"""kairos_rag — Hermes plugin for KAIROS semantic retrieval.

Registers a `pre_llm_call` hook that, on the first turn of each session,
queries the kairos-rag daemon at /run/karios/rag.sock and returns retrieved
context to be injected into the user message (never the system prompt,
so prompt-cache prefix remains stable).

FAIL-OPEN: any error — socket unreachable, daemon crashed, timeout, bad
response — is caught, logged to stderr with the sentinel
`KAIROS_RAG_ERROR {json}` (consumed by agent-worker PTY reader per v10.2
design), and the hook returns None. A raise from a plugin hook callback
gets logged by the PluginManager but won't crash Hermes — still, we
belt-and-suspenders to guarantee the pipeline is never disrupted.

Gating (in order of precedence, checked on every call):
  1. Env `KAIROS_RAG_DISABLED=1` → skip
  2. File `/etc/kairos-rag/enabled` missing → skip (default OFF)
  3. File `/etc/kairos-rag/disabled.<profile>` exists → skip for that agent

Per-profile source_kind filters can be configured in
`/etc/kairos-rag/profiles.yaml` (optional; sensible defaults per agent).

Returns: {"context": "<formatted hits>"} or None.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
import traceback
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration (env + files; all with safe defaults)
# ---------------------------------------------------------------------------

SOCKET_PATH  = os.environ.get("KAIROS_RAG_SOCKET", "/run/karios/rag.sock")
TIMEOUT_MS   = int(os.environ.get("KAIROS_RAG_PLUGIN_TIMEOUT_MS", "8000"))  # v7.97 H8: 5000 -> 8000; socket timeout = 9.0s absorbs SEM queue wait (4.8s) + one execution slot (4.8s) for 5th+ concurrent request
TOP_K        = int(os.environ.get("KAIROS_RAG_PLUGIN_TOP_K", "5"))
MAX_CTX_CHARS = int(os.environ.get("KAIROS_RAG_MAX_CONTEXT_CHARS", "6000"))

ENABLE_FLAG        = Path(os.environ.get("KAIROS_RAG_ENABLE_FLAG",  "/etc/kairos-rag/enabled"))
PROFILE_DISABLE_DIR = Path(os.environ.get("KAIROS_RAG_DISABLE_DIR", "/etc/kairos-rag"))
PROFILES_CONFIG    = Path(os.environ.get("KAIROS_RAG_PROFILES_CONFIG", "/etc/kairos-rag/profiles.yaml"))

# Per-profile source_kind filter defaults. Keys are Hermes profile names.
# Each maps to a list of allowed source_kind values; empty list = no filter.
DEFAULT_PROFILE_FILTERS = {
    "backend":                 ["code_karios_migration", "code_karios_core", "code_karios_bootstrap", "vault_raw", "vault_wiki"],
    "frontend":                ["code_karios_web_ts", "code_karios_web_md", "vault_raw", "vault_wiki"],
    "architect":               ["vault_raw", "vault_wiki", "code_karios_migration", "code_karios_core"],
    "architect-blind-tester":  ["vault_raw", "vault_wiki", "code_karios_migration"],
    "code-blind-tester":       ["code_karios_playwright", "code_karios_migration", "vault_raw", "vault_wiki"],
    "tester":                  ["code_karios_playwright", "code_karios_migration", "vault_raw"],
    "devops":                  ["vault_raw", "vault_wiki", "code_karios_bootstrap", "code_karios_migration"],
    "monitor":                 ["vault_raw", "vault_wiki"],
    "orchestrator":            ["vault_raw", "vault_wiki"],
}


# ---------------------------------------------------------------------------
# Stderr logging with KAIROS_RAG sentinels (consumed by agent-worker PTY reader)
# ---------------------------------------------------------------------------

# PTY line buffer effective max — keep sentinels under this to avoid mid-line
# truncation when multiple subprocess writers share the Hermes stderr PTY.
_MAX_SENTINEL_BYTES = 2048


def _atomic_stderr_line(prefix: str, payload: dict) -> None:
    """Write a single `prefix {json}\\n` line via os.write(2) — atomic up to PIPE_BUF.

    Multi-process Hermes can have concurrent writers to the same PTY. `sys.stderr.write`
    is NOT guaranteed atomic across processes (may interleave mid-line). os.write()
    of a single buffer <= PIPE_BUF (4096 on Linux) IS atomic. Keeping sentinels
    under _MAX_SENTINEL_BYTES protects against truncation + interleaving.
    """
    try:
        line = f"{prefix} {json.dumps(payload)}\n"
        buf = line.encode("utf-8", errors="replace")
        if len(buf) > _MAX_SENTINEL_BYTES:
            # Re-encode with aggressively shortened detail to fit
            shortened = dict(payload)
            if "detail" in shortened:
                shortened["detail"] = str(shortened["detail"])[:200] + "...[truncated]"
            for k in list(shortened.keys()):
                if k not in ("category", "event", "t", "detail"):
                    shortened[k] = str(shortened[k])[:80]
            line = f"{prefix} {json.dumps(shortened)}\n"
            buf = line.encode("utf-8", errors="replace")[:_MAX_SENTINEL_BYTES]
            # Ensure we still end with newline after truncation
            if not buf.endswith(b"\n"):
                buf = buf[:-1] + b"\n"
        os.write(2, buf)  # atomic up to PIPE_BUF; bypasses Python's stderr buffer
    except Exception:
        # Absolute last resort — we CANNOT let a logging failure break the callback
        pass


def _log_error(category: str, detail: str, **fields):
    """Emit `KAIROS_RAG_ERROR {json}` on its own line to stderr.

    agent-worker parses these sentinels in its PTY stream_reader and forwards
    to Redis pubsub `kairos:rag:events`, which dispatcher attaches as a
    Langfuse child span on the gap trace. Never raises.
    """
    payload = {
        "category": category,
        "detail": str(detail)[:500],
        "t": time.time(),
        **{k: str(v)[:200] for k, v in fields.items()},
    }
    _atomic_stderr_line("KAIROS_RAG_ERROR", payload)


def _log_event(event: str, **fields):
    """Emit `KAIROS_RAG_EVENT {json}` for informational events (hit count, timing)."""
    payload = {"event": event, "t": time.time(), **{k: str(v)[:200] for k, v in fields.items()}}
    _atomic_stderr_line("KAIROS_RAG_EVENT", payload)


# ---------------------------------------------------------------------------
# Gating — 3 checks before we do any work
# ---------------------------------------------------------------------------

def _get_profile() -> str:
    """Resolve which Hermes profile we're running under.

    Hermes sets HERMES_HOME=/root/.hermes/profiles/<profile>/ per agent.
    Fall back to HERMES_AGENT env or 'unknown'.
    """
    hermes_home = os.environ.get("HERMES_HOME", "")
    if hermes_home:
        # .../profiles/backend/ → backend
        parts = hermes_home.rstrip("/").split("/")
        if len(parts) >= 2 and parts[-2] == "profiles":
            return parts[-1]
    return os.environ.get("HERMES_AGENT", "unknown")


def _is_enabled(profile: str) -> tuple[bool, str]:
    """Return (enabled, reason). Reason used for telemetry only."""
    if os.environ.get("KAIROS_RAG_DISABLED", "").strip() in ("1", "true", "yes"):
        return False, "env_disabled"
    if not ENABLE_FLAG.exists():
        return False, "enable_flag_missing"
    disable_file = PROFILE_DISABLE_DIR / f"disabled.{profile}"
    if disable_file.exists():
        return False, "profile_disabled"
    return True, "enabled"


# ---------------------------------------------------------------------------
# Per-profile source_kind filter — loaded once, refreshed per call cheaply
# ---------------------------------------------------------------------------

def _load_profile_filters() -> dict:
    """Read /etc/kairos-rag/profiles.yaml if present. Fall back to defaults."""
    if not PROFILES_CONFIG.exists():
        return DEFAULT_PROFILE_FILTERS
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(PROFILES_CONFIG.read_text()) or {}
        filters = data.get("profiles", {})
        if not isinstance(filters, dict):
            return DEFAULT_PROFILE_FILTERS
        # Merge with defaults so missing profiles still work
        merged = dict(DEFAULT_PROFILE_FILTERS)
        for k, v in filters.items():
            if isinstance(v, list):
                merged[k] = v
        return merged
    except Exception as exc:
        _log_error("profile_filter_read_failed", str(exc))
        return DEFAULT_PROFILE_FILTERS


# Fallback used when the profile name isn't in DEFAULT_PROFILE_FILTERS.
# Without this, an unknown profile triggers an unbounded search across every
# indexed corpus — a cross-agent info leak + performance footgun.
UNKNOWN_PROFILE_FALLBACK = ["vault_raw", "vault_wiki"]


def _filter_for(profile: str) -> dict:
    """Always returns a bounded filter — never None. Unknown profile → vault-only."""
    filters = _load_profile_filters()
    kinds = filters.get(profile)
    if not kinds:
        _log_event("unknown_profile_fallback", profile=profile, fallback=UNKNOWN_PROFILE_FALLBACK)
        kinds = UNKNOWN_PROFILE_FALLBACK
    return {"must": [{"key": "source_kind", "match": {"any": kinds}}]}


# ---------------------------------------------------------------------------
# Socket client — one-shot query, fail-open
# ---------------------------------------------------------------------------

def _query_daemon(query: str, top_k: int, flt: dict | None, trace_id: str | None) -> dict | None:
    """Return the daemon's JSON response dict, or None on any failure."""
    req = {
        "query":      query[:4000],  # don't send multi-MB messages
        "top_k":      top_k,
        "timeout_ms": TIMEOUT_MS,
    }
    if flt is not None:
        req["filter"] = flt
    if trace_id:
        req["trace_id"] = trace_id

    s = None
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(TIMEOUT_MS / 1000.0 + 1.0)  # socket timeout slightly > daemon timeout
        s.connect(SOCKET_PATH)
        s.sendall((json.dumps(req) + "\n").encode("utf-8"))
        buf = b""
        # Read until newline
        deadline = time.monotonic() + (TIMEOUT_MS / 1000.0 + 1.0)
        while time.monotonic() < deadline:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
            if b"\n" in buf:
                break
        if b"\n" not in buf:
            _log_error("daemon_no_response", "no newline received", sock=SOCKET_PATH)
            return None
        return json.loads(buf.split(b"\n", 1)[0].decode("utf-8"))
    except FileNotFoundError:
        _log_error("socket_missing", "daemon socket not present", sock=SOCKET_PATH)
        return None
    except ConnectionRefusedError:
        _log_error("daemon_not_listening", "socket exists but not accepting", sock=SOCKET_PATH)
        return None
    except socket.timeout:
        _log_error("socket_timeout", f"timeout_ms={TIMEOUT_MS}")
        return None
    except json.JSONDecodeError as e:
        _log_error("daemon_malformed_response", str(e))
        return None
    except Exception as e:
        _log_error("socket_unexpected", f"{type(e).__name__}: {e}")
        return None
    finally:
        if s is not None:
            try:
                s.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Context formatter — compact, token-bounded, source-attributed
