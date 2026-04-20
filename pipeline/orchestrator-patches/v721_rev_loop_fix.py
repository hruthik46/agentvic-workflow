"""v7.21 patches:
  A) agent-worker: lower watchdog threshold from 6000 → 3000 chars
  B) agent-worker: after watchdog retry STILL no tool_use → Telegram escalate
  C) dispatcher: when [COMPLETE] phase=3-coding from backend, check latest
     e2e-results.json — if rating < 8 + recent (<15min), route directly to
     CODE-REVISE via handle_e2e_results instead of pointless [API-SYNC]
"""
from pathlib import Path
import py_compile

# ── A + B: agent-worker patches ──────────────────────────────────────────────
aw = Path("/usr/local/bin/agent-worker")
aw_text = aw.read_text()

# A: lower watchdog threshold (search for the magic 6000 in stream_reader)
# Match the threshold check pattern
import re
old_count = aw_text.count(">= 6000")
if old_count == 0:
    old_count = aw_text.count("> 6000")
print(f"[v7.21-A] occurrences of 6000 threshold to lower: {old_count}")
aw_text = aw_text.replace("token_count[0] >= 6000", "token_count[0] >= 3000")
aw_text = aw_text.replace("token_count[0] > 6000", "token_count[0] > 3000")
aw_text = aw_text.replace("'WATCHDOG SIGTERMs at 6000 chars", "'WATCHDOG SIGTERMs at 3000 chars")
aw_text = aw_text.replace("Watchdog SIGTERMs at 6000 chars", "Watchdog SIGTERMs at 3000 chars")
aw_text = aw_text.replace("Watchdog kills prose-only at 6000 chars", "Watchdog kills prose-only at 3000 chars")
new_count = aw_text.count(">= 3000") + aw_text.count("> 3000")
print(f"[v7.21-A] now occurrences of 3000 threshold: at least {new_count}")

# B: escalate after watchdog retry-still-no-tool-use
RETRY_OLD = '''        retry_output = subprocess.run(
            [HERMES_CMD, "chat",
             "--profile", profile,
             "--query", retry_query,
             "--toolsets", "terminal,file,web",
             "-v"],
            capture_output=True, text=True, timeout=1800, cwd="/root"
        ).stdout + "\\n[WATCHDOG-RETRY]"
        # v7.19: close Langfuse span with retry metadata'''

RETRY_NEW = '''        retry_output = subprocess.run(
            [HERMES_CMD, "chat",
             "--profile", profile,
             "--query", retry_query,
             "--toolsets", "terminal,file,web",
             "-v"],
            capture_output=True, text=True, timeout=1800, cwd="/root"
        ).stdout + "\\n[WATCHDOG-RETRY]"
        # v7.21-B: escalate if retry STILL produced no tool_use (prose-mode persistent)
        if "tool_use" not in retry_output and len(retry_output) > 1500:
            try:
                import urllib.request as _v721_urlreq, urllib.parse as _v721_urlp
                _v721_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
                _v721_chat  = os.environ.get("TELEGRAM_CHAT_ID", "")
                if _v721_token and _v721_chat:
                    _v721_msg = (f"\u26a0\ufe0f *PROSE-MODE-STUCK* {AGENT}\\n"
                                 f"gap={gap_id or 'n/a'} trace={trace_id or 'n/a'}\\n"
                                 f"Watchdog killed Hermes once, retry STILL produced "
                                 f"{len(retry_output)} chars with 0 tool_use events.\\n"
                                 f"Manual intervention recommended.")
                    _v721_data = _v721_urlp.urlencode({
                        "chat_id": _v721_chat,
                        "text": _v721_msg,
                        "parse_mode": "Markdown",
                    }).encode()
                    _v721_url = f"https://api.telegram.org/bot{_v721_token}/sendMessage"
                    _v721_urlreq.urlopen(_v721_url, data=_v721_data, timeout=5)
                    print(f"[{AGENT}] v7.21-B prose-mode-stuck escalated to Telegram")
            except Exception as _v721_e:
                print(f"[{AGENT}] v7.21-B telegram escalate failed: {_v721_e}")
            # Write critique
            try:
                subprocess.run(
                    ["/usr/local/bin/karios-vault", "critique",
                     "--agent", AGENT,
                     "--failed", "PROSE-MODE-PERSISTENT — watchdog kill + retry both produced no tool_use",
                     "--task", (task or "")[:200],
                     "--trace", trace_id or "unknown"],
                    capture_output=True, timeout=10
                )
            except Exception:
                pass
        # v7.19: close Langfuse span with retry metadata'''

if "v7.21-B prose-mode-stuck" in aw_text:
    print("[v7.21-B] already wired")
elif RETRY_OLD in aw_text:
    aw_text = aw_text.replace(RETRY_OLD, RETRY_NEW, 1)
    print("[v7.21-B] post-retry escalation wired")
