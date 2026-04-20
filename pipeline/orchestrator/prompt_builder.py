"""v7.12 — prompt_builder.py
Single source of truth for every dispatch prompt sent to Hermes.
Produces MINIMAL numbered-step prompts that force tool-use, while preserving
intent (like the 7 testing dimensions) via structured intent_tags.

Why this exists:
  MiniMax-M2.7 drifts into prose when the prompt is large (>4K chars) or
  unstructured. Per v7.10 finding, minimal step-numbered prompts work.
  But hand-rolling them loses intent (7 dimensions of testing, adversarial
  coverage, SOUL.md role). This module is the canonical builder — all
  dispatch sites call build_prompt(task_type, ...) instead of inlining strings.

Design:
  - Each task_type has a TEMPLATE: a list of numbered STEPS (each is a tool
    call description) + a TAIL_JSON_SCHEMA + HARD_RULES.
  - intent_tags add supplementary lines (e.g., "7_dimensions" adds the 7
    dimension names to the JSON schema).
  - Total prompt stays under 3500 chars unless intent requires more.
  - Role/profile doc lives in SOUL.md — agents read it via read_file only if
    they hit something the minimal prompt doesn't cover.
"""
from typing import Iterable

# ── JSON schemas (embedded as strings to keep the prompt compact) ────────────

_ARCH_REVIEW_SCHEMA = (
    '{"gap_id":"{gid}","iteration":{it},"rating":N,'
    '"critical_issues":[{"category":"X","severity":"HIGH|MEDIUM|LOW","why":"...","fix":"..."}],'
    '"dimensions":{"correctness":N,"completeness":N,"feasibility":N,"security":N,"testability":N,"resilience":N},'
    '"adversarial_test_cases":{"case_id":"what_it_tests → pass|fail + evidence"},'
    '"recommendation":"APPROVE|REQUEST_CHANGES|REJECT","summary":"what you found",'
    '"trace_id":"{tid}"}'
)

_E2E_RESULTS_SCHEMA = (
    '{"gap_id":"{gid}","iteration":{it},"rating":N,'
    '"recommendation":"APPROVE|REJECT",'
    '"summary":"what actually ran and what passed",'
    '"critical_issues":[...],'
    '"dimensions":{"functional_correctness":N,"edge_cases":N,"security":N,"performance":N,"concurrency":N,"resilience":N,"error_handling":N},'
    '"adversarial_test_cases":{"test_id":"pass|fail + evidence"},'
    '"evidence":{"healthz":"HTTP_CODE","git_log":"commit_sha","go_test":"PASS|FAIL summary","esxi_probe":"output"},'
    '"trace_id":"{tid}"}'
)

_CODING_COMPLETE_SCHEMA = (
    '{"gap_id":"{gid}","iteration":{it},'
    '"commit_sha":"40-hex","branch":"backend/...","files_changed":[...],'
    '"summary":"what was implemented","tests_added":["..."]}'
)

# ── Templates per task_type ──────────────────────────────────────────────────

