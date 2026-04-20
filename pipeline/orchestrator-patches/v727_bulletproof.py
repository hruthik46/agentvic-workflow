"""v7.27 — bulletproof the pipeline against agent failure modes.

4 enhancements (no agent code-writing — pure pipeline guardrails):

A) Better tool_use detection in agent-worker:
   - Match MiniMax format: <minimax:tool_call>, <invoke name=, <parameter name=
   - Match OpenAI format: tool_calls, function_call
   - Match Anthropic format: tool_use, "type": "tool_use"
   Was: grep "tool_use" only → undercounted MiniMax tool calls

B) Tool-use FREQUENCY watchdog (additive to existing 3000-char no-tool watchdog):
   If >10000 chars between tool calls, kill — agent producing prose
   between tool calls is the same problem at smaller scale

C) Architect-revisit dispatch after 4 failed CODE-REVISE iterations:
   When backend has been told to fix same issues 4+ times without succeeding,
   the design (architecture) might be wrong. Send [ARCH-REVISE] to architect
   with critical_issues + iteration history.

D) Hard K_max escalation with explicit Telegram + state freeze:
   When iteration > 8, mark gap state=escalated, send Telegram
   "🚨 ESCALATE — gap stuck after 8 iterations, manual intervention needed"
   Stop dispatching to backend/devops/testers for this gap.
"""
from pathlib import Path
import py_compile
import re

# ── A + B: agent-worker tool_use detection improvements ─────────────────────
aw = Path("/usr/local/bin/agent-worker")
text = aw.read_text()

OLD_DETECT = '''            # Detect tool_use event in output
            if '"tool_use"' in decoded or 'tool_use' in decoded:
                tool_use_events[0] += 1
                tool_use_detected.set()
'''

NEW_DETECT = '''            # v7.27-A: Detect tool_use across MiniMax + OpenAI + Anthropic formats
            # MiniMax: <minimax:tool_call>, <invoke name=, <parameter name=
            # OpenAI: "tool_calls", "function_call"
            # Anthropic: "tool_use", "type": "tool_use"
            _v727a_tool_markers = (
                "<minimax:tool_call>",
                "<invoke name=",
                "<parameter name=",
                '"tool_calls"',
                '"function_call"',
                '"tool_use"',
                "'tool_use'",
                "tool_use",
            )
            for _v727a_m in _v727a_tool_markers:
                if _v727a_m in decoded:
                    tool_use_events[0] += 1
                    tool_use_detected.set()
                    # v7.27-B: track chars-since-last-tool-call for frequency watchdog
                    try:
                        token_count[1] = 0  # reset counter at index 1
                    except IndexError:
                        token_count.append(0)
                    break
'''

if "v7.27-A: Detect tool_use across MiniMax" in text:
    print("[v7.27-A] already patched")
elif OLD_DETECT in text:
    text = text.replace(OLD_DETECT, NEW_DETECT, 1)
    print("[v7.27-A] tool_use detection now matches MiniMax + OpenAI + Anthropic formats")
else:
    print("[v7.27-A] WARN: OLD_DETECT pattern not found")

# v7.27-B: track chars between tool calls; init counter
OLD_CHAR_TRACK = '''            # Rough token estimate: words × 1.3
            token_count[0] += len(decoded.split()) * 1.3
'''
NEW_CHAR_TRACK = '''            # Rough token estimate: words × 1.3
            token_count[0] += len(decoded.split()) * 1.3
            # v7.27-B: track chars since last tool call (separate counter)
            try:
                token_count[1] += len(decoded)
            except (IndexError, TypeError):
                token_count.append(len(decoded))
            # If >10K chars accumulated since last tool call AND we've had at least 1 tool call,
            # the agent is producing too much prose between actions → kill
            if (token_count[1] > 10000 and tool_use_detected.is_set()
                    and tool_use_events[0] > 0 and not kill_event.is_set()):
                _v727b_hpid = hermes_pid_holder[0] if hermes_pid_holder else None
                if _v727b_hpid:
                    try:
                        os.killpg(os.getpgid(_v727b_hpid), signal.SIGTERM)
                        print(f"[{AGENT}] WATCHDOG-FREQ: SIGTERM Hermes pid={_v727b_hpid} — {token_count[1]:.0f} chars since last tool call (after {tool_use_events[0]} tool calls)")
                    except (ProcessLookupError, PermissionError):
                        pass
                kill_event.set()
                break
'''

if "v7.27-B: track chars since last tool call" in text:
    print("[v7.27-B] already patched")
elif OLD_CHAR_TRACK in text:
    text = text.replace(OLD_CHAR_TRACK, NEW_CHAR_TRACK, 1)
    print("[v7.27-B] frequency watchdog (10K chars between tool calls) wired")
else:
    print("[v7.27-B] WARN: OLD_CHAR_TRACK pattern not found")

aw.write_text(text)
try:
    py_compile.compile(str(aw), doraise=True)
    print("[v7.27-A+B] agent-worker syntax OK")
except Exception as e:
    print(f"[v7.27-A+B] SYNTAX ERROR: {e}")

# ── C + D: dispatcher architect-revisit + hard K_max escalation ─────────────
ed = Path("/var/lib/karios/orchestrator/event_dispatcher.py")
ed_text = ed.read_text()

# Find handle_e2e_results — add a check BEFORE the routing logic:
# if iteration > 4 AND most recent issues match prior 3 iterations' issues,
# dispatch [ARCH-REVISE] instead of [CODE-REVISE]
# Also: if iteration > 8, escalate hard.

# Insert the check right after `combined_issues = ...` line in retry path
OLD_COMBINED = '''    elif routing["next_action"] == "retry_with_self_diagnosis":
        combined_issues = " ".join(str(i) if not isinstance(i, str) else i for i in critical_issues)  # v7.15: coerce dict items
        can_resolve, strategy, needs_escalate = self_diagnose(
            gap_id, "3-coding", iteration, rating, combined_issues)
'''