else:
    print("[v7.21-B] WARN: RETRY_OLD block not found exactly")

aw.write_text(aw_text)
try:
    py_compile.compile(str(aw), doraise=True)
    print("[v7.21-A+B] agent-worker syntax OK")
except Exception as e:
    print(f"[v7.21-A+B] SYNTAX ERROR: {e}")

# ── C: dispatcher [COMPLETE] phase=3-coding short-circuit ───────────────────
ed = Path("/var/lib/karios/orchestrator/event_dispatcher.py")
ed_text = ed.read_text()

OLD_API_SYNC = '''            elif n_phase == "3-coding" and n_current in ("3-coding", "2-arch-loop", "2-architecture"):
                # Coding complete → trigger API-SYNC gate (also accept arriving from 2-* if state lagged)
                gap_data = load_gap(gap_id) or {}
                gap_data["iteration_status"] = "awaiting_sync"
                gap_data["phase"] = "phase-3-coding"
                save_gap(gap_id, gap_data)
                send_to_agent("backend",
                            f"[API-SYNC] {gap_id} — ready for API contract verification",
                            f"gap_id={gap_id}\\niteration={iteration}\\ntrace_id={trace_id}\\n\\n"
                            "Verify the API contract against the implementation. "
                            "Report back with [CODING-COMPLETE] or [CODING-ERROR].",
                            gap_id=gap_id, trace_id=trace_id)
'''

NEW_API_SYNC = '''            elif n_phase == "3-coding" and n_current in ("3-coding", "2-arch-loop", "2-architecture"):
                # v7.21-C: if recent e2e-results.json exists with rating < 8, route to CODE-REVISE
                # instead of pointless [API-SYNC] (backend keeps prose-emitting [COMPLETE] without
                # actually fixing the build; firing [API-SYNC] just re-loops).
                _v721_skip_apisync = False
                try:
                    import time as _v721_t
                    _v721_results = list((IT_DIR / gap_id).rglob("e2e-results.json"))
                    if _v721_results:
                        _v721_results.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                        _v721_latest = _v721_results[0]
                        if (_v721_t.time() - _v721_latest.stat().st_mtime) < 900:  # <15 min old
                            _v721_data = json.loads(_v721_latest.read_text())
                            _v721_rating = _v721_data.get("rating", 10)
                            if _v721_rating < 8:
                                _v721_crit = _v721_data.get("critical_issues", [])
                                if not isinstance(_v721_crit, list):
                                    _v721_crit = []
                                print(f"[dispatcher] v7.21-C [COMPLETE] phase=3-coding for {gap_id} "
                                      f"BUT recent e2e (rating={_v721_rating}/10) failing — "
                                      f"routing to handle_e2e_results instead of [API-SYNC]")
                                handle_e2e_results(gap_id, iteration, _v721_rating,
                                                    _v721_crit,
                                                    _v721_data.get("test_results", {}),
                                                    _v721_data.get("dimensions", {}),
                                                    _v721_data.get("adversarial_tests", {}),
                                                    _v721_data.get("recommendation", "REQUEST_CHANGES"),
                                                    trace_id=trace_id)
                                _v721_skip_apisync = True
                except Exception as _v721_e:
                    print(f"[dispatcher] v7.21-C check failed (falling through to API-SYNC): {_v721_e}")

                if not _v721_skip_apisync:
                    # Coding complete → trigger API-SYNC gate (also accept arriving from 2-* if state lagged)
                    gap_data = load_gap(gap_id) or {}
                    gap_data["iteration_status"] = "awaiting_sync"
                    gap_data["phase"] = "phase-3-coding"
                    save_gap(gap_id, gap_data)
                    send_to_agent("backend",
                                f"[API-SYNC] {gap_id} — ready for API contract verification",
                                f"gap_id={gap_id}\\niteration={iteration}\\ntrace_id={trace_id}\\n\\n"
                                "Verify the API contract against the implementation. "
                                "Report back with [CODING-COMPLETE] or [CODING-ERROR].",
                                gap_id=gap_id, trace_id=trace_id)
'''

if "v7.21-C [COMPLETE] phase=3-coding" in ed_text:
    print("[v7.21-C] already patched")
elif OLD_API_SYNC in ed_text:
    ed_text = ed_text.replace(OLD_API_SYNC, NEW_API_SYNC, 1)
    ed.write_text(ed_text)
    print("[v7.21-C] short-circuit to handle_e2e_results when recent failing tests exist")
else:
    print("[v7.21-C] WARN: OLD_API_SYNC block not found exactly")

try:
    py_compile.compile(str(ed), doraise=True)
    print("[v7.21-C] dispatcher syntax OK")
except Exception as e:
    print(f"[v7.21-C] SYNTAX ERROR: {e}")
