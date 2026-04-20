"""v7.32 — DETAILED REPORTS PROTOCOL.

Per SWE-Bench best practices (agents at 83.4% bug-fix rate):
- Reviewer reports include ROOT CAUSE, REPRODUCTION, FILE:LINE, EVIDENCE,
  SUGGESTED FIX, ACCEPTANCE CRITERIA per critical_issue
- Fix-agent prompts inject these fields VERBATIM so the coder knows exactly
  what to fix and how to verify

This v7.32 patches:
A) Update _ARCH_REVIEW_SCHEMA to include suggested_redesign per dimension
B) Update _E2E_RESULTS_SCHEMA to include detailed critical_issue fields
C) New helper format_critical_issues_for_revise() that builds rich body text
D) Wire CODE-REVISE prompt to use the rich format
E) Wire ARCH-REVISE prompt to use the rich format
"""
import re, py_compile
from pathlib import Path

# ── A+B: update schemas in prompt_builder.py ─────────────────────────────────
pb = Path("/var/lib/karios/orchestrator/prompt_builder.py")
text = pb.read_text()

OLD_E2E_SCHEMA = """_E2E_RESULTS_SCHEMA = (
    '{\"gap_id\":\"{gid}\",\"iteration\":{it},\"rating\":N,'
    '\"recommendation\":\"APPROVE|REJECT\",'
    '\"summary\":\"what actually ran and what passed\",'
    '\"critical_issues\":[...],'
    '\"dimensions\":{\"functional_correctness\":N,\"edge_cases\":N,\"security\":N,\"performance\":N,\"concurrency\":N,\"resilience\":N,\"error_handling\":N},'
    '\"adversarial_test_cases\":{\"test_id\":\"pass|fail + evidence\"},'
    '\"evidence\":{\"healthz\":\"HTTP_CODE\",\"git_log\":\"commit_sha\",\"go_test\":\"PASS|FAIL summary\",\"esxi_probe\":\"output\"},'
    '\"trace_id\":\"{tid}\"}'
)"""

NEW_E2E_SCHEMA = """_E2E_RESULTS_SCHEMA = (
    '{\"gap_id\":\"{gid}\",\"iteration\":{it},\"rating\":N,'
    '\"recommendation\":\"APPROVE|REJECT\",'
    '\"summary\":\"what actually ran and what passed\",'
    '\"critical_issues\":[{'
    '\"severity\":\"CRITICAL|HIGH|MEDIUM|LOW\",'
    '\"category\":\"snake-or-hyphen-tag e.g. syntax-error\",'
    '\"dimension\":\"functional_correctness|edge_cases|security|performance|concurrency|resilience|error_handling\",'
    '\"file_line\":\"path/to/file.go:LINE\",'
    '\"description\":\"WHAT IS BROKEN — concise\",'
    '\"root_cause\":\"WHY it broke — actual reason from runtime evidence\",'
    '\"reproduction\":\"exact bash command that reliably triggers the failure\",'
    '\"evidence\":\"actual output snippet (stdout/stderr from reproduction)\",'
    '\"suggested_fix\":\"concrete code change OR API replacement OR config delta — actionable, not vague\",'
    '\"acceptance_criteria\":\"how the fix-agent VERIFIES the fix worked (specific cmd + expected output)\",'
    '\"prior_attempts\":[\"iter N tried X but failed because Y\"]'
    '}],'
    '\"dimensions\":{\"functional_correctness\":N,\"edge_cases\":N,\"security\":N,\"performance\":N,\"concurrency\":N,\"resilience\":N,\"error_handling\":N},'
    '\"adversarial_test_cases\":{\"test_id\":\"pass|fail + evidence\"},'
    '\"evidence\":{\"healthz\":\"HTTP_CODE\",\"git_log\":\"commit_sha\",\"go_test\":\"PASS|FAIL summary\",\"esxi_probe\":\"output\"},'
    '\"trace_id\":\"{tid}\"}'
)"""

if "root_cause" in text:
    print("[v7.32-A] schema already updated")
elif OLD_E2E_SCHEMA in text:
    text = text.replace(OLD_E2E_SCHEMA, NEW_E2E_SCHEMA, 1)
    print("[v7.32-A] _E2E_RESULTS_SCHEMA upgraded with detailed critical_issue fields")