_TEMPLATES = {
    "ARCH-DESIGN": {
        "intro": "TASK: Phase 2 architecture design for {gid} iter {it}. Research-backed + testable.",
        "steps": [
            "bash: cat /var/lib/karios/coordination/requirements/{gid}.md",
            "bash: karios-vault search '{intent_query}' --limit 8",
            "bash: ls /var/lib/karios/iteration-tracker/{gid}/phase-1-research/ 2>/dev/null && cat /var/lib/karios/iteration-tracker/{gid}/phase-1-research/research-findings.md 2>/dev/null",
            "file_write: /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/architecture.md (>=2KB: problem, high-level design, components, data flows, security)",
            "file_write: /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/api-contract.md (>=2KB: endpoints, schemas, error codes)",
            "file_write: /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/test-cases.md (>=2KB: 7-dimensional coverage)",
            "file_write: /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/edge-cases.md (>=2KB)",
            "file_write: /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/deployment-plan.md (>=2KB)",
            "bash: agent send orchestrator '[ARCH-COMPLETE] {gid} iteration {it}'",
        ],
        "tail_schema": None,
        "rules": [
            "HARD PRE-SUBMIT GATE: all 5 docs >= 2KB, no 'placeholder'/'TODO' strings.",
            "DO NOT WRITE PROSE. Every output MUST be a tool call.",
            "Watchdog kills prose-only at 6000 chars.",
        ],
    },

    "ARCH-BLIND-REVIEW": {
        "intro": "TASK: Blind architecture review for {gid} iter {it}. Rate on 6 dimensions. Adversarial test cases required.",
        "steps": [
            "bash: ls /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/",
            "bash: for f in arch* api* test* edge* deploy*; do wc -c /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/$f.md; done",
            "bash: cat /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/architecture.md",
            "bash: cat /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/test-cases.md",
            "bash: karios-vault search 'vmware blind test {gid}' --limit 5  # prior learnings",
            "file_write: /var/lib/karios/iteration-tracker/{gid}/phase-2-arch-loop/iteration-{it}/review.json with schema below",
            "bash: agent send orchestrator '[ARCH-REVIEWED] {gid} iteration {it}' < /var/lib/karios/iteration-tracker/{gid}/phase-2-arch-loop/iteration-{it}/review.json",
        ],
        "tail_schema": _ARCH_REVIEW_SCHEMA,
        "rules": [
            "You do NOT see code — only the architecture docs.",
            "Generate 3+ adversarial test cases that would break the design.",
            "Rate 0-10 per dimension. rating < 8 = REQUEST_CHANGES with critical_issues list.",
            "DO NOT WRITE PROSE. Every output MUST be a tool call.",
            "DO NOT synthesize. If a doc is missing, mark that dimension 'blocked — doc absent'.",
        ],
    },

    "CODE-REQUEST": {
        "intro": "TASK: Implement Phase 3 for {gid} iter {it}. Read design, write code, ship PR.",
        "steps": [
            "bash: get_minimal_context(task='{intent_query}')  # via MCP tool if configured; else ls + head the arch docs",
            "bash: ls /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/",
            "bash: cat /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/architecture.md",
            "bash: cat /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/api-contract.md",
            "bash: cd /root/karios-source-code/{repo} && git checkout -b backend/{gid}-{date}",
            "file_write: the new/modified source files per architecture",
            "bash: cd /root/karios-source-code/{repo} && git add -A && git commit -m '{commit_title}' && git push origin HEAD",
            "bash: agent send orchestrator '[CODING-COMPLETE] {gid} commit_sha=<40-hex> branch=<name>'",
        ],
        "tail_schema": _CODING_COMPLETE_SCHEMA,
        "rules": [
            "MUST produce a real commit SHA. Phantom [CODING-COMPLETE] without commit_sha=<40-hex> is refused by dispatcher.",
            "Do NOT push agentic-workflow / pipeline-internal files (.hermes, iteration-tracker, agent-worker, etc — blacklisted in .gitignore).",
            "On conflict: /usr/local/bin/karios-merge-resolve <repo> <file>",
            "DO NOT WRITE PROSE. Every output MUST be a tool call.",
        ],
    },

    "E2E-REVIEW": {
        "intro": "TASK: Real E2E test of {gid} iter {it}. Evidence required for all 7 dimensions.",
        "steps": [
            "bash: cat /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/test-cases.md",
            "bash: cd /root/karios-source-code/{repo} && git log --oneline backend/{gid}-{date} | head -5",
            "bash: cd /root/karios-source-code/{repo} && git show <top-commit-sha> --stat",
            "bash: curl -sI http://192.168.118.106:8089/api/v1/healthz",
            "bash: sshpass -p '<SSH_PW>' ssh -o StrictHostKeyChecking=no root@192.168.115.232 'vim-cmd vmsvc/getallvms' | head -15  # ESXi probe for VMware gaps",
            "bash: cd /root/karios-source-code/{repo} && git checkout backend/{gid}-{date} && go test ./... -v 2>&1 | tail -50",
            "bash: cd /root/karios-source-code/karios-playwright && npx playwright test --reporter=json > /tmp/pw-{gid}.json 2>&1 || true",
            "file_write: /var/lib/karios/iteration-tracker/{gid}/phase-3-coding/iteration-{it}/e2e-results.json with schema below (all 7 dimensions, evidence populated from outputs above)",
            "bash: agent send orchestrator '[E2E-RESULTS] {gid} iteration {it}' < /var/lib/karios/iteration-tracker/{gid}/phase-3-coding/iteration-{it}/e2e-results.json",
        ],
        "tail_schema": _E2E_RESULTS_SCHEMA,
        "rules": [
            "7 DIMENSIONS MANDATORY in the JSON: functional_correctness, edge_cases, security, performance, concurrency, resilience, error_handling.",
            "rating >= 8 to pass. Critical in ANY dimension blocks approval.",
            "DO NOT synthesize results. If a test can't run, mark 'skipped — reason: X' in adversarial_test_cases.",
            "Evidence fields must be populated from actual command output (healthz code, git_log sha, go_test summary, esxi_probe first line).",
            "DO NOT WRITE PROSE. Every output MUST be a tool call.",
            "Watchdog kills prose-only at 6000 chars.",
        ],
    },

    "TEST-RUN": {
        "intro": "TASK: Execute functional test plan for {gid} iter {it}. Real commands only.",
        "steps": [
            "bash: cat /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/test-cases.md",
            "bash: cd /root/karios-source-code/{repo} && git checkout backend/{gid}-{date} 2>/dev/null || true && go test ./... -v 2>&1 | tail -60",
            "bash: cd /root/karios-source-code/{repo} && go vet ./... 2>&1 | head -30",
            "file_write: /var/lib/karios/iteration-tracker/{gid}/phase-3-coding/iteration-{it}/test-results.json with pass/fail counts + output snippets",
            "bash: agent send orchestrator '[TEST-RESULTS] {gid} iteration {it}' < /var/lib/karios/iteration-tracker/{gid}/phase-3-coding/iteration-{it}/test-results.json",
        ],
        "tail_schema": None,
        "rules": [
            "Report honest pass/skip/fail counts. Do not guess.",
            "DO NOT WRITE PROSE. Every output MUST be a tool call.",
        ],
    },

    "PRODUCTION": {
        "intro": "TASK: Deploy {gid} iter {it} to production.",
        "steps": [
            "bash: cd /root/karios-source-code/{repo} && git log --oneline backend/{gid}-{date} | head -3",
            "bash: cd /root/karios-source-code/{repo} && git rev-list --left-right --count origin/main...backend/{gid}-{date}  # gate: must be N\\t0 (all pushed)",
            "bash: /root/deploy-all.sh || echo 'no-op: pipeline source change — no infra redeploy'",
            "bash: /usr/local/bin/karios-contract-test || echo 'contract test result captured'",
            "file_write: /var/lib/karios/iteration-tracker/{gid}/phase-5-deployment/deploy-summary.json",
            "bash: agent send orchestrator '[PROD-DEPLOYED] {gid}'",
        ],
        "tail_schema": None,
        "rules": [
            "Dispatcher refuses [PROD-DEPLOYED] if `git rev-list --left-right --count origin/<branch>...HEAD` != `N\\t0` (unpushed commits). Push first.",
            "DO NOT WRITE PROSE. Every output MUST be a tool call.",
        ],
    },
}

