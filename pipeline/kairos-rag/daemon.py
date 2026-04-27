#!/usr/bin/env python3
"""kairos-rag-daemon — unix-socket RAG retrieval for KAIROS pipeline.

Listens on /run/karios/rag.sock. Reads newline-delimited JSON requests from
connected clients, returns newline-delimited JSON responses.

FAIL-OPEN: any internal error returns {"error": str, "category": str} — the
daemon MUST NOT raise back to the client. The client (a Hermes plugin running
inside every agent subprocess) re-raises would kill the Hermes session.

Socket API contract v2 (re-ranking enabled):

  REQUEST (one JSON object per line):
    {
      "query":      str,            # required, non-empty
      "top_k":      int,            # optional, default 5 — final hits returned
      "filter":     dict | null,    # optional Qdrant filter
      "timeout_ms": int,            # optional, default 5000
      "trace_id":   str | null      # optional Langfuse parent trace
    }

  RESPONSE (one JSON object per line):
    {
      "hits": [
        {"text": str, "source": str, "score": float, "metadata": {...}}
      ],
      "timing_ms": {"embed": int, "qdrant": int, "rerank": int}
    }
    Note: "score" is the cross-encoder score when reranking is active,
    otherwise the Qdrant cosine score.

  ERROR (one JSON object per line):
    {
      "error": str,
      "category": "timeout" | "embed_failed" | "qdrant_failed" | "bad_request" | "unknown"
    }

Re-ranking (v2):
  Internally retrieves top_k * RETRIEVE_MULT (default 4, capped at 50) from
  Qdrant, then applies cross-encoder re-ranking (ms-marco-MiniLM-L-6-v2) to
  return only the top_k most relevant results.
  FAIL-OPEN: if re-ranking is unavailable (model not loaded, inference error),
  returns dense-only results without raising.
  Disable: KAIROS_RAG_RERANK_DISABLED=1
"""

import asyncio
import concurrent.futures
import json
import math
import os
import re
import signal
import time
import traceback
import urllib.request
import urllib.error
from pathlib import Path

OLLAMA_URL    = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
QDRANT_URL    = os.environ.get("QDRANT_URL", "http://127.0.0.1:6333")
COLLECTION    = os.environ.get("KAIROS_RAG_COLLECTION", "kairos_rag")
EMBED_MODEL   = os.environ.get("KAIROS_RAG_EMBED_MODEL", "nomic-embed-text:v1.5")
SOCKET_PATH   = os.environ.get("KAIROS_RAG_SOCKET", "/run/karios/rag.sock")
LANGFUSE_URL  = os.environ.get("LANGFUSE_URL", "")
LANGFUSE_PK   = os.environ.get("LANGFUSE_PK", "")
LANGFUSE_SK   = os.environ.get("LANGFUSE_SK", "")
MAX_CONCURRENT = int(os.environ.get("KAIROS_RAG_MAX_CONCURRENT", "2"))
DEFAULT_TIMEOUT_MS = int(os.environ.get("KAIROS_RAG_TIMEOUT_MS", "5000"))