# ---------------------------------------------------------------------------

def _format_hits(hits: list, max_chars: int) -> str:
    if not hits:
        return ""
    lines = ["[KAIROS_RAG retrieved context — semantic top-K for this task]", ""]
    used = sum(len(l) + 1 for l in lines)
    for h in hits:
        # Coerce wire types defensively — daemon currently sends strings/floats
        # but we cannot trust a wire partner to stay in contract forever.
        text = str(h.get("text") or "").strip()
        source = str(h.get("source", ""))
        try:
            score = float(h.get("score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        kind = str((h.get("metadata", {}) or {}).get("source_kind", ""))
        short_source = source[-90:] if len(source) > 90 else source
        header = f"## [{kind}] ...{short_source} (cosine={score:.3f})"
        block = f"{header}\n{text}\n---\n"
        if used + len(block) > max_chars:
            # Truncate the last chunk to fit budget
            remaining = max_chars - used - len(header) - 10
            if remaining > 200:
                block = f"{header}\n{text[:remaining]}…\n---\n"
                lines.append(block)
            break
        lines.append(block)
        used += len(block)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Hook callback — Hermes calls us; we must NEVER raise
# ---------------------------------------------------------------------------

def pre_llm_call(
    session_id=None,
    user_message: str = "",
    conversation_history=None,
    is_first_turn=None,            # was bool=True; explicit None-triggers safe bail
    model=None,
    platform=None,
    sender_id=None,
    **kwargs,
):
    """Return {"context": "..."} or None.

    MVP: retrieve only on first turn (is_first_turn IS True). Unknown/None/False
    exits silently. Previously `**_ignored` hid missing kwargs; now we preserve
    the name `kwargs` but only accept truthy True — not truthy non-bool.

    Per-turn retrieval is a Phase 2 refinement (needs query-rewriting).
    """
    try:
        # Strict is-first-turn check. None (signature drift) or False both bail.
        if is_first_turn is not True:
            return None
        query = (user_message or "").strip()
        if not query:
            return None

        profile = _get_profile()
        enabled, reason = _is_enabled(profile)
        if not enabled:
            # Emit event so we can verify the plugin loaded even while disabled
            _log_event("skipped", profile=profile, reason=reason)
            return None

        flt = _filter_for(profile)
        # session_id becomes the Langfuse trace_id for correlation
        trace_id = str(session_id) if session_id else None

        t0 = time.monotonic()
        resp = _query_daemon(query, TOP_K, flt, trace_id)
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        if resp is None:
            # daemon truly unreachable — socket missing/refused/timeout (per _query_daemon sentinels)
            _log_event("no_hits", profile=profile, elapsed_ms=elapsed_ms, reason="daemon_unreachable")
            return None
        if "error" in resp:
            # daemon reached but returned categorized error (timeout/embed_failed/qdrant_failed/bad_request)
            # Back-pressure (embed timeout) is operationally distinct from daemon-dead.
            err_cat = resp.get("category", "unknown")
            _log_event("no_hits", profile=profile, elapsed_ms=elapsed_ms, reason="daemon_error", rag_category=err_cat)
            return None

        hits = resp.get("hits", []) or []
        timing = resp.get("timing_ms", {})
        ctx = _format_hits(hits, MAX_CTX_CHARS)
        if not ctx:
            _log_event("no_hits", profile=profile, elapsed_ms=elapsed_ms, daemon_timing=timing)
            return None

        _log_event(
            "hits_injected",
            profile=profile,
            n_hits=len(hits),
            total_ms=elapsed_ms,
            daemon_timing=timing,
            ctx_chars=len(ctx),
        )
        return {"context": ctx}

    except Exception as e:
        # Belt-and-suspenders: the plugin manager has its own try/except,
        # but make absolutely sure a bug in our format logic can't surface.
        try:
            _log_error("callback_unexpected", f"{type(e).__name__}: {e}", tb=traceback.format_exc()[-500:])
        except Exception:
            pass
        return None


# ---------------------------------------------------------------------------
# Hermes plugin entry point
# ---------------------------------------------------------------------------

def register(ctx):
    """Hermes calls this once at plugin load. We register the pre_llm_call hook."""
    ctx.register_hook("pre_llm_call", pre_llm_call)