NEW_COMBINED = '''    elif routing["next_action"] == "retry_with_self_diagnosis":
        combined_issues = " ".join(str(i) if not isinstance(i, str) else i for i in critical_issues)  # v7.15: coerce dict items

        # v7.27-D: HARD K_MAX ESCALATION at iteration > 8
        if iteration >= 8:
            try:
                _v727d_state_path = Path("/var/lib/karios/orchestrator/state.json")
                _v727d_state = json.loads(_v727d_state_path.read_text())
                _v727d_state.setdefault("active_gaps", {}).setdefault(gap_id, {})["state"] = "escalated"
                _v727d_state["active_gaps"][gap_id]["iteration"] = iteration
                _v727d_state["active_gaps"][gap_id]["phase"] = "escalated"
                _v727d_state_path.write_text(json.dumps(_v727d_state, indent=2))
                print(f"[dispatcher] v7.27-D HARD ESCALATE {gap_id} iter={iteration}/8 — state frozen")
            except Exception as _v727d_e:
                print(f"[dispatcher] v7.27-D state freeze failed: {_v727d_e}")
            try:
                telegram_alert(f"🚨 *{gap_id}*: HARD ESCALATE — stuck after {iteration} iterations. Critical issues persist:\\n" +
                              ("\\n".join(f"- {str(i)[:120]}" for i in critical_issues[:5])))
            except Exception:
                pass
            return

        # v7.27-C: ARCHITECT-REVISIT after 4 failed CODE-REVISE iterations
        # If the same critical_issues categories recur 3+ times, the design is wrong
        if iteration >= 4:
            try:
                _v727c_recent_dir = Path(f"/var/lib/karios/iteration-tracker/{gap_id}")
                _v727c_e2e_files = sorted(_v727c_recent_dir.rglob("e2e-results.json"),
                                           key=lambda p: p.stat().st_mtime, reverse=True)[:4]
                _v727c_categories = set()
                for _v727c_f in _v727c_e2e_files:
                    try:
                        _v727c_d = json.loads(_v727c_f.read_text())
                        for _v727c_c in (_v727c_d.get("critical_issues") or []):
                            if isinstance(_v727c_c, dict) and _v727c_c.get("category"):
                                _v727c_categories.add(_v727c_c["category"])
                    except Exception:
                        continue
                # If the SAME critical category persists across 3+ recent results,
                # the design needs rethinking (not just a code patch)
                if len(_v727c_e2e_files) >= 3 and len(_v727c_categories) <= 2:
                    print(f"[dispatcher] v7.27-C ARCH-REVISIT: same {len(_v727c_categories)} category(ies) across {len(_v727c_e2e_files)} iterations — sending to architect")
                    _v727c_tid = new_trace_id(gap_id, "orchestrator", f"arch_revisit_iter{iteration}")
                    _v727c_arch_body = (
                        f"ARCHITECT-REVISIT — design may be wrong. Gap {gap_id} stuck at iteration {iteration}/8.\\n\\n"
                        f"Backend has tried to fix the same issue categories {len(_v727c_e2e_files)} times: "
                        f"{', '.join(sorted(_v727c_categories))}\\n\\n"
                        f"Latest critical issues:\\n" +
                        "\\n".join(
                            (f"- [{i.get('severity','?')}] {i.get('category','?')}: {i.get('description', str(i)[:200])}"
                             if isinstance(i, dict) else f"- {i}")
                            for i in critical_issues[:10]
                        ) +
                        f"\\n\\nRequired:\\n"
                        f"  1. Read current architecture.md + critical_issues above\\n"
                        f"  2. Identify if the bug is in the DESIGN (wrong API contract, wrong storage model, etc.)\\n"
                        f"  3. Write updated architecture.md to phase-2-architecture/iteration-{iteration+1}/\\n"
                        f"  4. Send [ARCH-COMPLETE] {gap_id} iteration {iteration+1}\\n"
                        f"DO NOT write code. ONLY revise the design."
                    )
                    send_to_agent("architect",
                                  f"[ARCH-REVISE] {gap_id} iteration {iteration+1}",
                                  _v727c_arch_body,
                                  gap_id=gap_id, trace_id=_v727c_tid, priority="high")
                    try:
                        notify_phase_transition(gap_id, "code-blind-tester+tester (4+ iter rev-loop)",
                                                "architect (ARCH-REVISE)",
                                                "ARCH-REVISIT", rating=rating,
                                                summary=f"design revisit triggered after {iteration} failed code revisions")
                    except Exception:
                        pass
                    return  # Skip backend CODE-REVISE — architect needs to act first
            except Exception as _v727c_e:
                print(f"[dispatcher] v7.27-C arch-revisit check failed: {_v727c_e}")

        can_resolve, strategy, needs_escalate = self_diagnose(
            gap_id, "3-coding", iteration, rating, combined_issues)
'''

if "v7.27-C ARCH-REVISIT" in ed_text:
    print("[v7.27-C+D] already patched")
elif OLD_COMBINED in ed_text:
    ed_text = ed_text.replace(OLD_COMBINED, NEW_COMBINED, 1)
    print("[v7.27-C] architect-revisit after 4 stuck iterations wired")
    print("[v7.27-D] hard K_max=8 escalation wired")
else:
    print("[v7.27-C+D] WARN: OLD_COMBINED block not found")

ed.write_text(ed_text)
try:
    py_compile.compile(str(ed), doraise=True)
    print("[v7.27-C+D] dispatcher syntax OK")
except Exception as e:
    print(f"[v7.27-C+D] SYNTAX ERROR: {e}")
