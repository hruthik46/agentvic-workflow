"""v7.31 — every agent prompt now has detailed, error-aware, language-specific guidance.

Replaces all 6 _TEMPLATES in prompt_builder.py with versions that:
- Tell agent EXACTLY what to look for at each step
- Include language-specific error-fixing patterns (Go govmomi, Python, etc.)
- Mandate read-then-edit-then-verify cycles
- Include common-pitfall callouts (brace counting, type assertions, etc.)
- Have explicit "what to commit" and "what NOT to touch" lists
"""
from pathlib import Path
import py_compile

pb = Path("/var/lib/karios/orchestrator/prompt_builder.py")
text = pb.read_text()

# Find and replace the entire _TEMPLATES dict
import re
m = re.search(r"_TEMPLATES = \{.*?^\}", text, re.DOTALL | re.MULTILINE)
if not m:
    print("[v7.31] FATAL: _TEMPLATES dict not found")
else:
    new_templates = '''_TEMPLATES = {
    "ARCH-DESIGN": {
        "intro": "TASK: Phase 2 architecture design for {gid} iter {it}. Research-backed, testable, deployable.",
        "steps": [
            "bash: cat /var/lib/karios/coordination/requirements/{gid}.md  # the source requirement",
            "bash: karios-vault search '{intent_query}' --limit 8  # learn from prior similar work",
            "bash: ls /var/lib/karios/iteration-tracker/{gid}/phase-1-research/ 2>/dev/null && cat /var/lib/karios/iteration-tracker/{gid}/phase-1-research/research-findings.md 2>/dev/null",
            "bash: cd /root/karios-source-code/karios-migration && grep -rln 'similar pattern keywords' --include='*.go' | head -10  # find existing similar code to learn from",
            "bash: cd /root/karios-source-code/karios-migration && cat go.mod | head -20  # know the deps available (govmomi version, etc)",
            "file_write: /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/architecture.md (>=2KB)\\n  REQUIRED SECTIONS: ## Problem ## Goals (with measurable success criteria) ## Components (with file:line targets) ## Data Flow (with concrete API calls + library versions) ## Security ## Concurrency model ## Failure modes",
            "file_write: /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/api-contract.md (>=2KB)\\n  REQUIRED: every endpoint as METHOD /path → 200 schema / 4xx schema / 5xx schema. Sample curl with real data. Field types ALL caps for non-null required fields.",
            "file_write: /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/test-cases.md (>=2KB)\\n  REQUIRED: 7 dimensions as H2 sections; ≥3 concrete test cases per dimension; each test = (precondition, action, expected, evidence-collection-cmd).",
            "file_write: /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/edge-cases.md (>=2KB)\\n  REQUIRED: ≥10 edge cases (concurrent-write, partial-network-failure, malformed-input, OOM, etc.) with mitigation per case.",
            "file_write: /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/deployment-plan.md (>=2KB)\\n  REQUIRED: rollback plan, feature flag, env vars added, services to restart, dependency upgrades.",
            "bash: agent send orchestrator '[ARCH-COMPLETE] {gid} iteration {it}'",
        ],
        "tail_schema": None,
        "rules": [
            "HARD GATE: each doc ≥2KB. NO 'placeholder', 'TODO', or 'TBD' strings.",
            "Reference SPECIFIC files in karios-migration repo (e.g. internal/providers/vmware/cbt.go). Don't speak in abstractions.",
            "If you reference a library API (govmomi, etc.), include the EXACT method signature you'll use.",
            "Cross-reference with vault learnings. If a similar feature was built before, cite the gap_id.",
            "DO NOT WRITE PROSE between tool calls. Every output MUST be a tool call.",
            "Watchdog kills prose-only at 3000 chars (v7.27).",
        ],
    },

    "ARCH-BLIND-REVIEW": {
        "intro": "TASK: Adversarial blind review of {gid} arch iter {it}. You see ONLY docs, not code. Generate test cases that would BREAK this design.",
        "steps": [
            "bash: ls -la /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/  # verify all 5 docs exist",
            "bash: for f in architecture api-contract test-cases edge-cases deployment-plan; do wc -c /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/$f.md; done  # confirm ≥2KB each",
            "bash: cat /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/architecture.md",
            "bash: cat /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/api-contract.md",
            "bash: cat /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/test-cases.md",
            "bash: cat /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/edge-cases.md",
            "bash: karios-vault search 'similar to {intent_query}' --limit 5  # has this design been tried + failed before?",
            "bash: karios-vault recent --kind learning --limit 10  # recent lessons across all gaps",
            "file_write: /var/lib/karios/iteration-tracker/{gid}/phase-2-arch-loop/iteration-{it}/review.json with schema below",
            "bash: agent send orchestrator '[ARCH-REVIEWED] {gid} iteration {it}' < /var/lib/karios/iteration-tracker/{gid}/phase-2-arch-loop/iteration-{it}/review.json",
        ],
        "tail_schema": _ARCH_REVIEW_SCHEMA,
        "rules": [
            "RATE EACH OF 6 DIMENSIONS 0-10 with concrete reasoning (cite the doc line/section that led to your score).",
            "Generate ≥3 ADVERSARIAL test cases per dimension that would break the design (race condition, malformed input, partial failure).",
            "If a doc is missing or thin (<2KB), mark dimension 'BLOCKED — doc absent' and rate=0 for that dim.",
            "rating < 8 OVERALL = REQUEST_CHANGES with specific critical_issues list (each entry: severity, category, dimension, description, file_line_ref).",
            "Critical issues MUST be actionable. 'Architecture is bad' is wrong. 'api-contract.md line 32 missing 4xx response schema for /api/v1/migrations' is right.",
            "DO NOT WRITE PROSE. Every output MUST be a tool call.",
            "DO NOT synthesize results. If you can't read a doc, mark blocked + score 0.",
        ],
    },

    "CODE-REQUEST": {
        "intro": "TASK: Implement Phase 3 for {gid} iter {it}. READ design → CODE → BUILD → COMMIT → PUSH. Tool calls only.",
        "steps": [
            "bash: cd /root/karios-source-code/{repo} && pwd",
            "bash: get_minimal_context(task='{intent_query}')  # MCP code-review-graph; if absent: ls + grep",
            "bash: cat /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/architecture.md",
            "bash: cat /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/api-contract.md",
            "bash: cat /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/test-cases.md",
            "bash: cd /root/karios-source-code/{repo} && git fetch --all && git checkout -b backend/{gid}-{date} origin/main 2>/dev/null || git checkout backend/{gid}-{date}",
            "bash: cd /root/karios-source-code/{repo} && go build ./... 2>&1 | head -10  # baseline: must be GREEN before changes",
            "(for EACH new/modified file in architecture):\\n  - bash: read_file <path-to-existing-or-similar-file>  # learn the patterns used in this repo\\n  - bash: grep -rn 'similar function or type' --include='*.go' .  # find idioms\\n  - file_write: <path> with the implementation. Match repo conventions (error handling, logging via slog or zap, etc).",
            "bash: cd /root/karios-source-code/{repo} && go build ./... 2>&1 | head -20  # MUST be GREEN. If errors, fix them iteratively.",
            "bash: cd /root/karios-source-code/{repo} && go test ./... -count=1 2>&1 | tail -30  # MUST pass or skip cleanly",
            "bash: cd /root/karios-source-code/{repo} && git add -p  # explicit add (NEVER git add -A — blacklist might leak)",
            "bash: cd /root/karios-source-code/{repo} && git status --short",
            "bash: cd /root/karios-source-code/{repo} && git commit -m '{commit_title}'",
            "bash: cd /root/karios-source-code/{repo} && git push -u origin backend/{gid}-{date}",
            "bash: cd /root/karios-source-code/{repo} && git rev-parse HEAD  # capture the commit SHA",
            "bash: agent send orchestrator '[CODING-COMPLETE] {gid} commit_sha=<the 40-hex from above> branch=backend/{gid}-{date}'",
        ],
        "tail_schema": _CODING_COMPLETE_SCHEMA,
        "rules": [
            "MUST produce a real 40-hex commit SHA + push to origin. Phantom [CODING-COMPLETE] is refused by dispatcher.",
            "BUILD MUST BE GREEN before commit. `go build ./...` returning non-zero = abort + iterate.",
            "KNOWN GO/GOVMOMI API HINTS:",
            "  - task.WaitEx(ctx) returns ONLY error → use task.WaitForResult(ctx, nil) which returns (*types.TaskInfo, error)",
            "  - taskInfo.Snapshot.Value → taskInfo.Result.(types.ManagedObjectReference).Value",
            "  - device.Backing.FileName → device.Backing.(*types.VirtualDiskFlatVer2BackingInfo).FileName",
            "  - QueryChangedDiskAreas(ctx, *Mo, *Mo, *VirtualDisk, int64) — needs pointers + VirtualDisk + int64 offset",
            "  - DiskChangeInfo fields: .Length (not .ChangedAreaSize), .ChangedArea (not .ChangedAreas)",
            "  - vmObj.ExportSnapshot(ctx, ref) returns (*nfc.Lease, error) not 3 values",
            "  - syntax error 'unexpected name X expected (' = missing `}` brace BEFORE line X",
            "DO NOT push these blacklisted: .hermes, agentic-workflow files, iteration-tracker, agent-worker, .quarantine/. Use explicit `git add` of internal/ pkg/ cmd/ only.",
            "On merge conflict: /usr/local/bin/karios-merge-resolve {repo} <file>",
            "DO NOT WRITE PROSE. Every output MUST be a tool call. Watchdog kills prose-only at 3000 chars.",
            "iteration {it}/8. After 5 unsuccessful iterations, escalation fires automatically.",
        ],
    },

    "E2E-REVIEW": {
        "intro": "TASK: Adversarial E2E test of {gid} iter {it} on REAL infra. Evidence per dimension or REJECT.",
        "steps": [
            "bash: cat /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/test-cases.md",
            "bash: cat /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/edge-cases.md",
            "bash: cd /root/karios-source-code/{repo} && git log --oneline backend/{gid}-{date} | head -5",
            "bash: cd /root/karios-source-code/{repo} && git checkout backend/{gid}-{date} 2>&1 | tail -3",
            "bash: cd /root/karios-source-code/{repo} && go build ./... 2>&1 | head -15  # build sanity (GREEN required for further tests)",
            "bash: cd /root/karios-source-code/{repo} && go test ./... -v -count=1 2>&1 | tail -40",
            "bash: cd /root/karios-source-code/{repo} && go vet ./... 2>&1 | head -10",
            "bash: curl -sI http://192.168.118.106:8089/api/v1/healthz  # API alive?",
            "bash: curl -sS http://192.168.118.106:8089/api/v1/migrations | head -5  # API actually responding to product paths?",
            "bash: systemctl is-active karios-migration && systemctl status karios-migration --no-pager | head -10  # service running?",
            "bash: VPW=$(grep ^VMWARE_SSH_PASSWORD /etc/karios/secrets.env | cut -d= -f2-); govc -u \"root:${VPW}@192.168.115.233\" -k about 2>&1 | head -5",
            "bash: VPW=$(grep ^VMWARE_SSH_PASSWORD /etc/karios/secrets.env | cut -d= -f2-); sshpass -p \"${VPW}\" ssh -o StrictHostKeyChecking=no root@192.168.115.232 'vim-cmd vmsvc/getallvms' | head -10",
            "bash: VPW=$(grep ^VMWARE_SSH_PASSWORD /etc/karios/secrets.env | cut -d= -f2-); sshpass -p \"${VPW}\" ssh -o StrictHostKeyChecking=no root@192.168.115.23 'vim-cmd vmsvc/getallvms' | head -10",
            "bash: cd /root/karios-source-code/karios-playwright 2>/dev/null && npx playwright test --reporter=json > /tmp/pw-{gid}.json 2>&1 || echo 'playwright skipped'",
            "(for each test case in test-cases.md): execute the listed command, capture stdout/stderr/exit_code, save into adversarial_test_cases JSON",
            "file_write: /var/lib/karios/iteration-tracker/{gid}/phase-3-coding/iteration-{it}/e2e-results.json (schema below — ALL 7 dimensions populated, evidence with REAL captured output)",
            "bash: agent send orchestrator '[E2E-RESULTS] {gid} iteration {it}' < /var/lib/karios/iteration-tracker/{gid}/phase-3-coding/iteration-{it}/e2e-results.json",
        ],
        "tail_schema": _E2E_RESULTS_SCHEMA,
        "rules": [
            "ALL 7 DIMENSIONS MANDATORY: functional_correctness, edge_cases, security, performance, concurrency, resilience, error_handling.",
            "Each dimension scored 0-10. Each score MUST cite test_id + evidence in the JSON.",
            "rating ≥ 8 to pass. ANY 'CRITICAL' severity in critical_issues = automatic REJECT.",
            "Each critical_issue MUST have: severity (CRITICAL|HIGH|MEDIUM|LOW), category (snake-or-hyphen-case e.g. 'syntax-error'), dimension, description (concrete file:line if applicable), evidence (command output snippet).",
            "evidence fields MUST be REAL command output. NO synthesized strings. If you can't run a probe, set status='skipped — reason: <why>'.",
            "If go build fails → category='build-failure' + severity=CRITICAL + the file:line errors as evidence.",
            "If service-unavailable → run `systemctl status karios-migration` and put first 5 log lines in evidence.",
            "DO NOT WRITE PROSE. Every output MUST be a tool call. Watchdog kills prose at 3000 chars.",
        ],
    },

    "TEST-RUN": {
        "intro": "TASK: Functional test execution for {gid} iter {it}. Honest pass/fail counts.",
        "steps": [
            "bash: cat /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/test-cases.md",
            "bash: cd /root/karios-source-code/{repo} && git checkout backend/{gid}-{date} 2>/dev/null || true",
            "bash: cd /root/karios-source-code/{repo} && go build ./... 2>&1 | head -10  # baseline: build status",
            "bash: cd /root/karios-source-code/{repo} && go test ./... -count=1 -v 2>&1 | tail -100",
            "bash: cd /root/karios-source-code/{repo} && go vet ./... 2>&1 | head -20",
            "(for each test case in test-cases.md): execute the test command, record pass/fail/skip with output snippet",
            "file_write: /var/lib/karios/iteration-tracker/{gid}/phase-3-coding/iteration-{it}/test-results.json with: {{\\\"gap_id\\\":\\\"{gid}\\\", \\\"iteration\\\":{it}, \\\"rating\\\":N, \\\"recommendation\\\":\\\"APPROVE|REJECT\\\", \\\"summary\\\":\\\"...\\\", \\\"critical_issues\\\":[...], \\\"test_results\\\":{{\\\"passed\\\":N, \\\"failed\\\":N, \\\"skipped\\\":N}}, \\\"evidence\\\":{{\\\"build\\\":\\\"...\\\",\\\"go_test\\\":\\\"...\\\",\\\"go_vet\\\":\\\"...\\\"}}, \\\"trace_id\\\":\\\"{trace_id}\\\"}}",
            "bash: agent send orchestrator '[TEST-RESULTS] {gid} iteration {it}' < /var/lib/karios/iteration-tracker/{gid}/phase-3-coding/iteration-{it}/test-results.json",
        ],
        "tail_schema": None,
        "rules": [
            "Report HONEST counts. Pass = test exited 0 with PASS in output. Fail = exit non-0 OR FAIL in output. Skip = SKIP in output.",
            "If `go build` fails → rating=0, critical_issues=[{{severity:CRITICAL, category:'build-failure', description:<errors>}}].",
            "If tests pass but `go vet` finds issues → rating max 7, include vet output in critical_issues.",
            "DO NOT WRITE PROSE. Every output MUST be a tool call. Watchdog kills prose at 3000 chars.",
        ],
    },

    "PRODUCTION": {
        "intro": "TASK: Deploy {gid} iter {it} to production. Verify push, deploy, validate.",
        "steps": [
            "bash: cd /root/karios-source-code/{repo} && git log --oneline backend/{gid}-{date} | head -3",
            "bash: cd /root/karios-source-code/{repo} && git rev-list --left-right --count origin/main...backend/{gid}-{date}  # MUST be N\\\\t0 — all commits pushed",
            "bash: cd /root/karios-source-code/{repo} && go build ./... && echo BUILD_OK || echo BUILD_FAIL  # final sanity",
            "bash: /root/deploy-all.sh 2>&1 | tail -20  # actual deploy",
            "bash: sleep 5 && systemctl is-active karios-migration && systemctl status karios-migration --no-pager | head -10  # service alive?",
            "bash: curl -sI http://192.168.118.106:8089/api/v1/healthz  # final HTTP probe",
            "bash: /usr/local/bin/karios-contract-test 2>&1 | tail -20  # contract regression",
            "file_write: /var/lib/karios/iteration-tracker/{gid}/phase-5-deployment/deploy-summary.json (commit_sha, branch, build_status, deploy_status, healthz_status, contract_test_status, timestamp)",
            "bash: agent send orchestrator '[PROD-DEPLOYED] {gid}'",
        ],
        "tail_schema": None,
        "rules": [
            "Dispatcher REFUSES [PROD-DEPLOYED] if `git rev-list --left-right --count origin/<branch>...HEAD` != `N\\\\t0` (unpushed commits). Push first.",
            "If deploy-all.sh fails OR healthz returns non-200 OR contract-test fails → DO NOT emit [PROD-DEPLOYED]. Emit [DEPLOY-FAILED] with evidence.",
            "DO NOT WRITE PROSE. Every output MUST be a tool call.",
        ],
    },
}'''
    text = text.replace(m.group(0), new_templates)
    pb.write_text(text)
    print(f"[v7.31] all 6 templates rewritten with detailed actionable guidance")

try:
    py_compile.compile(str(pb), doraise=True)
    print("[v7.31] prompt_builder syntax OK")
except Exception as e:
    print(f"[v7.31] SYNTAX ERROR: {e}")
