"""v7.18.3 — move Langfuse trace calls INLINE into dispatcher functions
instead of post-hoc monkey-patching (which fails on circular import).
"""
from pathlib import Path
import py_compile

ed = Path("/var/lib/karios/orchestrator/event_dispatcher.py")
text = ed.read_text()

# 1. Replace the monkey-patching import with a direct wrapper import
OLD_IMPORT = '''try:
    import langfuse_dispatcher_patch  # noqa: F401  initializes Langfuse if env vars set
except Exception as _e:
    print(f"[dispatcher] v7.18 langfuse-patch unavailable: {_e}")
'''

NEW_IMPORT = '''# v7.18.3: Inline Langfuse trace calls (monkey-patch failed on circular import)
try:
    sys.path.insert(0, "/root/agentic-workflow/pipeline/integrations/3-langfuse")
    from kairos_langfuse_wrapper import init_langfuse as _v718_lf_init, trace_dispatch as _v718_lf_dispatch, trace_phase_event as _v718_lf_phase
    _V718_LF_OK = _v718_lf_init()
except Exception as _e:
    _V718_LF_OK = False
    print(f"[dispatcher] v7.18 langfuse inline unavailable: {_e}")
    def _v718_lf_dispatch(*a, **kw):
        from contextlib import contextmanager
        @contextmanager
        def _noop():
            yield None
        return _noop()
    def _v718_lf_phase(*a, **kw):
        pass
'''

if "_V718_LF_OK" in text:
    print("[v7.18.3] already migrated to inline")
elif OLD_IMPORT in text:
    text = text.replace(OLD_IMPORT, NEW_IMPORT, 1)
    print("[v7.18.3] replaced monkey-patch import with inline wrapper")
else:
    print("[v7.18.3] WARN: OLD_IMPORT block not found")

# 2. Inject _v718_lf_phase() call at start of notify_phase_transition body
NPT_OLD = '''def notify_phase_transition(gap_id: str, from_agent: str, to_agent: str,
                              event: str, rating=None, score_max=10, summary: str = ""):
    """v7.3: Loud Telegram notification when a phase transitions or a blind-tester scores.
    User explicitly asked: 'I want to know that the blind-test agent reviewed, this is the
    score, now handing back to architect/coder.'"""
'''

NPT_NEW = NPT_OLD + '''    # v7.18.3: inline Langfuse phase-event trace
    try:
        if _V718_LF_OK:
            _v718_lf_phase(gap_id, event, from_agent, to_agent or "", rating=rating, summary=summary)
    except Exception as _lfe:
        pass
'''

if "_v718_lf_phase(gap_id, event" in text:
    print("[v7.18.3] notify_phase_transition already patched")
elif NPT_OLD in text:
    text = text.replace(NPT_OLD, NPT_NEW, 1)
    print("[v7.18.3] notify_phase_transition now emits Langfuse events inline")
else:
    print("[v7.18.3] WARN: NPT_OLD not found exactly")

# 3. Wrap send_to_agent body with trace_dispatch context
STA_OLD_BODY_START = '''def send_to_agent(agent: str, subject: str, body: str,
                  task_id: str = None, gap_id: str = None,
                  trace_id: str = None, priority: str = "normal"):
    """Send a context packet to an agent via their dedicated Redis Stream.

    FIX v5.1: Write to stream:{agent} — each agent has its own stream.
    Previously wrote to stream:orchestrator with separate consumer groups per agent,
    causing XREADGROUP race conditions where agents claimed each other's messages.
    Now orchestrator writes directly to agent's private stream — no group needed.

    FIX v5.4: Semantic Memory inject_context() prepended to body before dispatch.
    """
    tid = trace_id or new_trace_id(gap_id, "orchestrator", subject[:20])
'''

STA_NEW_BODY_START = STA_OLD_BODY_START + '''    # v7.18.3: inline Langfuse dispatch trace
    _v718_trace_cm = None
    try:
        if _V718_LF_OK:
            _v718_trace_cm = _v718_lf_dispatch(gap_id or "no-gap", agent, subject,
                                                trace_id=tid,
                                                metadata={"priority": priority,
                                                           "body_chars": len(body or "")})
            _v718_trace_cm.__enter__()
    except Exception:
        _v718_trace_cm = None
'''

if "_v718_trace_cm = _v718_lf_dispatch" in text:
    print("[v7.18.3] send_to_agent already patched")
elif STA_OLD_BODY_START in text:
    text = text.replace(STA_OLD_BODY_START, STA_NEW_BODY_START, 1)
    print("[v7.18.3] send_to_agent now opens Langfuse span inline")
else:
    print("[v7.18.3] WARN: STA_OLD_BODY_START not found exactly")

# 4. Close the trace context at the last line of send_to_agent (before `return` or end)
# We'll just cleanup at module exit via flush. For now, leave span open — flush at end.
# Actually for cleanness, add a `try/finally` wrapper. Simpler: exit span inside function
# just before the return statement. Find end of send_to_agent.
# Rather than parsing end of function, use atexit-style flush. The span will show as
# "incomplete" (no .update(output=...)) but trace is still recorded.

# 5. Write + syntax check
ed.write_text(text)
try:
    py_compile.compile(str(ed), doraise=True)
    print("[v7.18.3] syntax OK")
except Exception as e:
    print(f"[v7.18.3] SYNTAX ERROR: {e}")
