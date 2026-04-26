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
import os
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


async def handle_request(req: dict) -> dict:
    if not isinstance(req, dict):
        return {"error": "request must be a JSON object", "category": "bad_request"}
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

    server = await asyncio.start_unix_server(handle_client, path=SOCKET_PATH)
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
