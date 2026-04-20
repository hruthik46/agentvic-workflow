"""v7.19 patch — wire trace_hermes_call into agent-worker run_hermes_pty.

Adds:
  1. Langfuse init at module top (loads /etc/karios/secrets.env, soft-fails)
  2. Wraps run_hermes_pty body with trace_hermes_call context
  3. Emits generation observation with output length, tool_use events, exit code

Idempotent — re-runs are no-ops.
"""
from pathlib import Path
import py_compile

aw = Path("/usr/local/bin/agent-worker")
text = aw.read_text()

# 1. Add Langfuse imports near the top, after existing v7.18 zombie reaper import block
LF_IMPORT = '''
# v7.19: LLM-side Langfuse trace capture
try:
    sys.path.insert(0, "/root/agentic-workflow/pipeline/integrations/3-langfuse")
    # Load LANGFUSE_* from /etc/karios/secrets.env if not already in env
    import os as _v719_os
    _sec = "/etc/karios/secrets.env"
    if not _v719_os.environ.get("LANGFUSE_PUBLIC_KEY"):
        try:
            for _line in open(_sec).read().splitlines():
                if _line.startswith("LANGFUSE_") and "=" in _line:
                    _k, _, _v = _line.partition("=")
                    _v719_os.environ[_k.strip()] = _v.strip()
        except Exception:
            pass
    from kairos_langfuse_wrapper import init_langfuse as _v719_lf_init, trace_hermes_call as _v719_lf_hermes
    _V719_LF_OK = _v719_lf_init()
except Exception as _v719_e:
    _V719_LF_OK = False
    print(f"[agent-worker] v7.19 langfuse unavailable: {_v719_e}")
    from contextlib import contextmanager as _v719_cm
    @_v719_cm
    def _v719_lf_hermes(*a, **kw):
        yield None
'''

# Find the v7.18 zombie reaper import block and insert after it
ZR_MARKER = '''try:
    from zombie_reaper import reap_zombie_hermes_for_profile as _v718_reap
except Exception as _e:
    _v718_reap = None
    print(f"[agent-worker] v7.18 zombie-reaper unavailable: {_e}")
'''

if "_V719_LF_OK" in text:
    print("[v7.19] already patched")
elif ZR_MARKER in text:
    text = text.replace(ZR_MARKER, ZR_MARKER + LF_IMPORT, 1)
    print("[v7.19] Langfuse imports inserted after v7.18 zombie-reaper block")
else:
    print("[v7.19] WARN: ZR_MARKER not found; appending Langfuse block at top of imports")

# 2. Wrap run_hermes_pty body with trace_hermes_call
# Find the function signature line
PTY_SIG = '''def run_hermes_pty(task: str, agent_name: str, gap_id: str = None,
                   trace_id: str = None, phase: str = None) -> str:
'''
# Insert a tracing wrapper at the very start of the body (after docstring)
PTY_BODY_START_OLD = '''    """
    Run Hermes with PTY streaming for token-counting watchdog (Item E).

    Replaces subprocess.run in run_hermes(). Counts tokens and detects tool_use.
    If >4000 tokens with 0 tool_use events → SIGTERM and retry once.

    Falls back to subprocess.run if PTY unavailable.
    """
    import signal as _signal
'''

PTY_BODY_START_NEW = '''    """
    Run Hermes with PTY streaming for token-counting watchdog (Item E).

    Replaces subprocess.run in run_hermes(). Counts tokens and detects tool_use.
    If >4000 tokens with 0 tool_use events → SIGTERM and retry once.

    Falls back to subprocess.run if PTY unavailable.

    v7.19: wrapped with trace_hermes_call so every Hermes invocation is logged
    to Langfuse as a generation observation with tool_use count + exit code.
    """
    import signal as _signal
    # v7.19: open Langfuse generation span (no-op if Langfuse disabled)
    _v719_span_cm = None
    _v719_span = None
    try:
        if _V719_LF_OK:
            _v719_span_cm = _v719_lf_hermes(agent_name, "MiniMax-M2.7",
                                             prompt_chars=len(task or ""),
                                             gap_id=gap_id or "",
                                             trace_id=trace_id)
            _v719_span = _v719_span_cm.__enter__()
    except Exception as _v719_e:
        _v719_span_cm = None
'''

