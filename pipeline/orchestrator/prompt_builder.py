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

# ── v7.51: Obsidian vault as primary knowledge source for all 9 agents ──
import subprocess as _vault_sp
import logging as _vault_log

_VAULT_BIN = "/usr/local/bin/karios-vault"
_VAULT_RECENT_N = 8
_VAULT_SEARCH_N = 6
_VAULT_PER_ENTRY_CHARS = 220
_VAULT_TOTAL_CAP = 4096
_VAULT_TIMEOUT_S = 4

def _vault_run(args):
    """Run karios-vault with hard timeout. Returns stdout str or '' on failure."""
    try:
        r = _vault_sp.run([_VAULT_BIN] + list(args),
                          capture_output=True, text=True,
                          timeout=_VAULT_TIMEOUT_S)
        if r.returncode != 0:
            return ""
        return r.stdout or ""
    except Exception:
        return ""

def _vault_trim(line):
    line = line.strip().replace("\n", " ")
    return line[:_VAULT_PER_ENTRY_CHARS]

def _load_vault_context(task_type=None, gap_id=None, keywords=None):
    """Build a capped vault snippet for prompt injection.
    Always returns a non-empty string."""
    seen = set()
    out_lines = []

    recent = _vault_run(["recent", "--limit", str(_VAULT_RECENT_N)])
    for ln in recent.splitlines():
        t = _vault_trim(ln)
        if not t or t in seen:
            continue
        seen.add(t)
        out_lines.append(f"- [recent] {t}")

    query_terms = []
    if task_type: query_terms.append(str(task_type))
    if gap_id: query_terms.append(str(gap_id))
    if keywords:
        if isinstance(keywords, (list, tuple)):
            query_terms.extend(str(k) for k in keywords if k)
        else:
            query_terms.append(str(keywords))

    if query_terms:
        q = " ".join(query_terms)[:200]
        found = _vault_run(["search", q])
        kept = 0
        for ln in found.splitlines():
            if kept >= _VAULT_SEARCH_N:
                break
            t = _vault_trim(ln)
            if not t or t in seen:
                continue
            seen.add(t)
            out_lines.append(f"- [match:{q[:40]}] {t}")
            kept += 1

    if not out_lines:
        return "(vault empty or unreachable - proceed without prior context)"

    blob = "\n".join(out_lines)
    if len(blob) > _VAULT_TOTAL_CAP:
        blob = blob[:_VAULT_TOTAL_CAP] + "\n... [truncated at 4KB cap]"
    return blob
# ── end v7.51 ──


# ── JSON schemas (embedded as strings to keep the prompt compact) ────────────

_ARCH_REVIEW_SCHEMA = (
    '{"gap_id":"{gid}","iteration":{it},"rating":N,'
    '"critical_issues":[{'
    '"severity":"CRITICAL|HIGH|MEDIUM|LOW",'
    '"category":"design-flaw|missing-spec|incoherent-api|untestable|security-gap|scaling-blocker",'
    '"dimension":"correctness|completeness|feasibility|security|testability|resilience",'
    '"doc_line":"architecture.md:LINE or api-contract.md:LINE",'
    '"description":"WHAT is wrong — concise",'
    '"root_cause":"WHY it is wrong — what the doc says vs reality",'
    '"suggested_redesign":"concrete change to the doc — what to replace, what to add",'
    '"acceptance_criteria":"how to verify the redesign — specific doc section + content",'
    '"prior_attempts":["iter N tried X but reviewer rejected because Y"]'
    '}],'
    '"dimensions":{"correctness":N,"completeness":N,"feasibility":N,"security":N,"testability":N,"resilience":N},'
    '"adversarial_test_cases":{"case_id":"what_it_tests → would_break_design? + how"},'
    '"recommendation":"APPROVE|REQUEST_CHANGES|REJECT","summary":"what you found",'
    '"trace_id":"{tid}"}'
)

