"""Wire subject_normalizer.maybe_normalize_complete into event_dispatcher.py
[COMPLETE] handler — replaces the 'no transition' else branch with a
normalize-or-noop call.
"""
from pathlib import Path
import py_compile

ed = Path("/var/lib/karios/orchestrator/event_dispatcher.py")
text = ed.read_text()

PATCH_IMPORT = '''
try:
    from subject_normalizer import maybe_normalize_complete as _v718_normalize
except Exception as _e:
    _v718_normalize = None
    print(f"[dispatcher] v7.18 subject-normalizer unavailable: {_e}")
'''

OLD_NO_TRANSITION = (
    '            else:\n'
    '                print(f"[dispatcher] COMPLETE handler: no transition for {gap_id} {phase} '
    '(current={current_phase}; normalized {n_phase}/{n_current})")\n'
)

NEW_NO_TRANSITION = '''            else:
                # v7.18: Subject normalizer — if a tester emits [COMPLETE] without proper subject,
                # rewrite as [E2E-RESULTS] / [TEST-RESULTS] using on-disk JSON or honest REJECT
                _normalized = None
                if _v718_normalize is not None:
                    try:
                        _normalized = _v718_normalize(
                            sender=sender,
                            gap_id=gap_id,
                            active_phase=current_phase or n_current or "",
                            iteration=iteration if iteration else 1,
                            trace_id=trace_id or "",
                        )
                    except Exception as _ne:
                        print(f"[dispatcher] v7.18 normalizer failed: {_ne}")
                if _normalized:
                    print(f"[dispatcher] v7.18 [COMPLETE] from {sender} → rewriting as {_normalized['subject']} ({_normalized['source']})")
                    try:
                        # Inject the rewritten message back into orchestrator inbox
                        from pathlib import Path as _P
                        import json as _j, time as _t, uuid as _u
                        _inj = _P("/var/lib/karios/agent-msg/inbox/orchestrator")
                        _inj.mkdir(parents=True, exist_ok=True)
                        (_inj / f"v718-norm-{gap_id}-{int(_t.time())}-{_u.uuid4().hex[:6]}.json").write_text(_j.dumps({
                            "from": sender,
                            "to": "orchestrator",
                            "id": f"v718-norm-{_u.uuid4().hex[:8]}",
                            "subject": _normalized["subject"],
                            "body": _normalized["body"],
                            "gap_id": gap_id,
                            "trace_id": trace_id or "",
                            "priority": "high",
                        }))
                    except Exception as _ie:
                        print(f"[dispatcher] v7.18 normalizer inject failed: {_ie}")
                else:
                    print(f"[dispatcher] COMPLETE handler: no transition for {gap_id} {phase} (current={current_phase}; normalized {n_phase}/{n_current})")
'''

if "_v718_normalize is not None" in text:
    print("[v7.18-norm] already wired")
else:
    # Insert import after the v7.18 langfuse_dispatcher_patch try/except
    marker = '    print(f"[dispatcher] v7.18 langfuse-patch unavailable: {_e}")\n'
    if marker in text:
        text = text.replace(marker, marker + PATCH_IMPORT, 1)
    else:
        print("[v7.18-norm] WARN: langfuse-patch marker not found; adding import at top of imports")

    # Replace the 'no transition' else branch
    if OLD_NO_TRANSITION in text:
        text = text.replace(OLD_NO_TRANSITION, NEW_NO_TRANSITION, 1)
        ed.write_text(text)
        print("[v7.18-norm] wired into [COMPLETE] handler")
    else:
        print("[v7.18-norm] ERROR: old no-transition branch not found exactly — no change made")

try:
    py_compile.compile(str(ed), doraise=True)
    print("[v7.18-norm] syntax OK")
except Exception as e:
    print(f"[v7.18-norm] SYNTAX ERROR: {e}")
