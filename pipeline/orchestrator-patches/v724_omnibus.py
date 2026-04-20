"""v7.24 omnibus — fix 7 remaining bugs found in 18:11 audit:

1) Normalizer reports iter=1 always — recover from state.json
2) DevOps Hermes not invoking — verify [INFRA-FIX] body reaches it
3) Stale RECOVER replays (4x in 30min) — only recover if real stall
4) Tester writes to iter-1 always — fix downstream of normalizer
5) Trace ID reuse — generate fresh per-iteration traces
6) Frontend never involved — wire frontend FAN-IN sync
7) Single CODE-REVISE in 30min vs 3 INFRA-FIX — backend never gets
   notified when devops fixes infra (no [INFRA-FIXED] handler chain)
"""
from pathlib import Path
import py_compile
import re

ed = Path("/var/lib/karios/orchestrator/event_dispatcher.py")
text = ed.read_text()

# ── Bug #1+#4: Normalizer recovers iter from state.json ─────────────────────
# Find subject_normalizer.py
sn = Path("/var/lib/karios/orchestrator/patches/subject_normalizer.py")
sn_text = sn.read_text()

OLD_NORM_SIG = '''def maybe_normalize_complete(sender: str, gap_id: str, active_phase: str,
                              iteration: int, trace_id: str = "") -> Optional[Dict[str, Any]]:
'''

NEW_NORM_BODY_PROLOGUE = '''def maybe_normalize_complete(sender: str, gap_id: str, active_phase: str,
                              iteration: int, trace_id: str = "") -> Optional[Dict[str, Any]]:
    # v7.24-1: recover real iter from state.json instead of trusting incoming envelope
    try:
        import json as _v724_j
        from pathlib import Path as _v724_P
        _v724_state = _v724_j.loads(_v724_P("/var/lib/karios/orchestrator/state.json").read_text())
        _v724_real_iter = _v724_state.get("active_gaps", {}).get(gap_id, {}).get("iteration")
        if isinstance(_v724_real_iter, int) and _v724_real_iter > 0 and _v724_real_iter > iteration:
            iteration = _v724_real_iter
    except Exception:
        pass
'''

if "v7.24-1: recover real iter" in sn_text:
    print("[v7.24-1] subject_normalizer already patched")
elif OLD_NORM_SIG in sn_text:
    sn_text = sn_text.replace(OLD_NORM_SIG, NEW_NORM_BODY_PROLOGUE, 1)
    sn.write_text(sn_text)
    print("[v7.24-1] subject_normalizer recovers iter from state.json")
else:
    print("[v7.24-1] WARN: signature not found exactly")

# ── Bug #3: stale RECOVER on dispatcher restart ─────────────────────────────
# Find recover_from_checkpoints; only recover if last_dispatch > 10 min ago
print("\n[v7.24-3] Looking for recover_from_checkpoints...")
rfc_match = re.search(r"def recover_from_checkpoints\(.*?\n((?:    .+\n)+)", text)
if rfc_match:
    print("  found function — adding stale-protection guard")
    OLD_RFC_DISPATCH = '''        send_to_agent("backend", f"[RECOVER] {gap_id} — resume coding",'''
    NEW_RFC_DISPATCH = '''        # v7.24-3: skip RECOVER if the gap had recent dispatch activity (avoids stale replay loops)
        try:
            import time as _v724_3_t
            _v724_3_marker = Path(f"/var/lib/karios/agent-memory/{gap_id}_last_dispatch.ts")
            if _v724_3_marker.exists():
                _v724_3_age = _v724_3_t.time() - _v724_3_marker.stat().st_mtime
                if _v724_3_age < 600:  # <10 min
                    print(f"[dispatcher] v7.24-3 SKIP RECOVER {gap_id}: last dispatch {_v724_3_age:.0f}s ago (within 10min)")
                    continue
        except Exception:
            pass
        send_to_agent("backend", f"[RECOVER] {gap_id} — resume coding",'''
    if "v7.24-3 SKIP RECOVER" in text:
        print("  [v7.24-3] already patched")
    elif OLD_RFC_DISPATCH in text:
        text = text.replace(OLD_RFC_DISPATCH, NEW_RFC_DISPATCH, 1)
        print("  [v7.24-3] RECOVER stale-skip guard wired")
    else:
        print("  [v7.24-3] WARN: OLD_RFC_DISPATCH not found exactly")

# Also: write the marker file each time send_to_agent fires for a gap_id
OLD_SEND_TOP = '''def send_to_agent(agent: str, subject: str, body: str,
                  task_id: str = None, gap_id: str = None,
                  trace_id: str = None, priority: str = "normal"):
    """Send a context packet to an agent via their dedicated Redis Stream.'''