_E2E_RESULTS_SCHEMA = (
    '{"gap_id":"{gid}","iteration":{it},"rating":N,'
    '"recommendation":"APPROVE|REJECT",'
    '"summary":"what actually ran and what passed",'
    '"critical_issues":[{'
    '"severity":"CRITICAL|HIGH|MEDIUM|LOW",'
    '"category":"snake-or-hyphen-tag e.g. syntax-error",'
    '"dimension":"functional_correctness|edge_cases|security|performance|concurrency|resilience|error_handling",'
    '"file_line":"path/to/file.go:LINE",'
    '"description":"WHAT IS BROKEN — concise",'
    '"root_cause":"WHY it broke — actual reason from runtime evidence",'
    '"reproduction":"exact bash command that reliably triggers the failure",'
    '"evidence":"actual output snippet (stdout/stderr from reproduction)",'
    '"suggested_fix":"concrete code change OR API replacement OR config delta — actionable, not vague",'
    '"acceptance_criteria":"how the fix-agent VERIFIES the fix worked (specific cmd + expected output)",'
    '"prior_attempts":["iter N tried X but failed because Y"]'
    '}],'
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
    'ARCH-DESIGN': {
        'intro': 'TASK: Phase 2 architecture design for {gid} iter {it}. Research-backed, testable, deployable.',
        'steps': [
            'bash: cat /var/lib/karios/coordination/requirements/{gid}.md',
            'bash: karios-vault search {intent_query} --limit 8',
            'bash: ls /var/lib/karios/iteration-tracker/{gid}/phase-1-research/ 2>/dev/null && cat /var/lib/karios/iteration-tracker/{gid}/phase-1-research/research-findings.md 2>/dev/null',
            'bash: cd /root/karios-source-code/karios-migration && cat go.mod | head -20  # know dep versions (govmomi, etc)',
            'bash: cd /root/karios-source-code/karios-migration && find internal/ -name *.go | head -20  # learn the existing code structure',
            'write_file: /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/architecture.md (>=2KB) REQUIRED: ## Problem ## Goals (measurable) ## Components (file:line targets) ## Data Flow (concrete API calls + library versions) ## Security ## Concurrency ## Failure modes',
            'write_file: /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/api-contract.md (>=2KB) every endpoint METHOD /path with request schema, 200/4xx/5xx schemas, sample curl with real data',
            'write_file: /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/test-cases.md (>=2KB) 7 dimensions, >=3 cases per dim, each = (precondition, action, expected, evidence-cmd)',
            'write_file: /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/edge-cases.md (>=2KB) >=10 cases (concurrent-write, partial-network-failure, OOM) with mitigation',
            'write_file: /var/lib/karios/iteration-tracker/{gid}/phase-2-architecture/iteration-{it}/deployment-plan.md (>=2KB) rollback plan, feature flag, env vars, services to restart',
            'bash: agent msg send orchestrator [ARCH-COMPLETE] {gid} iteration {it}',
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
            'write_file: /var/lib/karios/iteration-tracker/{gid}/phase-2-arch-loop/iteration-{it}/review.json with schema below',
            'bash: agent msg send orchestrator [ARCH-REVIEWED] {gid} iteration {it} < /var/lib/karios/iteration-tracker/{gid}/phase-2-arch-loop/iteration-{it}/review.json',
        ],
        'tail_schema': _ARCH_REVIEW_SCHEMA,
        'rules': [
            'RATE EACH OF 6 DIMENSIONS 0-10 with concrete reasoning (cite the doc line/section).',
            'Generate >=3 ADVERSARIAL test cases per dimension.',
            'If a doc missing or thin (<2KB): mark dimension BLOCKED, rate=0.',
            'rating < 8 OVERALL = REQUEST_CHANGES with critical_issues (severity, category, dimension, description, file_line_ref).',
            'Critical issues MUST be actionable. Architecture is bad is wrong. api-contract.md line 32 missing 4xx schema for /api/v1/migrations is right.',
            'v7.50 REAL-ENV MANDATE: review.json MUST contain evidence.real_env_probes with >=5 entries. Each = {claim, doc_ref, command, exit_code, stdout_excerpt, verdict CONFIRMS|CONTRADICTS|INCONCLUSIVE}. Probes target: vCenter (govc 192.168.115.233), ESXi (ssh 192.168.115.232), CloudStack (curl https://192.168.118.202), Karios backend (curl http://192.168.118.106:8089/api/v1/), live UI (curl https://192.168.118.202/). Doc-only reviews are auto-rejected by dispatcher v7.50 gate.',
            'PROBE EXAMPLES (run via bash tool BEFORE writing review.json):',
            '  govc -u root:karios@12345@192.168.115.233 -k about',
            '  sshpass -p karios@12345 ssh -o StrictHostKeyChecking=no root@192.168.115.232 vim-cmd vmsvc/getallvms | head -5',
            '  curl -sk https://192.168.118.202/client/api?command=listHosts -u admin:Adminadmin@123 | head -20',
            '  curl -sf -o /tmp/p.json -w "HTTP %{http_code}\\n" http://192.168.118.106:8089/api/v1/migrations',
            'Capture each probe stdout into evidence.real_env_probes — quote first 500 chars per entry.',
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
            'For EACH file in architecture: read_file similar pattern, grep for idioms, then write_file with implementation matching repo conventions',
            'bash: cd /root/karios-source-code/{repo} && go build ./... 2>&1 | head -20  # MUST be GREEN before commit',
            'bash: cd /root/karios-source-code/{repo} && go test ./... -count=1 2>&1 | tail -30',
            'bash: cd /root/karios-source-code/{repo} && git add -p  # explicit, never -A',
            'bash: cd /root/karios-source-code/{repo} && git commit -m {commit_title}',
            'bash: cd /root/karios-source-code/{repo} && git push -u origin backend/{gid}-{date}',
            'bash: cd /root/karios-source-code/{repo} && git rev-parse HEAD',
            'bash: agent msg send orchestrator [CODING-COMPLETE] {gid} commit_sha=<40-hex> branch=backend/{gid}-{date}',
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
            'bash: VPW=$(grep ^VMWARE_SSH_PASSWORD /etc/karios/secrets.env | cut -d= -f2-); govc -u root:$VPW@192.168.115.233 -k about 2>&1 | head -5',
            'bash: VPW=$(grep ^VMWARE_SSH_PASSWORD /etc/karios/secrets.env | cut -d= -f2-); sshpass -p $VPW ssh -o StrictHostKeyChecking=no root@192.168.115.232 vim-cmd vmsvc/getallvms | head -10',
            'For each test case: execute, capture stdout/stderr/exit_code into adversarial_test_cases JSON',
            'write_file: /var/lib/karios/iteration-tracker/{gid}/phase-3-coding/iteration-{it}/e2e-results.json (schema: ALL 7 dims populated, evidence with REAL output)',
            'bash: agent msg send orchestrator [E2E-RESULTS] {gid} iteration {it} < /var/lib/karios/iteration-tracker/{gid}/phase-3-coding/iteration-{it}/e2e-results.json',
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
            'v7.50 LIVE-API MANDATE: e2e-results.json MUST contain evidence.live_api_probes >=1 entries hitting http://192.168.118.106:8089. Each = {path, method, http_code, response_excerpt, latency_ms, doc_ref, verdict CONFORMS|DEVIATES|ERROR}. Probe EVERY (method,path) declared in api-contract.md. Dispatcher v7.50 gate refuses reviews lacking live_api_probes.',
            'PLAYWRIGHT MANDATE: also run cd /root/karios-source-code/karios-playwright && npx playwright test tests/migration/api.spec.ts --reporter=line — capture pass/fail counts in evidence.playwright_summary.',
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
            'write_file: /var/lib/karios/iteration-tracker/{gid}/phase-3-coding/iteration-{it}/test-results.json with rating, recommendation, summary, critical_issues, test_results{{passed,failed,skipped}}, evidence{{build,go_test,go_vet}}, trace_id',
            'bash: agent msg send orchestrator [TEST-RESULTS] {gid} iteration {it} < /var/lib/karios/iteration-tracker/{gid}/phase-3-coding/iteration-{it}/test-results.json',
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
            'write_file: /var/lib/karios/iteration-tracker/{gid}/phase-5-deployment/deploy-summary.json (commit_sha, branch, build_status, deploy_status, healthz_status, contract_test_status, timestamp)',
            'bash: agent msg send orchestrator [PROD-DEPLOYED] {gid}',
        ],
        'tail_schema': None,
        'rules': [
            'Dispatcher REFUSES [PROD-DEPLOYED] if git rev-list --left-right --count origin/<branch>...HEAD != N tab 0. Push first.',
            'If deploy-all.sh fails OR healthz non-200 OR contract-test fails -> emit [DEPLOY-FAILED] with evidence, NOT [PROD-DEPLOYED].',
            'DO NOT WRITE PROSE. Every output MUST be a tool call.',
        ],
    },
}