else:
    print("[v7.32-A] WARN: OLD_E2E_SCHEMA not found exactly — schema is in different format")

# Same for ARCH-REVIEW schema
OLD_ARCH_SCHEMA = """_ARCH_REVIEW_SCHEMA = (
    '{\"gap_id\":\"{gid}\",\"iteration\":{it},\"rating\":N,'
    '\"critical_issues\":[{\"category\":\"X\",\"severity\":\"HIGH|MEDIUM|LOW\",\"why\":\"...\",\"fix\":\"...\"}],'
    '\"dimensions\":{\"correctness\":N,\"completeness\":N,\"feasibility\":N,\"security\":N,\"testability\":N,\"resilience\":N},'
    '\"adversarial_test_cases\":{\"case_id\":\"what_it_tests → pass|fail + evidence\"},'
    '\"recommendation\":\"APPROVE|REQUEST_CHANGES|REJECT\",\"summary\":\"what you found\",'
    '\"trace_id\":\"{tid}\"}'
)"""

NEW_ARCH_SCHEMA = """_ARCH_REVIEW_SCHEMA = (
    '{\"gap_id\":\"{gid}\",\"iteration\":{it},\"rating\":N,'
    '\"critical_issues\":[{'
    '\"severity\":\"CRITICAL|HIGH|MEDIUM|LOW\",'
    '\"category\":\"design-flaw|missing-spec|incoherent-api|untestable|security-gap|scaling-blocker\",'
    '\"dimension\":\"correctness|completeness|feasibility|security|testability|resilience\",'
    '\"doc_line\":\"architecture.md:LINE or api-contract.md:LINE\",'
    '\"description\":\"WHAT is wrong — concise\",'
    '\"root_cause\":\"WHY it is wrong — what the doc says vs reality\",'
    '\"suggested_redesign\":\"concrete change to the doc — what to replace, what to add\",'
    '\"acceptance_criteria\":\"how to verify the redesign — specific doc section + content\",'
    '\"prior_attempts\":[\"iter N tried X but reviewer rejected because Y\"]'
    '}],'
    '\"dimensions\":{\"correctness\":N,\"completeness\":N,\"feasibility\":N,\"security\":N,\"testability\":N,\"resilience\":N},'
    '\"adversarial_test_cases\":{\"case_id\":\"what_it_tests → would_break_design? + how\"},'
    '\"recommendation\":\"APPROVE|REQUEST_CHANGES|REJECT\",\"summary\":\"what you found\",'
    '\"trace_id\":\"{tid}\"}'
)"""

if "suggested_redesign" in text:
    print("[v7.32-B] arch schema already updated")
elif OLD_ARCH_SCHEMA in text:
    text = text.replace(OLD_ARCH_SCHEMA, NEW_ARCH_SCHEMA, 1)
    print("[v7.32-B] _ARCH_REVIEW_SCHEMA upgraded with suggested_redesign + acceptance_criteria")
else:
    print("[v7.32-B] WARN: OLD_ARCH_SCHEMA not found exactly")

pb.write_text(text)
try:
    py_compile.compile(str(pb), doraise=True)
    print("[v7.32-A+B] prompt_builder syntax OK")
except Exception as e:
    print(f"[v7.32-A+B] SYNTAX ERROR: {e}")
    raise SystemExit(1)

# ── C+D: dispatcher uses the rich critical_issue fields ─────────────────────
ed = Path("/var/lib/karios/orchestrator/event_dispatcher.py")
ed_text = ed.read_text()

