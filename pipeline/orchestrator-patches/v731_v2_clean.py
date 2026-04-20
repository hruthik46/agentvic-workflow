"""v7.31 v2 — clean, all single-quoted strings, no double-quote escape issues."""
import re, py_compile
from pathlib import Path

pb = Path("/var/lib/karios/orchestrator/prompt_builder.py")
text = pb.read_text()

m = re.search(r"_TEMPLATES = \{.*?^\}", text, re.DOTALL | re.MULTILINE)
if not m:
    print("FATAL: _TEMPLATES not found")
    raise SystemExit(1)

new_t = """_TEMPLATES = {
    'ARCH-DESIGN': {
        'intro': 'TASK: Phase 2 architecture design for {gid} iter {it}. Research-backed, testable, deployable.',
        'steps': [
            'bash: cat /var/lib/karios/coordination/requirements/{gid}.md',
            'bash: karios-vault search {intent_query} --limit 8',
            'bash: ls /var/lib/karios/iteration-tracker/{gid}/phase-1-research/ 2>/dev/null && cat /var/lib/karios/iteration-tracker/{gid}/phase-1-research/research-findings.md 2>/dev/null',
            'bash: cd /root/karios-source-code/karios-migration && cat go.mod | head -20  # know dep versions (govmomi, etc)',
            'bash: cd /root/karios-source-code/karios-migration && find internal/ -name *.go | head -20  # learn the existing code structure',
            'file_write: /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/architecture.md (>=2KB) REQUIRED: ## Problem ## Goals (measurable) ## Components (file:line targets) ## Data Flow (concrete API calls + library versions) ## Security ## Concurrency ## Failure modes',
            'file_write: /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/api-contract.md (>=2KB) every endpoint METHOD /path with request schema, 200/4xx/5xx schemas, sample curl with real data',
            'file_write: /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/test-cases.md (>=2KB) 7 dimensions, >=3 cases per dim, each = (precondition, action, expected, evidence-cmd)',
            'file_write: /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/edge-cases.md (>=2KB) >=10 cases (concurrent-write, partial-network-failure, OOM) with mitigation',
            'file_write: /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/deployment-plan.md (>=2KB) rollback plan, feature flag, env vars, services to restart',
            'bash: agent send orchestrator [ARCH-COMPLETE] {gid} iteration {it}',
        ],
        'tail_schema': None,
        'rules': [
            'HARD GATE: each doc >= 2KB. NO placeholder/TODO/TBD strings.',
            'Reference SPECIFIC files in karios-migration repo. No abstractions.',
            'For library APIs (govmomi etc): include EXACT method signatures.',
            'Cross-reference vault learnings.',
            'DO NOT WRITE PROSE. Every output MUST be a tool call.',
        ],
    },
    'ARCH-BLIND-REVIEW': {
        'intro': 'TASK: Adversarial blind review of {gid} arch iter {it}. Generate test cases that would BREAK this design.',
        'steps': [
            'bash: ls -la /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/',
            'bash: for f in architecture api-contract test-cases edge-cases deployment-plan; do wc -c /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/$f.md; done',
            'bash: cat /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/architecture.md',
            'bash: cat /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/api-contract.md',
            'bash: cat /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/test-cases.md',
            'bash: cat /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/edge-cases.md',
            'bash: karios-vault search prior-attempts-{intent_query} --limit 5',
            'file_write: /var/lib/karios/iteration-tracker/{gid}/phase-2-arch-loop/iteration-{it}/review.json with schema below',
            'bash: agent send orchestrator [ARCH-REVIEWED] {gid} iteration {it} < /var/lib/karios/iteration-tracker/{gid}/phase-2-arch-loop/iteration-{it}/review.json',
        ],
        'tail_schema': _ARCH_REVIEW_SCHEMA,
        'rules': [
            'RATE EACH OF 6 DIMENSIONS 0-10 with concrete reasoning (cite the doc line/section).',
            'Generate >=3 ADVERSARIAL test cases per dimension.',
            'If a doc missing or thin (<2KB): mark dimension BLOCKED, rate=0.',
            'rating < 8 OVERALL = REQUEST_CHANGES with critical_issues (severity, category, dimension, description, file_line_ref).',
            'Critical issues MUST be actionable. Architecture is bad is wrong. api-contract.md line 32 missing 4xx schema for /api/v1/migrations is right.',
            'DO NOT WRITE PROSE. Every output MUST be a tool call.',
        ],
    },
    'CODE-REQUEST': {
        'intro': 'TASK: Implement Phase 3 for {gid} iter {it}. READ design -> CODE -> BUILD -> COMMIT -> PUSH. Tool calls only.',
        'steps': [
            'bash: cd /root/karios-source-code/{repo} && pwd',
            'bash: get_minimal_context(task={intent_query})  # MCP code-review-graph if configured, else ls + grep',
            'bash: cat /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/architecture.md',
            'bash: cat /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/api-contract.md',
            'bash: cat /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/test-cases.md',
            'bash: cd /root/karios-source-code/{repo} && git fetch --all && git checkout -b backend/{gid}-{date} origin/main 2>/dev/null || git checkout backend/{gid}-{date}',
            'bash: cd /root/karios-source-code/{repo} && go build ./... 2>&1 | head -10  # baseline',
            'For EACH file in architecture: read_file similar pattern, grep for idioms, then file_write with implementation matching repo conventions',
            'bash: cd /root/karios-source-code/{repo} && go build ./... 2>&1 | head -20  # MUST be GREEN before commit',
            'bash: cd /root/karios-source-code/{repo} && go test ./... -count=1 2>&1 | tail -30',
            'bash: cd /root/karios-source-code/{repo} && git add -p  # explicit, never -A',
            'bash: cd /root/karios-source-code/{repo} && git commit -m {commit_title}',
            'bash: cd /root/karios-source-code/{repo} && git push -u origin backend/{gid}-{date}',
            'bash: cd /root/karios-source-code/{repo} && git rev-parse HEAD',
            'bash: agent send orchestrator [CODING-COMPLETE] {gid} commit_sha=<40-hex> branch=backend/{gid}-{date}',
        ],
        'tail_schema': _CODING_COMPLETE_SCHEMA,
        'rules': [
            'MUST produce a real 40-hex commit SHA + push. Phantom [CODING-COMPLETE] refused.',
            'BUILD MUST BE GREEN before commit. go build returning non-zero = abort + iterate.',
            'KNOWN GO/GOVMOMI API HINTS:',
            '  task.WaitEx(ctx) returns ONLY error -> use task.WaitForResult(ctx, nil) returning (*types.TaskInfo, error)',
            '  taskInfo.Snapshot.Value -> taskInfo.Result.(types.ManagedObjectReference).Value',
            '  device.Backing.FileName -> device.Backing.(*types.VirtualDiskFlatVer2BackingInfo).FileName',
            '  QueryChangedDiskAreas(ctx, *Mo, *Mo, *VirtualDisk, int64) needs pointers + VirtualDisk + int64',
            '  DiskChangeInfo fields: .Length (not ChangedAreaSize), .ChangedArea (not ChangedAreas)',
            '  vmObj.ExportSnapshot(ctx, ref) returns (*nfc.Lease, error) not 3 values',
            '  syntax error unexpected name X expected ( = missing brace BEFORE line X',
            'DO NOT push: .hermes, agentic-workflow, iteration-tracker, agent-worker, .quarantine/. Use explicit git add of internal/ pkg/ cmd/.',
            'On merge conflict: /usr/local/bin/karios-merge-resolve {repo} <file>',
            'DO NOT WRITE PROSE. Every output MUST be a tool call. Watchdog kills prose at 3000 chars.',
        ],
    },
    'E2E-REVIEW': {
        'intro': 'TASK: Adversarial E2E test of {gid} iter {it} on REAL infra. Evidence per dimension or REJECT.',
        'steps': [
            'bash: cat /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/test-cases.md',
            'bash: cat /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/edge-cases.md',
            'bash: cd /root/karios-source-code/{repo} && git log --oneline backend/{gid}-{date} | head -5',
            'bash: cd /root/karios-source-code/{repo} && git checkout backend/{gid}-{date} 2>&1 | tail -3',
            'bash: cd /root/karios-source-code/{repo} && go build ./... 2>&1 | head -15',
            'bash: cd /root/karios-source-code/{repo} && go test ./... -v -count=1 2>&1 | tail -40',
            'bash: cd /root/karios-source-code/{repo} && go vet ./... 2>&1 | head -10',
            'bash: curl -sI http://192.168.118.106:8089/api/v1/healthz',
            'bash: systemctl is-active karios-migration && systemctl status karios-migration --no-pager | head -10',
            'bash: VPW=$(grep ^VMWARE_SSH_PASSWORD /etc/karios/secrets.env | cut -d= -f2-); govc -u root:${VPW}@192.168.115.233 -k about 2>&1 | head -5',
            'bash: VPW=$(grep ^VMWARE_SSH_PASSWORD /etc/karios/secrets.env | cut -d= -f2-); sshpass -p ${VPW} ssh -o StrictHostKeyChecking=no root@192.168.115.232 vim-cmd vmsvc/getallvms | head -10',
            'For each test case: execute, capture stdout/stderr/exit_code into adversarial_test_cases JSON',
            'file_write: /var/lib/karios/iteration-tracker/{gid}/phase-3-coding/iteration-{it}/e2e-results.json (schema: ALL 7 dims populated, evidence with REAL output)',
            'bash: agent send orchestrator [E2E-RESULTS] {gid} iteration {it} < /var/lib/karios/iteration-tracker/{gid}/phase-3-coding/iteration-{it}/e2e-results.json',
        ],
        'tail_schema': _E2E_RESULTS_SCHEMA,
        'rules': [
            'ALL 7 DIMENSIONS MANDATORY: functional_correctness, edge_cases, security, performance, concurrency, resilience, error_handling.',
            'Each dim 0-10 with test_id + evidence. rating >=8 to pass.',
            'ANY CRITICAL severity in critical_issues = automatic REJECT.',
            'critical_issue MUST have: severity (CRITICAL|HIGH|MEDIUM|LOW), category (snake-or-hyphen e.g. syntax-error), dimension, description (file:line if applicable), evidence (real output snippet).',
            'evidence MUST be REAL command output. NO synthesis. If probe cannot run, status=skipped — reason: <why>.',
            'If go build fails -> category=build-failure + severity=CRITICAL + file:line errors as evidence.',
            'If service-unavailable -> systemctl status karios-migration first 5 lines as evidence.',
            'DO NOT WRITE PROSE. Every output MUST be a tool call.',
        ],
    },
    'TEST-RUN': {
        'intro': 'TASK: Functional test execution for {gid} iter {it}. Honest pass/fail counts.',
        'steps': [
            'bash: cat /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/test-cases.md',
            'bash: cd /root/karios-source-code/{repo} && git checkout backend/{gid}-{date} 2>/dev/null || true',
            'bash: cd /root/karios-source-code/{repo} && go build ./... 2>&1 | head -10',
            'bash: cd /root/karios-source-code/{repo} && go test ./... -count=1 -v 2>&1 | tail -100',
            'bash: cd /root/karios-source-code/{repo} && go vet ./... 2>&1 | head -20',
            'For each test case: execute the test command, record pass/fail/skip with output snippet',
            'file_write: /var/lib/karios/iteration-tracker/{gid}/phase-3-coding/iteration-{it}/test-results.json with rating, recommendation, summary, critical_issues, test_results{passed,failed,skipped}, evidence{build,go_test,go_vet}, trace_id',
            'bash: agent send orchestrator [TEST-RESULTS] {gid} iteration {it} < /var/lib/karios/iteration-tracker/{gid}/phase-3-coding/iteration-{it}/test-results.json',
        ],
        'tail_schema': None,
        'rules': [
            'Report HONEST counts. Pass=test exited 0 with PASS. Fail=non-0 OR FAIL. Skip=SKIP.',
            'If go build fails -> rating=0, critical_issues=[severity:CRITICAL, category:build-failure, description:errors].',
            'If tests pass but go vet finds issues -> rating max 7, include vet output.',
            'DO NOT WRITE PROSE. Every output MUST be a tool call.',
        ],
    },
    'PRODUCTION': {
        'intro': 'TASK: Deploy {gid} iter {it} to production. Verify push, deploy, validate.',
        'steps': [
            'bash: cd /root/karios-source-code/{repo} && git log --oneline backend/{gid}-{date} | head -3',
            'bash: cd /root/karios-source-code/{repo} && git rev-list --left-right --count origin/main...backend/{gid}-{date}  # MUST be N tab 0 — all pushed',
            'bash: cd /root/karios-source-code/{repo} && go build ./... && echo BUILD_OK || echo BUILD_FAIL',
            'bash: /root/deploy-all.sh 2>&1 | tail -20',
            'bash: sleep 5 && systemctl is-active karios-migration && systemctl status karios-migration --no-pager | head -10',
            'bash: curl -sI http://192.168.118.106:8089/api/v1/healthz',
            'bash: /usr/local/bin/karios-contract-test 2>&1 | tail -20',
            'file_write: /var/lib/karios/iteration-tracker/{gid}/phase-5-deployment/deploy-summary.json (commit_sha, branch, build_status, deploy_status, healthz_status, contract_test_status, timestamp)',
            'bash: agent send orchestrator [PROD-DEPLOYED] {gid}',
        ],
        'tail_schema': None,
        'rules': [
            'Dispatcher REFUSES [PROD-DEPLOYED] if git rev-list --left-right --count origin/<branch>...HEAD != N tab 0. Push first.',
            'If deploy-all.sh fails OR healthz non-200 OR contract-test fails -> emit [DEPLOY-FAILED] with evidence, NOT [PROD-DEPLOYED].',
            'DO NOT WRITE PROSE. Every output MUST be a tool call.',
        ],
    },
}"""

text = text.replace(m.group(0), new_t)
pb.write_text(text)

try:
    py_compile.compile(str(pb), doraise=True)
    print("[v7.31 v2] syntax OK")
except Exception as e:
    print(f"[v7.31 v2] SYNTAX ERROR: {e}")
    raise SystemExit(1)
print("[v7.31 v2] all 6 templates rewritten with detailed actionable guidance")