# ── Intent tags — optional enrichments ───────────────────────────────────────
_INTENT_EXTRAS = {
    "7_dimensions": "All 7 dimensions (functional_correctness, edge_cases, security, performance, concurrency, resilience, error_handling) MUST have a numeric rating + evidence in adversarial_test_cases.",
    "vmware": ("VMware infrastructure (KRE-Lab):\n"
            "  - vCenter: 192.168.115.233 (vCenter Server 8.0.2 build-24321653) — govc/govmomi for cluster ops\n"
            "  - ESXi Node A: 192.168.115.232 (FREE, 16c/95GB, datastore1, 9 test VMs: ubuntu-vm, karios-test, win-vm, bios-ide-test, multi-nic-test, bsd-efi-bootonly-loader, etc)\n"
            "  - ESXi Node B: 192.168.115.23 (LICENSED — CBT, vMotion, advanced features, 4c/63GB)\n"
            "  - Cluster: Cluster-01 (DRS enabled, no shared storage)\n"
            "  - SSH user/pass for ALL three: root / <REDACTED-SSH-PASSWORD>\n"
            "  - vCenter REST API base: https://192.168.115.233/rest/com/vmware/\n"
            "  - CRITICAL govmomi gotcha: HostSystem.summary.managementServerIp returns vCenter IP NOT ESXi IP. Use HostSystem.name for actual host IP.\n"
            "  - Tests MUST run against BOTH standalone ESXi (.232) AND vCenter-managed flow (.233 → .232/.23) — both are valid karios-migration source types."),
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

    # v7.51: inject vault context as PRIMARY KNOWLEDGE for every prompt.
    _vault_blob = _load_vault_context(
        task_type=task_type, gap_id=gap_id,
        keywords=intent_query or task_type
    )

    out = [tmpl["intro"].format(**fmt)]
    out.append("")
    out.append("=== VAULT CONTEXT (PRIMARY KNOWLEDGE SOURCE) ===")
    out.append("Obsidian vault is the SHARED MEMORY of all 9 KAIROS agents.")
    out.append("Treat these entries as authoritative prior knowledge. If a vault")
    out.append("entry contradicts your assumption, the vault wins unless you have")
    out.append("direct evidence. Cite entry titles when you build on them.")
    out.append("After your task, persist findings via:")
    out.append("  karios-vault learning|critique|rca|bug|fix|decision|memory \"<title>\" --body \"<md>\"")
    out.append("")
    out.append(_vault_blob)
    out.append("")
    out.append("=== END VAULT CONTEXT ===")
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