# Re-ranking config
RERANK_MODEL  = os.environ.get("KAIROS_RAG_RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
RETRIEVE_MULT = int(os.environ.get("KAIROS_RAG_RETRIEVE_MULT", "4"))  # retrieve Nx, return top_k
RERANK_DISABLED = os.environ.get("KAIROS_RAG_RERANK_DISABLED", "").lower() in ("1", "true", "yes")

# Chunking config — defaults match /etc/kairos-rag/corpus.yaml so dedup chunks
# match the indexer's chunks at retrieval time. Env vars allow operations to
# drift later if the indexer's corpus.yaml changes.
CHUNK_MAX_CHARS = int(os.environ.get("KAIROS_RAG_CHUNK_MAX_CHARS", "2000"))
CHUNK_OVERLAP   = int(os.environ.get("KAIROS_RAG_CHUNK_OVERLAP", "200"))

# Dedup-side pre-filter: drop chunks whose stripped length is below this
# threshold BEFORE max-pool reduction. Motivated by D2-tune finding that
# header-only chunks (e.g. '## Key Technical Details\n\n\n', 27 chars) appear
# verbatim across unrelated shards and dominate max-pool, collapsing the
# similar/dissimilar gap (4 dissimilar pairs scored exactly 0.9921310257994065).
# Retrieval has cross-encoder re-rank as a noise filter; dedup has nothing —
# this is the dedup-side analogue (cf. ColBERT punctuation-token filtering).
# Naming is dedup-specific; the indexer's chunkers are NOT modified.
DEDUP_MIN_CHUNK_CHARS = int(os.environ.get("KAIROS_RAG_DEDUP_MIN_CHUNK_CHARS", "32"))

# Dedup-side reduction: top-k mean over chunk-pair cosine matrix.
# Motivated by D3-tune cluster gap of -0.1348 (residual false-positives at
# threshold 0.78 are real semantic overlap on infrastructure vocabulary; pure
# max-pool inflates these because a single high-cosine chunk pair drives the
# whole score). Top-k mean dampens single-region inflation while keeping the
# identical-pair invariant (every diagonal cell = 1.0 → top-3 mean = 1.0).
# k clamps to len(matrix) so single-cell matrices degrade gracefully to max-pool.
DEDUP_TOPK = int(os.environ.get("KAIROS_RAG_DEDUP_TOPK", "3"))


# ---------------------------------------------------------------------------
# Chunkers — VERBATIM copy from /usr/local/bin/kairos-rag-indexer (lines 124-156).
# Source of truth is the indexer; keep in sync — drift here breaks the
# indexer/dedup semantic match (chunk-level retrieval vs. chunk-level dedup).
# Do not refactor or "improve" these.
# ---------------------------------------------------------------------------

def chunk_markdown(text, max_chars, overlap):
    parts = re.split(r"(^#{1,6} .+?$)", text, flags=re.MULTILINE)
    blocks, current = [], ""
    for p in parts:
        if re.match(r"^#{1,6} ", p or ""):
            if current.strip():
                blocks.append(current)
            current = p + "\n"
        else:
            current += p or ""
    if current.strip():
        blocks.append(current)
    out = []
    for b in blocks:
        if len(b) <= max_chars:
            out.append(b)
        else:
            i = 0
            while i < len(b):
                out.append(b[i:i + max_chars])
                i += max(1, max_chars - overlap)
    return out


def chunk_generic(text, max_chars, overlap):
    if len(text) <= max_chars:
        return [text]
    out, i = [], 0
    while i < len(text):
        out.append(text[i:i + max_chars])
        i += max(1, max_chars - overlap)
    return out

# ---------------------------------------------------------------------------
# Cross-encoder re-ranker — lazy-loaded on first request
# ---------------------------------------------------------------------------

_RERANK_MODEL_INSTANCE = None   # None = not yet loaded; False = failed; CrossEncoder = ready
_RERANK_LOCK = None             # asyncio.Lock, set in main()


async def _get_reranker():
    """Lazy-load the cross-encoder. Returns the model or None (fail-open)."""
    global _RERANK_MODEL_INSTANCE
    if RERANK_DISABLED:
        return None
    if _RERANK_MODEL_INSTANCE is False:
        return None
    if _RERANK_MODEL_INSTANCE is not None:
        return _RERANK_MODEL_INSTANCE
    async with _RERANK_LOCK:
        if _RERANK_MODEL_INSTANCE is not None:
            return _RERANK_MODEL_INSTANCE if _RERANK_MODEL_INSTANCE is not False else None
        loop = asyncio.get_running_loop()
        try:
            def _load():
                from sentence_transformers import CrossEncoder
                model = CrossEncoder(RERANK_MODEL)
                # Warm up with a dummy pair to trigger any lazy init
                model.predict([["warmup query", "warmup doc"]])
                return model
            model = await loop.run_in_executor(_RERANK_POOL, _load)
            _RERANK_MODEL_INSTANCE = model
            print(f"[rag-daemon] reranker ready: {RERANK_MODEL}", flush=True)
        except Exception as e:
            _RERANK_MODEL_INSTANCE = False
            print(f"[rag-daemon] reranker unavailable (fail-open): {e}", flush=True)
        return _RERANK_MODEL_INSTANCE if _RERANK_MODEL_INSTANCE is not False else None


def _http_post_json_sync(url: str, body: dict, timeout: float) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


async def embed_query(query: str, timeout_s: float) -> list:
    loop = asyncio.get_running_loop()

    def _do():
        return _http_post_json_sync(
            f"{OLLAMA_URL}/api/embeddings",
            {"model": EMBED_MODEL, "prompt": query},
            timeout=timeout_s,
        )

    data = await loop.run_in_executor(_HOT_POOL, _do)
    return data["embedding"]


async def qdrant_search(vector: list, top_k: int, filt, timeout_s: float):
    loop = asyncio.get_running_loop()
    body = {"vector": vector, "limit": top_k, "with_payload": True}
    if filt:
        body["filter"] = filt

    def _do():
        return _http_post_json_sync(
            f"{QDRANT_URL}/collections/{COLLECTION}/points/search",
            body,
            timeout=timeout_s,
        )

    data = await loop.run_in_executor(_HOT_POOL, _do)
    return data.get("result", [])


async def langfuse_span(trace_id, query, timing_ms, hit_count, error):
    """Best-effort Langfuse span. Never raises. Isolated from request hot-path executor."""
    if not (LANGFUSE_URL and trace_id):
        return
    try:
        body = {
            "id": f"kairos_rag_{int(time.time() * 1000)}",
            "traceId": trace_id,
            "name": "kairos_rag_query",
            "startTime": time.time(),
            "input": {"query": query[:200]},
            "output": {"hit_count": hit_count, "error": error or ""},
            "metadata": timing_ms,
        }
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                _LF_POOL,
                lambda: _http_post_json_sync(
                    f"{LANGFUSE_URL}/api/public/ingestion",
                    {"batch": [{"type": "generation-create", "id": body["id"], "timestamp": time.time(), "body": body}]},
                    timeout=0.5,
                ),
            )
        except RuntimeError:
            pass
    except Exception:
        pass  # fail-open