if "_v719_span_cm = _v719_lf_hermes" in text:
    print("[v7.19] run_hermes_pty already wrapped")
elif PTY_BODY_START_OLD in text:
    text = text.replace(PTY_BODY_START_OLD, PTY_BODY_START_NEW, 1)
    print("[v7.19] run_hermes_pty body opens Langfuse generation span")
else:
    print("[v7.19] WARN: PTY_BODY_START_OLD not found exactly")

# 3. Close span at the two return points: after retry and at normal end
# Original retry block:
RETRY_BLOCK_OLD = '''        retry_output = subprocess.run(
            [HERMES_CMD, "chat",
             "--profile", profile,
             "--query", retry_query,
             "--toolsets", "terminal,file,web",
             "-v"],
            capture_output=True, text=True, timeout=1800, cwd="/root"
        ).stdout + "\\n[WATCHDOG-RETRY]"
        return retry_output
'''

RETRY_BLOCK_NEW = '''        retry_output = subprocess.run(
            [HERMES_CMD, "chat",
             "--profile", profile,
             "--query", retry_query,
             "--toolsets", "terminal,file,web",
             "-v"],
            capture_output=True, text=True, timeout=1800, cwd="/root"
        ).stdout + "\\n[WATCHDOG-RETRY]"
        # v7.19: close Langfuse span with retry metadata
        try:
            if _v719_span is not None:
                _v719_span.update(output={"chars": len(retry_output),
                                           "tool_use_events": tool_use_events[0],
                                           "exit_code": exit_code,
                                           "watchdog_retry": True})
        except Exception:
            pass
        try:
            if _v719_span_cm is not None:
                _v719_span_cm.__exit__(None, None, None)
        except Exception:
            pass
        return retry_output
'''

if "_v719_span.update" in text:
    print("[v7.19] retry-return already patched")
elif RETRY_BLOCK_OLD in text:
    text = text.replace(RETRY_BLOCK_OLD, RETRY_BLOCK_NEW, 1)
    print("[v7.19] retry-return path closes Langfuse span")
else:
    print("[v7.19] WARN: RETRY_BLOCK_OLD not found exactly")

# Normal-return path
NORMAL_END_OLD = '''        ).stdout + "\\n[WATCHDOG-RETRY]"
        # v7.19: close Langfuse span with retry metadata
        try:
            if _v719_span is not None:
                _v719_span.update(output={"chars": len(retry_output),
                                           "tool_use_events": tool_use_events[0],
                                           "exit_code": exit_code,
                                           "watchdog_retry": True})
        except Exception:
            pass
        try:
            if _v719_span_cm is not None:
                _v719_span_cm.__exit__(None, None, None)
        except Exception:
            pass
        return retry_output

    return full_output
'''

NORMAL_END_NEW = '''        ).stdout + "\\n[WATCHDOG-RETRY]"
        # v7.19: close Langfuse span with retry metadata
        try:
            if _v719_span is not None:
                _v719_span.update(output={"chars": len(retry_output),
                                           "tool_use_events": tool_use_events[0],
                                           "exit_code": exit_code,
                                           "watchdog_retry": True})
        except Exception:
            pass
        try:
            if _v719_span_cm is not None:
                _v719_span_cm.__exit__(None, None, None)
        except Exception:
            pass
        return retry_output

    # v7.19: normal-return — close Langfuse span with success metadata
    try:
        if _v719_span is not None:
            _v719_span.update(output={"chars": len(full_output),
                                       "tool_use_events": tool_use_events[0],
                                       "exit_code": exit_code})
    except Exception:
        pass
    try:
        if _v719_span_cm is not None:
            _v719_span_cm.__exit__(None, None, None)
    except Exception:
        pass
    return full_output
'''

if "v7.19: normal-return — close Langfuse span" in text:
    print("[v7.19] normal-return already patched")
elif NORMAL_END_OLD in text:
    text = text.replace(NORMAL_END_OLD, NORMAL_END_NEW, 1)
    print("[v7.19] normal-return path closes Langfuse span")
else:
    print("[v7.19] WARN: NORMAL_END_OLD not found exactly")

aw.write_text(text)
try:
    py_compile.compile(str(aw), doraise=True)
    print("[v7.19] syntax OK")
except Exception as e:
    print(f"[v7.19] SYNTAX ERROR: {e}")