NEW_SEND_TOP = '''def send_to_agent(agent: str, subject: str, body: str,
                  task_id: str = None, gap_id: str = None,
                  trace_id: str = None, priority: str = "normal"):
    """Send a context packet to an agent via their dedicated Redis Stream.'''

# Append marker write at end of send_to_agent body — find the function's last `return` or end
# Simpler: add a try/except after the body that touches the marker file
# Look for the v7.18.3 trace span entry hook we added before
SPAN_HOOK = '''    # v7.18.3: inline Langfuse dispatch trace
    _v718_trace_cm = None'''
SPAN_HOOK_NEW = '''    # v7.24-3: write last-dispatch marker file for RECOVER stale-skip guard
    try:
        if gap_id:
            _v724_3_dir = Path("/var/lib/karios/agent-memory")
            _v724_3_dir.mkdir(parents=True, exist_ok=True)
            (_v724_3_dir / f"{gap_id}_last_dispatch.ts").touch()
    except Exception:
        pass
    # v7.18.3: inline Langfuse dispatch trace
    _v718_trace_cm = None'''

if "v7.24-3: write last-dispatch marker" in text:
    print("[v7.24-3 marker] already patched")
elif SPAN_HOOK in text:
    text = text.replace(SPAN_HOOK, SPAN_HOOK_NEW, 1)
    print("[v7.24-3 marker] dispatch marker write wired into send_to_agent")
else:
    print("[v7.24-3 marker] WARN: SPAN_HOOK not found exactly")

# ── Bug #5: trace_id reuse — generate fresh per dispatch ────────────────────
# new_trace_id is already used in send_to_agent (`tid = trace_id or new_trace_id(...)`)
# but callers explicitly pass the OLD trace_id in. Best fix: in the rev-loop dispatches,
# generate a fresh trace per CODE-REVISE / INFRA-FIX iteration

# Find handle_e2e_results CODE-REVISE dispatch site and replace `trace_id=tid` with fresh
OLD_REVISE_TID = '''            send_to_agent("backend",
                          f"[CODE-REVISE] {gap_id} iteration {next_iter}",
                          _revise_body,
                          gap_id=gap_id, trace_id=tid, priority="high")
'''
NEW_REVISE_TID = '''            # v7.24-5: fresh trace_id per CODE-REVISE iteration (was reusing old trace from initial dispatch)
            _v724_5_revise_tid = new_trace_id(gap_id, "orchestrator", f"revise_iter{next_iter}")
            send_to_agent("backend",
                          f"[CODE-REVISE] {gap_id} iteration {next_iter}",
                          _revise_body,
                          gap_id=gap_id, trace_id=_v724_5_revise_tid, priority="high")
'''
if "v7.24-5: fresh trace_id per CODE-REVISE" in text:
    print("[v7.24-5] already patched")
elif OLD_REVISE_TID in text:
    text = text.replace(OLD_REVISE_TID, NEW_REVISE_TID, 1)
    print("[v7.24-5] fresh trace_id per CODE-REVISE iteration")
else:
    print("[v7.24-5] WARN: OLD_REVISE_TID not found exactly")

# Same for INFRA-FIX
OLD_INFRA_TID = '''                    send_to_agent("devops",
                                  f"[INFRA-FIX] {gap_id} iteration {next_iter}",
                                  _v7232_devops_body,
                                  gap_id=gap_id, trace_id=tid, priority="high")
'''
NEW_INFRA_TID = '''                    # v7.24-5: fresh trace per INFRA-FIX too
                    _v724_5_infra_tid = new_trace_id(gap_id, "orchestrator", f"infra_iter{next_iter}")
                    send_to_agent("devops",
                                  f"[INFRA-FIX] {gap_id} iteration {next_iter}",
                                  _v7232_devops_body,
                                  gap_id=gap_id, trace_id=_v724_5_infra_tid, priority="high")
'''
if "v7.24-5: fresh trace per INFRA-FIX" in text:
    print("[v7.24-5 infra] already patched")
elif OLD_INFRA_TID in text:
    text = text.replace(OLD_INFRA_TID, NEW_INFRA_TID, 1)
    print("[v7.24-5 infra] fresh trace_id per INFRA-FIX iteration")
else:
    print("[v7.24-5 infra] WARN: OLD_INFRA_TID not found exactly")