SEM = None  # set in main()

# Hot-path pool — embed + qdrant ONLY. Never used by re-ranker.
# Keeps PyTorch OpenMP threads from starving embed/qdrant threads.
_HOT_POOL = concurrent.futures.ThreadPoolExecutor(
    max_workers=max(4, MAX_CONCURRENT * 2), thread_name_prefix="kairos-rag-hot"
)

# Re-rank pool — isolated so PyTorch thread explosion can't starve _HOT_POOL.
# max_workers=2 allows two concurrent re-rank calls (one per SEM slot).
_RERANK_POOL = concurrent.futures.ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="kairos-rag-rerank"
)

_LF_POOL = concurrent.futures.ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="kairos-rag-lf"
)

_LF_TASKS: set = set()


async def _embed_one(text: str, timeout_s: float) -> list:
    """Embed a single text via Ollama. Reuses _http_post_json_sync on _HOT_POOL.

    Same shape as embed_query() but without the 'query' field-name coupling, so
    the score_pairs handler can batch arbitrary text without semantic confusion.
    """
    loop = asyncio.get_running_loop()

    def _do():
        return _http_post_json_sync(
            f"{OLLAMA_URL}/api/embeddings",
            {"model": EMBED_MODEL, "prompt": text},
            timeout=timeout_s,
        )

    data = await loop.run_in_executor(_HOT_POOL, _do)
    return data["embedding"]


def _cosine_clamped(a: list, b: list) -> float:
    """Cosine similarity in [0,1]. Negative cosines clamp to 0; over-1 clamps to 1.

    Robust whether nomic-embed-text returns L2-normalized vectors or not.
    """
    if len(a) != len(b) or not a:
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    cos = dot / (math.sqrt(na) * math.sqrt(nb))
    if cos < 0.0:
        return 0.0
    if cos > 1.0:
        return 1.0
    return cos


