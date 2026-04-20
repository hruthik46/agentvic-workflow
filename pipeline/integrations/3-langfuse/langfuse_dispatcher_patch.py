"""langfuse_dispatcher_patch.py — Wire kairos_langfuse_wrapper into the live dispatcher.

Drop into /var/lib/karios/orchestrator/. Imported at top of event_dispatcher.py;
calls init_langfuse() once at startup and monkey-patches notify_phase_transition +
send_to_agent to emit Langfuse traces. Soft-fails if Langfuse unavailable.

Wire-up (one line at top of event_dispatcher.py):
    import langfuse_dispatcher_patch  # noqa: F401  (initializes Langfuse if env vars set)
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make sibling integrations dir importable
_INTEGRATIONS = Path("/root/agentic-workflow/pipeline/integrations/3-langfuse")
if str(_INTEGRATIONS) not in sys.path:
    sys.path.insert(0, str(_INTEGRATIONS))

try:
    from kairos_langfuse_wrapper import (
        init_langfuse,
        trace_dispatch,
        trace_phase_event,
    )
    _LF_OK = init_langfuse()
except Exception as e:
    print(f"[langfuse-patch] disabled: {e}")
    _LF_OK = False

if _LF_OK:
    # Monkey-patch event_dispatcher functions defensively (only if module already imported)
    import event_dispatcher as _ed

    _orig_notify = _ed.notify_phase_transition

    def _notify_with_trace(gap_id, from_agent, to_agent, event,
                           rating=None, score_max=10, summary=""):
        result = _orig_notify(gap_id, from_agent, to_agent, event,
                              rating=rating, score_max=score_max, summary=summary)
        try:
            trace_phase_event(gap_id, event, from_agent, to_agent or "",
                              rating=rating, summary=summary)
        except Exception as ex:
            print(f"[langfuse-patch] phase-event trace failed: {ex}")
        return result

    _ed.notify_phase_transition = _notify_with_trace

    _orig_send = _ed.send_to_agent

    def _send_with_trace(agent, subject, body, task_id=None, gap_id=None,
                         trace_id=None, priority="normal"):
        try:
            with trace_dispatch(gap_id or "no-gap", agent, subject, trace_id=trace_id,
                                metadata={"priority": priority, "body_chars": len(body or "")}):
                return _orig_send(agent, subject, body, task_id=task_id,
                                  gap_id=gap_id, trace_id=trace_id, priority=priority)
        except Exception as ex:
            print(f"[langfuse-patch] dispatch trace failed: {ex}")
            return _orig_send(agent, subject, body, task_id=task_id,
                              gap_id=gap_id, trace_id=trace_id, priority=priority)

    _ed.send_to_agent = _send_with_trace
    print("[langfuse-patch] active: notify_phase_transition + send_to_agent wrapped")