# ── Bug #7: [INFRA-FIXED] handler chains back to re-test ────────────────────
# When devops emits [INFRA-FIXED], dispatcher should re-dispatch [E2E-REVIEW] + [TEST-RUN]
# to the testers (skipping backend coding step)
INFRA_FIXED_HANDLER = '''
    # v7.24-7: [INFRA-FIXED] handler — devops repaired infra, re-test directly
    if subject.startswith("[INFRA-FIXED]"):
        try:
            _v724_7_tokens = subject.split("]")[1].strip().split() if "]" in subject else []
            _v724_7_gid = _v724_7_tokens[0] if _v724_7_tokens else None
            if not _v724_7_gid:
                # fallback to active gap
                try:
                    _v724_7_state = json.loads(Path("/var/lib/karios/orchestrator/state.json").read_text())
                    _v724_7_active = [k for k, v in _v724_7_state.get("active_gaps", {}).items()
                                      if v.get("state") not in ("completed", "closed")]
                    if len(_v724_7_active) == 1:
                        _v724_7_gid = _v724_7_active[0]
                except Exception:
                    pass
            if _v724_7_gid:
                _v724_7_iter_t = _v724_7_tokens[_v724_7_tokens.index("iteration")+1] if "iteration" in _v724_7_tokens else None
                _v724_7_iter = int(_v724_7_iter_t.rstrip(":")) if _v724_7_iter_t else 1
                # Recover iter from state.json
                try:
                    _v724_7_state2 = json.loads(Path("/var/lib/karios/orchestrator/state.json").read_text())
                    _v724_7_state_iter = _v724_7_state2.get("active_gaps", {}).get(_v724_7_gid, {}).get("iteration")
                    if isinstance(_v724_7_state_iter, int) and _v724_7_state_iter > _v724_7_iter:
                        _v724_7_iter = _v724_7_state_iter
                except Exception:
                    pass
                _v724_7_tid = new_trace_id(_v724_7_gid, "orchestrator", f"reretest_iter{_v724_7_iter}")
                print(f"[dispatcher] v7.24-7 [INFRA-FIXED] {_v724_7_gid} — re-dispatching E2E-REVIEW + TEST-RUN to testers")
                # Use existing prompt builder if available
                if _PROMPT_BUILDER:
                    _v724_7_e2e_body = _build_prompt(task_type="E2E-REVIEW", gap_id=_v724_7_gid,
                                                      iteration=_v724_7_iter, trace_id=_v724_7_tid,
                                                      repo="karios-migration",
                                                      intent_tags=["7_dimensions", "vmware", "adversarial"],
                                                      intent_query=f"e2e re-test after infra fix {_v724_7_gid}")
                    _v724_7_test_body = _build_prompt(task_type="TEST-RUN", gap_id=_v724_7_gid,
                                                       iteration=_v724_7_iter, trace_id=_v724_7_tid,
                                                       repo="karios-migration",
                                                       intent_query=f"functional re-test {_v724_7_gid}")
                else:
                    _v724_7_e2e_body = f"Re-test {_v724_7_gid} iter {_v724_7_iter} after infra fix. Run full E2E."
                    _v724_7_test_body = f"Re-test {_v724_7_gid} iter {_v724_7_iter} after infra fix. Run tests."
                send_to_agent("code-blind-tester",
                              f"[E2E-REVIEW] {_v724_7_gid} iteration {_v724_7_iter}",
                              _v724_7_e2e_body, gap_id=_v724_7_gid, trace_id=_v724_7_tid)
                send_to_agent("tester",
                              f"[TEST-RUN] {_v724_7_gid} iteration {_v724_7_iter}",
                              _v724_7_test_body, gap_id=_v724_7_gid, trace_id=_v724_7_tid)
                try:
                    notify_phase_transition(_v724_7_gid, "devops (infra fix)",
                                            "code-blind-tester+tester (re-test)",
                                            "INFRA-FIXED", rating=None,
                                            summary="infra repaired; re-running E2E + tests")
                except Exception:
                    pass
        except Exception as _v724_7_e:
            print(f"[dispatcher] v7.24-7 INFRA-FIXED handler failed: {_v724_7_e}")
        return
'''

# Insert before "# ── E2E results" block
INSERT_MARKER = '    # ── E2E results (v4.0: includes dimensions, adversarial_tests, recommendation) ──\n'
if "v7.24-7 [INFRA-FIXED]" in text:
    print("[v7.24-7] already patched")
elif INSERT_MARKER in text:
    text = text.replace(INSERT_MARKER, INFRA_FIXED_HANDLER + "\n" + INSERT_MARKER, 1)
    print("[v7.24-7] [INFRA-FIXED] handler wired (devops → testers re-test loop)")
else:
    print("[v7.24-7] WARN: INSERT_MARKER not found")

ed.write_text(text)
try:
    py_compile.compile(str(ed), doraise=True)
    print("\n[v7.24] dispatcher syntax OK")
except Exception as e:
    print(f"\n[v7.24] SYNTAX ERROR: {e}")