async def handle_score_pairs(req: dict) -> dict:
    """Embed pairs of texts and return cosine similarity per pair.

    R1 design: reuses existing Ollama nomic-embed-text via _embed_one on
    _HOT_POOL. Batches the unique-text set so N pairs sharing texts cost the
    number of distinct texts, not 2N, calls.
    """
    pairs = req.get("pairs")
    if not isinstance(pairs, list) or not pairs:
        return {"error": "'pairs' must be a non-empty list", "category": "bad_request"}
    for p in pairs:
        if not (isinstance(p, (list, tuple)) and len(p) == 2
                and isinstance(p[0], str) and isinstance(p[1], str)):
            return {"error": "each pair must be a 2-element list of strings",
                    "category": "bad_request"}

    try:
        timeout_ms = int(req.get("timeout_ms", DEFAULT_TIMEOUT_MS))
    except (TypeError, ValueError):
        timeout_ms = DEFAULT_TIMEOUT_MS
    timeout_ms = max(500, min(timeout_ms, 30000))
    embed_timeout = max(0.5, min(timeout_ms / 1000.0 * 0.9, 8.0))

    # Dedup texts preserving first-seen order, then chunk each text using the
    # same chunker the indexer uses (chunk_markdown — falls through to
    # generic-style splitting on text without markdown headers). Embed at the
    # chunk level so dedup similarity matches chunk-level retrieval similarity.
    unique_texts = list(dict.fromkeys(t for pair in pairs for t in pair))
    text_chunks = {
        t: chunk_markdown(t, CHUNK_MAX_CHARS, CHUNK_OVERLAP) for t in unique_texts
    }
    # D3: drop chunks whose stripped length is below DEDUP_MIN_CHUNK_CHARS
    # before max-pool. Per-text fallback: if filtering removes ALL chunks for
    # a given text (tiny shard whose only chunk is sub-threshold), keep the
    # original chunk set FOR THAT TEXT ONLY rather than emit 0.0 / None.
    for _t, _cs in list(text_chunks.items()):
        _kept = [c for c in _cs if len(c.strip()) >= DEDUP_MIN_CHUNK_CHARS]
        if _kept:
            text_chunks[_t] = _kept
    # Flat chunk-level dedup across all texts.
    unique_chunks = list(dict.fromkeys(c for cs in text_chunks.values() for c in cs))

    async with SEM:
        t_embed = time.monotonic()
        try:
            chunk_vectors = await asyncio.wait_for(
                asyncio.gather(*[_embed_one(c, embed_timeout) for c in unique_chunks]),
                timeout=embed_timeout * 2,
            )
        except asyncio.TimeoutError:
            return {"error": f"embed timeout after {embed_timeout:.1f}s", "category": "timeout"}
        except urllib.error.HTTPError as e:
            return {"error": f"embed http {e.code}: {e.reason}", "category": "embed_failed"}
        except Exception as e:
            return {"error": f"embed failed: {type(e).__name__}: {e}", "category": "embed_failed"}
        embed_ms = int((time.monotonic() - t_embed) * 1000)

        emb_map = dict(zip(unique_chunks, chunk_vectors))
        t_score = time.monotonic()
        # D4: top-k mean over chunk-pair cosine matrix. For pair (a, b) build
        # the K_a x K_b cosine matrix in flat form, then average the top-k
        # cells (k clamped to len(matrix)). Identical-pair invariant holds:
        # every diagonal cell is 1.0, so top-k mean = 1.0. Single-cell
        # matrices degrade to max-pool. _cosine_clamped already returns [0,1]
        # so the mean is in [0,1]; the explicit clamp is numerical safety.
        scores = []
        for (a, b) in pairs:
            a_chunks = text_chunks[a]
            b_chunks = text_chunks[b]
            if not a_chunks or not b_chunks:
                scores.append(0.0)
                continue
            matrix_flat = []
            for ca in a_chunks:
                va = emb_map[ca]
                for cb in b_chunks:
                    matrix_flat.append(_cosine_clamped(va, emb_map[cb]))
            k = min(DEDUP_TOPK, len(matrix_flat))
            topk = sorted(matrix_flat, reverse=True)[:k]
            score = sum(topk) / k
            scores.append(max(0.0, min(1.0, score)))
        score_ms = int((time.monotonic() - t_score) * 1000)

    return {"scores": scores, "timing_ms": {"embed": embed_ms, "score": score_ms}}