# ── Intent tags — optional enrichments ───────────────────────────────────────
_INTENT_EXTRAS = {
    "7_dimensions": "All 7 dimensions (functional_correctness, edge_cases, security, performance, concurrency, resilience, error_handling) MUST have a numeric rating + evidence in adversarial_test_cases.",
    "vmware": "VMware context: ESXi 8.0.3 at 192.168.115.232 (free, 9 test VMs) / licensed at 192.168.115.23. Use govmomi or vim-cmd over SSH.",
    "cloudstack": "CloudStack API on localhost:8080 (401 = alive). karios-core on 192.168.118.106.",
    "adversarial": "You are ADVERSARIAL. Your job is to BREAK the system. If you can't break it after systematic testing → it passes.",
    "pipeline_internal": "This change touches the pipeline itself (not product code). Files land at /var/lib/karios/ or /usr/local/bin/ — they are NOT pushed to gitea org repos (blacklist enforced). Push agentic-workflow files to github.com/hruthik46/agentvic-workflow only.",
}


def build_prompt(
    task_type: str,
    gap_id: str,
    iteration: int = 1,
    trace_id: str = "",
    repo: str = "karios-migration",
    intent_tags: Iterable[str] = (),
    intent_query: str = "",
    commit_title: str = "",
    extra_context: str = "",
) -> str:
    """Build a minimal numbered-step prompt for a given dispatch.

    Args:
        task_type: one of _TEMPLATES keys (ARCH-DESIGN, ARCH-BLIND-REVIEW,
                   CODE-REQUEST, E2E-REVIEW, TEST-RUN, PRODUCTION)
        gap_id, iteration, trace_id: identifiers
        repo: source repo dir under /root/karios-source-code/
        intent_tags: list of tags from _INTENT_EXTRAS (e.g. ["7_dimensions",
                     "vmware", "adversarial"])
        intent_query: 5-10 word task description for get_minimal_context /
                      karios-vault search
        commit_title: for CODE-REQUEST, e.g. "feat(vmware): CBT warm migration"
        extra_context: optional free-text appended after HARD RULES (keep short)

    Returns:
        str: a minimal prompt ready for send_to_agent(..., body=<this>).
    """
    tmpl = _TEMPLATES.get(task_type)
    if tmpl is None:
        return f"[ERROR] unknown task_type={task_type}"

    from datetime import datetime
    date = datetime.utcnow().strftime("%Y%m%d")

    fmt = {
        "gid": gap_id,
        "it": iteration,
        "tid": trace_id,
        "repo": repo,
        "date": date,
        "intent_query": intent_query or f"{task_type} {gap_id}",
        "commit_title": commit_title or f"feat: implement {gap_id}",
    }

    out = [tmpl["intro"].format(**fmt)]
    out.append("")
    for i, step in enumerate(tmpl["steps"], 1):
        out.append(f"{i}. {step.format(**fmt)}")
    out.append("")

    if tmpl.get("tail_schema"):
        out.append("JSON schema for the output file:")
        _sch = tmpl["tail_schema"]
        _sch = _sch.replace("{gid}", str(gap_id)).replace("{it}", str(iteration)).replace("{tid}", str(trace_id))
        out.append(_sch)
        out.append("")

    out.append("HARD RULES:")
    for r in tmpl["rules"]:
        out.append(f"- {r}")

    for tag in intent_tags:
        extra = _INTENT_EXTRAS.get(tag)
        if extra:
            out.append(f"- [{tag}] {extra}")

    if extra_context:
        out.append("")
        out.append("Extra context:")
        out.append(extra_context)

    out.append("")
    out.append(f"Your role doc: ~/.hermes/profiles/<your-agent>/SOUL.md (read_file only if needed). Trace: {trace_id}")
    return "\n".join(out)


# ── Quick smoke test when run directly ───────────────────────────────────────
if __name__ == "__main__":
    p = build_prompt(
        task_type="E2E-REVIEW",
        gap_id="ARCH-IT-018",
        iteration=1,
        trace_id="trace_smoke_001",
        repo="karios-migration",
        intent_tags=["7_dimensions", "vmware", "adversarial"],
        intent_query="vmware cbt warm migration e2e",
    )
    print(p)
    print()
    print(f"--- length: {len(p)} chars ---")
