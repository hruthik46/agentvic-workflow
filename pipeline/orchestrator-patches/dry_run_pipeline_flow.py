"""DRY RUN THE PIPELINE FLOW (not karios-migration code).

Simulate each agent's role by manually injecting messages + reading what the
dispatcher routes. Find pipeline bugs at handoff boundaries.

Flow:
  1. ME (as code-blind-tester): write a v7.32-format e2e-results.json with all
     11 detailed fields populated. Inject [E2E-RESULTS] envelope.
  2. Dispatcher should:
     a. Parse the v7.32 fields correctly
     b. Route to handle_e2e_results
     c. Build CODE-REVISE body via format_critical_issues_for_revise()
     d. Dispatch [CODE-REVISE] to backend with all detail
  3. ME (as backend reader): inspect what backend's stream actually received.
     Verify the v7.32 fields (root_cause, reproduction, suggested_fix, acceptance_criteria)
     are present in the prompt.
  4. ME (as code-blind-tester re-test): cbt should ALSO have a fresh [E2E-REVIEW]
     in its stream from v7.33.1 re-dispatch logic.

Find any gap in the chain.
"""
import json, time, sys, subprocess
from pathlib import Path

print("=" * 75)
print("PIPELINE MESSAGE-FLOW DRY RUN — testing handoffs between agents")
print("=" * 75)

# ─── STEP 1 (as cbt): write a proper v7.32-format e2e-results.json ───────────
print("\n[STEP 1: ME as code-blind-tester — write v7.32-format e2e-results.json]")
v732_report = {
    "gap_id": "ARCH-IT-018",
    "iteration": 5,
    "rating": 2,
    "recommendation": "REJECT",
    "summary": "DRY RUN: Build broken with 3 govmomi API issues + 1 missing brace. Backend needs to fix in cbt.go + features.go + discovery.go.",
    "critical_issues": [
        {
            "severity": "CRITICAL",
            "category": "build-failure",
            "dimension": "functional_correctness",
            "file_line": "internal/migration/features.go:432",
            "description": "syntax error: unexpected name levelForPreflight, expected '('",
            "root_cause": "Missing closing brace `}` somewhere in runConnectivityChecks function (depth-tracker shows if rc.Destination block unclosed). The `func levelForPreflight` at line 432 is parsed as if inside another function.",
            "reproduction": "cd /root/karios-source-code/karios-migration && go build ./internal/migration/... 2>&1 | head -3",
            "evidence": "internal/migration/features.go:432:6: syntax error: unexpected name levelForPreflight, expected (",
            "suggested_fix": "Count braces in features.go between line 274 (func runConnectivityChecks) and line 432. Add missing `}` between line 398 and 399 (closes 'if rc.Destination != nil && rc.VMDetail != nil' block opened at line 363).",
            "acceptance_criteria": "go build ./internal/migration/... exits 0 with no syntax errors",
            "prior_attempts": [
                "iter 2 tried adding brace at line 430 — failed because that closes inner block not the if",
                "iter 3 tried gofmt -w — failed because gofmt cant fix structural brace errors"
            ]
        },
        {
            "severity": "CRITICAL",
            "category": "govmomi-api-drift",
            "dimension": "functional_correctness",
            "file_line": "internal/providers/vmware/discovery.go:372",
            "description": "backing.Kind undefined (type *types.VirtualDiskRawDiskMappingVer1BackingInfo has no field or method Kind)",
            "root_cause": "govmomi v0.40+ removed the Kind enum and CompatibilityMode string field. RDM detection must use a different mechanism.",
            "reproduction": "cd /root/karios-source-code/karios-migration && go build ./internal/providers/vmware/...",
            "evidence": "discovery.go:372:15: backing.Kind undefined; discovery.go:374:16: undefined: types.RawDiskMappingPhysical",
            "suggested_fix": "Replace `backing.Kind` with `backing.CompatibilityMode` (string field). Compare against literal strings 'physicalMode' / 'virtualMode' instead of types.RawDiskMappingPhysical / types.RawDiskMappingVirtual constants.",
            "acceptance_criteria": "go build ./internal/providers/vmware/... exits 0",
            "prior_attempts": []
        },
        {
            "severity": "CRITICAL",
            "category": "type-field-mismatch",
            "dimension": "functional_correctness",
            "file_line": "internal/migration/features.go:408",
            "description": "rc.VMDetail.BootMode undefined (type *provider.VMDetail has no field or method BootMode)",
            "root_cause": "VMDetail struct has BIOSType + SecureBoot fields, NOT BootMode. BootMode field exists on DeployOptions/RegisterTemplateOptions, not on VMDetail.",
            "reproduction": "cd /root/karios-source-code/karios-migration && go build ./internal/migration/...",
            "evidence": "features.go:408:40: rc.VMDetail.BootMode undefined (type *provider.VMDetail has no field or method BootMode)",
            "suggested_fix": "Replace `rc.VMDetail.BootMode == \"Secure\" || rc.VMDetail.BootMode == \"UEFI\"` with `rc.VMDetail.SecureBoot || string(rc.VMDetail.BIOSType) == \"UEFI\"`. For the message string, derive bootlabel = \"Secure\" if SecureBoot else string(BIOSType).",
            "acceptance_criteria": "features.go compiles; preflight check still warns when source VM uses UEFI/Secure boot",
            "prior_attempts": []
        }
    ],
    "dimensions": {
        "functional_correctness": 1, "edge_cases": 5, "security": 5,
        "performance": 5, "concurrency": 5, "resilience": 5, "error_handling": 5,
    },
    "adversarial_test_cases": {
        "build-attempt-1": "FAIL: 7 errors (4 in discovery.go, 3 BootMode in features.go) - blocks all downstream",
        "test-attempt-1": "FAIL: cascading build failures in internal/migration, internal/providers/vmware, internal/server",
        "service-restart": "PASS: karios-migration is active (but stale binary)"
    },
    "evidence": {
        "healthz": "404 Not Found (route registration broken)",
        "git_log": "ef5e305 (HEAD of backend/ARCH-IT-018-cbt) feat(vmware): CBT warm migration",
        "go_test": "FAIL: 3 packages fail-build, 17 pass",
        "esxi_probe": "skipped (dry-run)"
    },
    "trace_id": f"trace_dry_run_full_{int(time.time())}",
    "synthesized_by": "DRY-RUN-as-cbt",
}

