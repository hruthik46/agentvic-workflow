"""v7.22 — fix iteration counter bug + write to correct iter dir.

Three fixes:
A) v7.21.1 fallback: when subject has no iter token, read CURRENT iter from
   state.json instead of defaulting to 1. Ensures handle_e2e_results gets
   the actual current iter so next_iter increments correctly.
B) Tester/E2E prompt: write to iteration-{iter} dir using the iter passed
   in the dispatch (already correct via prompt_builder, just verifying)
C) handle_e2e_results: explicitly write state.json's iteration field via
   _update_active_gap_state (existing helper) AFTER computing next_iter,
   so subsequent dispatches see the new value.
"""
from pathlib import Path
import py_compile
import re

ed = Path("/var/lib/karios/orchestrator/event_dispatcher.py")
text = ed.read_text()

# ── A: v7.21.1 fallback uses state.json iter instead of defaulting to 1 ─────
OLD_A = '''            if _v721_1_gid:
                print(f"[dispatcher] v7.21.1 [E2E-RESULTS] no gap in subject — recovered gap_id={_v721_1_gid} (from trace_id or active-gap fallback)")
                gid = _v721_1_gid
                tokens = [gid]
            else:
                print(f"[dispatcher] ERROR: [E2E-RESULTS] message has no gap_id in subject: {subject!r} and trace/state fallback failed")
                return
        else:
            gid = tokens[0]
'''

NEW_A = '''            if _v721_1_gid:
                print(f"[dispatcher] v7.21.1 [E2E-RESULTS] no gap in subject — recovered gap_id={_v721_1_gid} (from trace_id or active-gap fallback)")
                gid = _v721_1_gid
                tokens = [gid]
                # v7.22-A: also recover iteration from state.json instead of defaulting to 1
                try:
                    _v722_state = json.loads(Path("/var/lib/karios/orchestrator/state.json").read_text())
                    _v722_gap = _v722_state.get("active_gaps", {}).get(_v721_1_gid, {})
                    _v722_iter = _v722_gap.get("iteration")
                    if _v722_iter and isinstance(_v722_iter, int) and _v722_iter > 0:
                        # Inject iter token into tokens so existing parser picks it up
                        tokens = [gid, "iteration", str(_v722_iter)]
                        print(f"[dispatcher] v7.22-A recovered iteration={_v722_iter} from state.json for {_v721_1_gid}")
                except Exception as _v722_e:
                    print(f"[dispatcher] v7.22-A iter recovery failed: {_v722_e}")
            else:
                print(f"[dispatcher] ERROR: [E2E-RESULTS] message has no gap_id in subject: {subject!r} and trace/state fallback failed")
                return
        else:
            gid = tokens[0]
'''

if "v7.22-A recovered iteration" in text:
    print("[v7.22-A] already patched")
elif OLD_A in text:
    text = text.replace(OLD_A, NEW_A, 1)
    print("[v7.22-A] iteration recovered from state.json on bare subject")
else:
    print("[v7.22-A] WARN: OLD_A block not found exactly")

# ── C: handle_e2e_results explicitly writes new iteration to state.json ─────
# Find the rev-loop dispatch block where update_gap_phase is called with next_iter
OLD_C = '''            next_iter = iteration + 1
            update_gap_phase(gap_id, "3-coding", iteration=next_iter, trace_id=tid,
                             last_rating=rating, last_issues=critical_issues,
                             self_diagnosis=strategy)
            update_agent_checkpoint("backend", phase="phase-3-coding", iteration=next_iter)
            update_agent_checkpoint("frontend", phase="phase-3-coding", iteration=next_iter)
'''

NEW_C = '''            next_iter = iteration + 1
            update_gap_phase(gap_id, "3-coding", iteration=next_iter, trace_id=tid,
                             last_rating=rating, last_issues=critical_issues,
                             self_diagnosis=strategy)
            update_agent_checkpoint("backend", phase="phase-3-coding", iteration=next_iter)
            update_agent_checkpoint("frontend", phase="phase-3-coding", iteration=next_iter)
            # v7.22-C: explicitly persist iteration to state.json (was getting reset by [COMPLETE] handler)
            try:
                _v722c_state_path = Path("/var/lib/karios/orchestrator/state.json")
                _v722c_state = json.loads(_v722c_state_path.read_text())
                _v722c_state.setdefault("active_gaps", {}).setdefault(gap_id, {})["iteration"] = next_iter
                _v722c_state["active_gaps"][gap_id]["phase"] = "3-coding"
                _v722c_state["active_gaps"][gap_id]["last_rating"] = rating
                _v722c_state_path.write_text(json.dumps(_v722c_state, indent=2))
                print(f"[dispatcher] v7.22-C persisted iter={next_iter} to state.json for {gap_id}")
            except Exception as _v722c_e:
                print(f"[dispatcher] v7.22-C state persist failed: {_v722c_e}")
'''

if "v7.22-C persisted iter" in text:
    print("[v7.22-C] already patched")
elif OLD_C in text:
    text = text.replace(OLD_C, NEW_C, 1)
    print("[v7.22-C] iteration explicitly persisted to state.json")
else:
    print("[v7.22-C] WARN: OLD_C block not found exactly — looking for broader match")
    # Try a more lenient match
    pat = re.compile(r"(            next_iter = iteration \+ 1\n.*?update_agent_checkpoint\(\"frontend\", phase=\"phase-3-coding\", iteration=next_iter\)\n)", re.DOTALL)
    m = pat.search(text)
    if m:
        text = text.replace(m.group(1), m.group(1) + '''            # v7.22-C: explicitly persist iteration to state.json (was getting reset by [COMPLETE] handler)
            try:
                _v722c_state_path = Path("/var/lib/karios/orchestrator/state.json")
                _v722c_state = json.loads(_v722c_state_path.read_text())
                _v722c_state.setdefault("active_gaps", {}).setdefault(gap_id, {})["iteration"] = next_iter
                _v722c_state["active_gaps"][gap_id]["phase"] = "3-coding"
                _v722c_state["active_gaps"][gap_id]["last_rating"] = rating
                _v722c_state_path.write_text(json.dumps(_v722c_state, indent=2))
                print(f"[dispatcher] v7.22-C persisted iter={next_iter} to state.json for {gap_id}")
            except Exception as _v722c_e:
                print(f"[dispatcher] v7.22-C state persist failed: {_v722c_e}")
''', 1)
        print("[v7.22-C] iteration explicitly persisted (lenient match)")
    else:
        print("[v7.22-C] FAIL: cannot find pattern even with lenient match")

ed.write_text(text)

try:
    py_compile.compile(str(ed), doraise=True)
    print("[v7.22] dispatcher syntax OK")
except Exception as e:
    print(f"[v7.22] SYNTAX ERROR: {e}")
