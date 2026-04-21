"""v7.33 — when v7.21-C short-circuits to handle_e2e_results, ALSO re-dispatch
fresh [E2E-REVIEW] + [TEST-RUN] to testers so they re-test against the CURRENT
state (not the stale e2e from 2 hours ago).

Bug: v7.21-C bypassed [API-SYNC] but didn't re-dispatch cbt/tester. So cbt's
last [E2E-REVIEW] was from v7.10 era using a generic 5-line prompt. The
v7.31 + v7.32 detailed prompts never reached cbt because the [API-SYNC] path
that triggers fresh tester dispatches got skipped.

Fix: after handle_e2e_results call, dispatch fresh [E2E-REVIEW] (v7.31) +
[TEST-RUN] (v7.31) so testers re-evaluate the current (post-CODE-REVISE) state.
"""
from pathlib import Path
import py_compile

ed = Path("/var/lib/karios/orchestrator/event_dispatcher.py")
text = ed.read_text()

OLD = '''                                handle_e2e_results(gap_id, iteration, _v721_rating,
                                                    _v721_crit,
                                                    _v721_data.get("test_results", {}),
                                                    _v721_data.get("dimensions", {}),
                                                    _v721_data.get("adversarial_tests", {}),
                                                    _v721_data.get("recommendation", "REQUEST_CHANGES"),
                                                    trace_id=trace_id)
                                _v721_skip_apisync = True'''

NEW = '''                                handle_e2e_results(gap_id, iteration, _v721_rating,
                                                    _v721_crit,
                                                    _v721_data.get("test_results", {}),
                                                    _v721_data.get("dimensions", {}),
                                                    _v721_data.get("adversarial_tests", {}),
                                                    _v721_data.get("recommendation", "REQUEST_CHANGES"),
                                                    trace_id=trace_id)
                                # v7.33: re-dispatch fresh [E2E-REVIEW] + [TEST-RUN] using v7.31 detailed
                                # prompt template so testers produce v7.32-schema results next iteration.
                                # Without this, cbt keeps re-using its OLD generic prompt from a stale
                                # message and never picks up the upgraded template.
                                try:
                                    _v733_iter = iteration + 1
                                    _v733_tid = new_trace_id(gap_id, "orchestrator", f"reretest_iter{_v733_iter}")
                                    if _PROMPT_BUILDER:
                                        _v733_e2e = _build_prompt(task_type="E2E-REVIEW", gap_id=gap_id,
                                                                    iteration=_v733_iter, trace_id=_v733_tid,
                                                                    repo="karios-migration",
                                                                    intent_tags=["7_dimensions", "vmware", "adversarial"],
                                                                    intent_query=f"e2e re-test post code-revise {gap_id}")
                                        _v733_test = _build_prompt(task_type="TEST-RUN", gap_id=gap_id,
                                                                     iteration=_v733_iter, trace_id=_v733_tid,
                                                                     repo="karios-migration",
                                                                     intent_query=f"functional re-test {gap_id}")
                                        send_to_agent("code-blind-tester",
                                                      f"[E2E-REVIEW] {gap_id} iteration {_v733_iter}",
                                                      _v733_e2e, gap_id=gap_id, trace_id=_v733_tid)
                                        send_to_agent("tester",
                                                      f"[TEST-RUN] {gap_id} iteration {_v733_iter}",
                                                      _v733_test, gap_id=gap_id, trace_id=_v733_tid)
                                        print(f"[dispatcher] v7.33: dispatched fresh [E2E-REVIEW]+[TEST-RUN] iter {_v733_iter} for {gap_id} (v7.31 template, v7.32 schema)")
                                except Exception as _v733_e:
                                    print(f"[dispatcher] v7.33 re-dispatch failed: {_v733_e}")
                                _v721_skip_apisync = True'''

if "v7.33: re-dispatch fresh" in text:
    print("[v7.33] already patched")
elif OLD in text:
    text = text.replace(OLD, NEW, 1)
    ed.write_text(text)
    print("[v7.33] handle_e2e_results now also re-dispatches testers with v7.31 template")
else:
    print("[v7.33] WARN: OLD pattern not found")

try:
    py_compile.compile(str(ed), doraise=True)
    print("[v7.33] dispatcher syntax OK")
except Exception as e:
    print(f"[v7.33] SYNTAX ERROR: {e}")