async def handle_request(req: dict) -> dict:
    if not isinstance(req, dict):
        return {"error": "request must be a JSON object", "category": "bad_request"}
    if req.get("op") == "score_pairs":
        return await handle_score_pairs(req)
    query = req.get("query", "")
    if not isinstance(query, str) or not query.strip():
        return {"error": "'query' field required (non-empty string)", "category": "bad_request"}

    try:
        top_k = int(req.get("top_k", 5))
    except (TypeError, ValueError):
        return {"error": "'top_k' must be int", "category": "bad_request"}
    top_k = max(1, min(top_k, 50))

    filter_dict = req.get("filter")
    if filter_dict is not None and not isinstance(filter_dict, dict):
        return {"error": "'filter' must be object or null", "category": "bad_request"}

    try:
        timeout_ms = int(req.get("timeout_ms", DEFAULT_TIMEOUT_MS))
    except (TypeError, ValueError):
        timeout_ms = DEFAULT_TIMEOUT_MS
    timeout_ms = max(500, min(timeout_ms, 30000))

    trace_id = req.get("trace_id")
    if trace_id is not None and not isinstance(trace_id, str):
        trace_id = None

    timing_ms = {}

    # Retrieve more candidates for re-ranking; capped at 50 to keep Qdrant fast
    retrieve_k = min(top_k * RETRIEVE_MULT, 50) if not RERANK_DISABLED else top_k

    async with SEM:
        # Embed gets up to 50% of budget, cap raised to 8s to absorb Ollama cold-start
        embed_timeout = max(0.5, min(timeout_ms / 1000.0 * 0.5, 8.0))
        t_embed = time.monotonic()
        try:
            vector = await asyncio.wait_for(embed_query(query, embed_timeout), timeout=embed_timeout)
        except asyncio.TimeoutError:
            return {"error": f"embed timeout after {embed_timeout:.1f}s", "category": "timeout"}
        except urllib.error.HTTPError as e:
            return {"error": f"embed http {e.code}: {e.reason}", "category": "embed_failed"}
        except Exception as e:
            return {"error": f"embed failed: {type(e).__name__}: {e}", "category": "embed_failed"}
        timing_ms["embed"] = int((time.monotonic() - t_embed) * 1000)

        # Qdrant gets remaining budget minus 0.2s headroom for rerank
        search_timeout = max(0.5, (timeout_ms / 1000.0) - timing_ms["embed"] / 1000.0 - 0.2)
        t_q = time.monotonic()
        try:
            hits = await asyncio.wait_for(
                qdrant_search(vector, retrieve_k, filter_dict, search_timeout), timeout=search_timeout
            )
        except asyncio.TimeoutError:
            return {"error": f"qdrant timeout after {search_timeout:.1f}s", "category": "timeout"}
        except urllib.error.HTTPError as e:
            return {"error": f"qdrant http {e.code}: {e.reason}", "category": "qdrant_failed"}
        except Exception as e:
            return {"error": f"qdrant search failed: {type(e).__name__}: {e}", "category": "qdrant_failed"}
        timing_ms["qdrant"] = int((time.monotonic() - t_q) * 1000)

        # Re-rank if we fetched more candidates than needed
        t_rerank = time.monotonic()
        timing_ms["rerank"] = 0
        if len(hits) > top_k:
            reranker = await _get_reranker()
            if reranker is not None:
                try:
                    pairs = [[query, h.get("payload", {}).get("text", "") or ""] for h in hits]
                    scores = await asyncio.get_running_loop().run_in_executor(
                        _RERANK_POOL, reranker.predict, pairs
                    )
                    # Sort by cross-encoder score descending, take top_k
                    ranked = sorted(zip(scores, hits), key=lambda x: float(x[0]), reverse=True)
                    hits = [h for _, h in ranked[:top_k]]
                    # Annotate with rerank scores for transparency
                    for (score, _), h in zip(ranked[:top_k], hits):
                        h["_rerank_score"] = float(score)
                    timing_ms["rerank"] = int((time.monotonic() - t_rerank) * 1000)
                except Exception as e:
                    print(f"[rag-daemon] rerank failed (fail-open): {e}", flush=True)
                    hits = hits[:top_k]
            else:
                hits = hits[:top_k]
        else:
            hits = hits[:top_k]

    hits_out = []
    for h in hits:
        payload = h.get("payload", {}) or {}
        entry = {
            "text": payload.get("text", ""),
            "source": payload.get("source", ""),
            "score": h.get("_rerank_score", float(h.get("score", 0.0))),
            "metadata": {k: v for k, v in payload.items() if k not in ("text",)},
        }
        hits_out.append(entry)

    t = asyncio.create_task(langfuse_span(trace_id, query, timing_ms, len(hits_out), None))
    _LF_TASKS.add(t)
    t.add_done_callback(_LF_TASKS.discard)

    return {"hits": hits_out, "timing_ms": timing_ms}


