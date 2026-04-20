"""v7.23.2 — route infra/deployment errors to DEVOPS instead of backend.

Bug: when classify_error returns 'infra' (e.g. service-unavailable,
malformed DATABASE_URL), CODE-REVISE still goes to backend. But backend
codes Go; it can't restart services or fix env files. DevOps owns infra.

Fix: in handle_e2e_results retry_with_self_diagnosis branch, check
classified category — if infra/deployment, dispatch [INFRA-FIX] to devops
instead of [CODE-REVISE] to backend.
"""
from pathlib import Path
import py_compile

ed = Path("/var/lib/karios/orchestrator/event_dispatcher.py")
text = ed.read_text()

# Find the CODE-REVISE dispatch block and add an infra branch BEFORE it
OLD = '''            update_agent_checkpoint("backend", phase="phase-3-coding", iteration=next_iter)
            update_agent_checkpoint("frontend", phase="phase-3-coding", iteration=next_iter)
            # v7.22-C: explicitly persist iteration to state.json (was getting reset by [COMPLETE] handler)'''

NEW = '''            update_agent_checkpoint("backend", phase="phase-3-coding", iteration=next_iter)
            update_agent_checkpoint("frontend", phase="phase-3-coding", iteration=next_iter)
            # v7.23.2: if errors classify as infra/deployment, route to DEVOPS instead of backend
            try:
                _v7232_cat, _ = classify_error(combined_issues)
                if _v7232_cat in ("infra", "deployment"):
                    _v7232_issues_short = "\\n".join(
                        (f"- [{i.get('severity','?')}] {i.get('description', str(i)[:200])}"
                         if isinstance(i, dict) else f"- {i}")
                        for i in critical_issues[:10]
                    )
                    _v7232_devops_body = (
                        f"INFRA/DEPLOYMENT issue — devops action required. Gap {gap_id} iter {next_iter}.\\n\\n"
                        f"PRIOR E2E RATING: {rating}/10 (REJECT). Self-diagnosis: {strategy}\\n\\n"
                        f"INFRA ISSUES TO RESOLVE:\\n{_v7232_issues_short}\\n\\n"
                        f"REQUIRED FIRST 3 TOOL CALLS (no prose):\\n"
                        f"  1. bash: systemctl status karios-migration --no-pager 2>&1 | head -30\\n"
                        f"  2. bash: journalctl -u karios-migration --no-pager -n 50\\n"
                        f"  3. bash: cat /etc/systemd/system/karios-migration.service && cat /etc/karios/secrets.env 2>&1 | grep -i database\\n\\n"
                        f"After identifying the env/service/config issue:\\n"
                        f"  - fix /etc/karios/secrets.env or systemd unit\\n"
                        f"  - systemctl daemon-reload && systemctl restart karios-migration\\n"
                        f"  - verify with: curl -sI http://localhost:8089/api/v1/healthz\\n"
                        f"  - confirm with: agent send orchestrator '[INFRA-FIXED] {gap_id} iteration {next_iter}'\\n"
                        f"DO NOT touch Go code. ONLY fix infra/env/service config."
                    )
                    print(f"[dispatcher] v7.23.2 INFRA-FIX routing for {gap_id} iter {next_iter} (category={_v7232_cat}) — devops, not backend")
                    send_to_agent("devops",
                                  f"[INFRA-FIX] {gap_id} iteration {next_iter}",
                                  _v7232_devops_body,
                                  gap_id=gap_id, trace_id=tid, priority="high")
                    try:
                        notify_phase_transition(gap_id, "code-blind-tester+tester",
                                                "devops (infra fix)",
                                                "INFRA-FIX", rating=rating,
                                                summary=f"infra/deployment errors detected; devops action required")
                    except Exception:
                        pass
                    return  # Skip the backend CODE-REVISE dispatch below
            except Exception as _v7232_e:
                print(f"[dispatcher] v7.23.2 routing check failed: {_v7232_e}")
            # v7.22-C: explicitly persist iteration to state.json (was getting reset by [COMPLETE] handler)'''

if "v7.23.2 INFRA-FIX routing" in text:
    print("[v7.23.2] already patched")
elif OLD in text:
    text = text.replace(OLD, NEW, 1)
    ed.write_text(text)
    print("[v7.23.2] infra/deployment errors now route to devops [INFRA-FIX] not backend [CODE-REVISE]")
else:
    print("[v7.23.2] WARN: OLD block not found exactly")

try:
    py_compile.compile(str(ed), doraise=True)
    print("[v7.23.2] dispatcher syntax OK")
except Exception as e:
    print(f"[v7.23.2] SYNTAX ERROR: {e}")