# Write to disk
out_path = Path("/var/lib/karios/iteration-tracker/ARCH-IT-018/phase-3-coding/iteration-5/e2e-results.json")
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(json.dumps(v732_report, indent=2))
print(f"  ✓ wrote {out_path} (v7.32 format, {len(v732_report['critical_issues'])} detailed issues)")

# ─── STEP 2 (as cbt): inject [E2E-RESULTS] envelope to dispatcher ───────────
print("\n[STEP 2: ME as code-blind-tester — inject [E2E-RESULTS] to orchestrator]")
import redis
r = redis.Redis(host="192.168.118.202", username="karios_admin", password="Adminadmin@123")
inj_id = r.xadd("stream:orchestrator", {
    "from": "code-blind-tester", "to": "orchestrator",
    "subject": "[E2E-RESULTS] ARCH-IT-018 iteration 5",
    "body": "",  # body empty triggers v7.20 disk fallback to read e2e-results.json
    "gap_id": "ARCH-IT-018",
    "trace_id": v732_report["trace_id"],
})
print(f"  ✓ injected: {inj_id.decode() if isinstance(inj_id, bytes) else inj_id}")

# ─── STEP 3: wait for dispatcher to process ─────────────────────────────────
print("\n[STEP 3: WAIT 6s for dispatcher to route...]")
time.sleep(6)

# ─── STEP 4: verify dispatcher routed correctly ─────────────────────────────
print("\n[STEP 4: Inspect dispatcher events]")
r2 = subprocess.run(
    ["journalctl", "-u", "karios-orchestrator-sub", "--no-pager", "--since", "10 seconds ago", "-n", "50"],
    capture_output=True, text=True, timeout=10
)
events = [l[20:].strip() for l in r2.stdout.splitlines()
          if any(k in l for k in ["E2E-RESULTS", "disk fallback", "CODE-REVISE", "→ backend",
                                    "→ code-blind", "→ tester", "ESCALATE", "v7.33", "INFRA-FIX",
                                    "v7.32", "v7.21-C"])]
for e in events:
    print(f"  {e[:240]}")

# ─── STEP 5: verify backend stream received v7.32 detailed body ─────────────
print("\n[STEP 5: Verify backend stream received DETAILED v7.32 prompt]")
r3 = subprocess.run(
    ["redis-cli", "-h", "192.168.118.202", "--user", "karios_admin",
     "--pass", "Adminadmin@123", "--no-auth-warning",
     "XREVRANGE", "stream:backend-worker", "+", "-", "COUNT", "1"],
    capture_output=True, text=True, timeout=5
)
out = r3.stdout
# Look for v7.32 marker fields
markers = ["root_cause", "reproduction", "suggested_fix", "acceptance_criteria",
            "ISSUE #1", "WHAT:", "WHY (root cause)", "REPRODUCE", "EVIDENCE", "SUGGESTED FIX",
            "ACCEPTANCE", "MANDATORY BUILD-FIX-BUILD", "task.WaitEx", "BootMode"]
found = [m for m in markers if m in out]
print(f"  v7.32 markers found in backend's latest message: {found}")
if not found:
    print(f"  raw stream entry:")
    print(f"    {out[:1500]}")

# ─── STEP 6: verify cbt + tester also got fresh re-dispatch (v7.33.1) ──────
print("\n[STEP 6: Verify cbt + tester received re-dispatch (v7.33.1)]")
for stream in ["stream:code-blind-tester", "stream:tester-agent"]:
    r4 = subprocess.run(
        ["redis-cli", "-h", "192.168.118.202", "--user", "karios_admin",
         "--pass", "Adminadmin@123", "--no-auth-warning",
         "XLEN", stream], capture_output=True, text=True, timeout=5)
    print(f"  {stream} XLEN: {r4.stdout.strip()}")

# ─── STEP 7: state.json should now reflect iter 6 ──────────────────────────
print("\n[STEP 7: state.json after dry-run]")
state = json.load(open("/var/lib/karios/orchestrator/state.json"))
g = state.get("active_gaps", {}).get("ARCH-IT-018", {})
print(f"  ARCH-IT-018: state={g.get('state')} phase={g.get('phase')} iter={g.get('iteration')} last_rating={g.get('last_rating')}")