async def handle_client(reader, writer):
    peer = writer.get_extra_info("peername") or "unix"
    try:
        while True:
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=60.0)
            except asyncio.TimeoutError:
                break
            if not line:
                break
            try:
                req = json.loads(line.decode("utf-8"))
                resp = await handle_request(req)
            except json.JSONDecodeError as e:
                resp = {"error": f"malformed JSON: {e}", "category": "bad_request"}
            except Exception as e:
                resp = {
                    "error": f"unexpected: {type(e).__name__}: {e}",
                    "category": "unknown",
                }
                print(f"[rag-daemon] unexpected in handle_request: {traceback.format_exc()}", flush=True)
            try:
                writer.write((json.dumps(resp) + "\n").encode("utf-8"))
                await writer.drain()
            except Exception:
                break
    except Exception as e:
        print(f"[rag-daemon] client loop error peer={peer}: {e}", flush=True)
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def main():
    global SEM, _RERANK_LOCK
    SEM = asyncio.Semaphore(MAX_CONCURRENT)
    _RERANK_LOCK = asyncio.Lock()

    sock_dir = Path(SOCKET_PATH).parent
    sock_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(sock_dir, 0o755)
    except PermissionError:
        pass
    try:
        os.unlink(SOCKET_PATH)
    except FileNotFoundError:
        pass
    except PermissionError:
        pass

    server = await asyncio.start_unix_server(handle_client, path=SOCKET_PATH, limit=8 * 1024 * 1024)
    try:
        os.chmod(SOCKET_PATH, 0o666)
    except Exception:
        pass

    stop_event = asyncio.Event()

    def _stop(*_):
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            pass

    rerank_status = "disabled" if RERANK_DISABLED else f"model={RERANK_MODEL} retrieve_mult={RETRIEVE_MULT}x"
    print(
        f"[rag-daemon] listening on {SOCKET_PATH} "
        f"(collection={COLLECTION}, model={EMBED_MODEL}, "
        f"max_concurrent={MAX_CONCURRENT}, rerank={rerank_status})",
        flush=True,
    )

    # Pre-warm the re-ranker in background so first agent call isn't slow
    if not RERANK_DISABLED:
        asyncio.create_task(_get_reranker())

    async with server:
        serve_task = asyncio.create_task(server.serve_forever())
        stop_task = asyncio.create_task(stop_event.wait())
        done, pending = await asyncio.wait({serve_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
        print("[rag-daemon] shutting down", flush=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