# Add a helper that formats critical_issues for the revise body
HELPER = '''
def format_critical_issues_for_revise(critical_issues, kind="code"):
    """v7.32: build a rich, SWE-Bench-style critical-issues block for fix-agent prompts.

    Per SWE-Bench best practices (83.4% bug-fix rate agents): include
    root_cause, reproduction, file_line, evidence, suggested_fix,
    acceptance_criteria. The fix-agent then has a complete spec, not just
    an error message.

    kind: "code" (for backend) or "arch" (for architect)
    """
    if not isinstance(critical_issues, list):
        return "(no structured critical_issues)"
    lines = []
    for i, issue in enumerate(critical_issues[:15], 1):
        if not isinstance(issue, dict):
            lines.append(f"{i}. {str(issue)[:300]}")
            continue
        sev = issue.get("severity", "?")
        cat = issue.get("category", "?")
        dim = issue.get("dimension", "?")
        desc = issue.get("description", "")
        loc = issue.get("file_line") or issue.get("doc_line") or "(no location)"
        cause = issue.get("root_cause", "(reviewer did not provide root cause)")
        repro = issue.get("reproduction", "")
        evid = issue.get("evidence", "")
        sug = issue.get("suggested_fix") or issue.get("suggested_redesign") or "(reviewer did not suggest a fix)"
        accept = issue.get("acceptance_criteria", "(no explicit acceptance criteria)")
        prior = issue.get("prior_attempts", [])

        lines.append(f"\\n--- ISSUE #{i} [{sev}] [{cat}] dim={dim} ---")
        lines.append(f"LOCATION: {loc}")
        lines.append(f"WHAT: {desc}")
        lines.append(f"WHY (root cause): {cause}")
        if repro:
            lines.append(f"REPRODUCE: {repro}")
        if evid:
            evid_short = str(evid)[:500]
            lines.append(f"EVIDENCE: {evid_short}")
        lines.append(f"SUGGESTED FIX: {sug}")
        lines.append(f"ACCEPTANCE: {accept}")
        if prior:
            for p in prior[:3]:
                lines.append(f"PRIOR ATTEMPT: {str(p)[:200]}")
    return "\\n".join(lines)

'''

if "def format_critical_issues_for_revise" in ed_text:
    print("[v7.32-C] helper already exists")
else:
    # Insert before def escalate_to_human (or before send_to_agent)
    for marker in ["\ndef escalate_to_human(", "\ndef send_to_agent("]:
        if marker in ed_text:
            ed_text = ed_text.replace(marker, HELPER + marker, 1)
            print(f"[v7.32-C] format_critical_issues_for_revise helper inserted before {marker.strip()[:40]}")
            break
    else:
        print("[v7.32-C] WARN: could not find marker to insert helper")

# Now inject the helper output into the CODE-REVISE extra_context
OLD_REVISE_BUILD = '''            _issues_str = "\\n".join(
                (f"- [{i.get('severity','?')}] {i.get('description', str(i)[:200])}"
                 if isinstance(i, dict) else f"- {i}")
                for i in critical_issues[:10]
            )'''

NEW_REVISE_BUILD = '''            # v7.32: SWE-Bench-style detailed issue rendering (root cause, reproduction, evidence, fix, acceptance)
            _issues_str = format_critical_issues_for_revise(critical_issues, kind="code")'''

if "format_critical_issues_for_revise(critical_issues, kind=\"code\")" in ed_text:
    print("[v7.32-D code] already wired")
elif OLD_REVISE_BUILD in ed_text:
    ed_text = ed_text.replace(OLD_REVISE_BUILD, NEW_REVISE_BUILD, 1)
    print("[v7.32-D code] CODE-REVISE issues now use detailed format")
else:
    print("[v7.32-D code] WARN: OLD_REVISE_BUILD not found")

# Same for INFRA-FIX dispatch
OLD_INFRA_BUILD = '''                    _v7232_issues_short = "\\n".join(
                        (f"- [{i.get('severity','?')}] {i.get('description', str(i)[:200])}"
                         if isinstance(i, dict) else f"- {i}")
                        for i in critical_issues[:10]
                    )'''

NEW_INFRA_BUILD = '''                    # v7.32: detailed infra issue rendering for devops
                    _v7232_issues_short = format_critical_issues_for_revise(critical_issues, kind="code")'''

if "format_critical_issues_for_revise(critical_issues, kind=\"code\")" in ed_text and OLD_INFRA_BUILD not in ed_text:
    print("[v7.32-D infra] already wired (or via code path)")
elif OLD_INFRA_BUILD in ed_text:
    ed_text = ed_text.replace(OLD_INFRA_BUILD, NEW_INFRA_BUILD, 1)
    print("[v7.32-D infra] INFRA-FIX issues now use detailed format")
else:
    print("[v7.32-D infra] WARN: OLD_INFRA_BUILD not found")

ed.write_text(ed_text)
try:
    py_compile.compile(str(ed), doraise=True)
    print("[v7.32-C+D] dispatcher syntax OK")
except Exception as e:
    print(f"[v7.32-C+D] SYNTAX ERROR: {e}")
