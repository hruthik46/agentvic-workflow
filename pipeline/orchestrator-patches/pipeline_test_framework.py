"""Comprehensive pipeline-flow integration test framework.

Injects synthetic events + verifies dispatcher routing for every phase
and every special-path branch.

Uses synthetic gap TEST-FLOW-001 (and variants) to avoid polluting real
gaps like ARCH-IT-018.
"""
import json, time, subprocess, re, sys
from pathlib import Path
from datetime import datetime

import redis as _r

R = _r.Redis(host="192.168.118.202", username="karios_admin", password="Adminadmin@123")
ITROOT = Path("/var/lib/karios/iteration-tracker")
SECRETS = "/etc/karios/secrets.env"
DISPATCHER_UNIT = "karios-orchestrator-sub"

# ─── Helpers ────────────────────────────────────────────────────────────────

def setup_synthetic_gap(gap_id: str, requirement: str = ""):
    """Create iteration-tracker dirs for synthetic gap."""
    g = ITROOT / gap_id
    (g / "phase-2-architecture" / "iteration-1").mkdir(parents=True, exist_ok=True)
    (g / "phase-3-coding" / "iteration-1").mkdir(parents=True, exist_ok=True)
    (g / "metadata.json").write_text(json.dumps({
        "gap_id": gap_id, "title": requirement or f"synthetic test for {gap_id}",
        "priority": "low", "created_at": datetime.utcnow().isoformat() + "Z"
    }))
    # Write minimal state to state.json
    sp = Path("/var/lib/karios/orchestrator/state.json")
    s = json.loads(sp.read_text())
    s.setdefault("active_gaps", {})[gap_id] = {
        "state": None, "phase": "0-requirement", "iteration": 1,
        "trace_id": f"trace_test_{gap_id}_{int(time.time())}"
    }
    sp.write_text(json.dumps(s, indent=2))

def cleanup_synthetic_gap(gap_id: str):
    """Mark gap completed so it doesn't pollute future runs."""
    sp = Path("/var/lib/karios/orchestrator/state.json")
    s = json.loads(sp.read_text())
    if gap_id in s.get("active_gaps", {}):
        s["active_gaps"][gap_id]["state"] = "completed"
        s["active_gaps"][gap_id]["phase"] = "completed"
        sp.write_text(json.dumps(s, indent=2))

def inject(stream: str, fields: dict):
    """Inject a message into a Redis stream."""
    return R.xadd(stream, {k: str(v) for k, v in fields.items()})

def grep_journal(since_seconds: int, patterns: list) -> list[str]:
    """Find dispatcher log lines matching any pattern."""
    r = subprocess.run(
        ["journalctl", "-u", DISPATCHER_UNIT, "--no-pager",
         "--since", f"{since_seconds} seconds ago", "-n", "500"],
        capture_output=True, text=True, timeout=10
    )
    out = []
    for line in r.stdout.splitlines():
        if any(p in line for p in patterns):
            out.append(line[20:].strip())
    return out

def stream_xlen(stream: str) -> int:
    try:
        return int(R.xlen(stream))
    except Exception:
        return -1

def latest_stream_body(stream: str) -> str:
    """Get most recent message body from a stream."""
    try:
        entries = R.xrevrange(stream, count=1)
        if not entries:
            return ""
        _id, fields = entries[0]
        # Look for payload or body
        for k in (b"payload", b"body"):
            if k in fields:
                v = fields[k].decode("utf-8", errors="replace")
                # If payload is JSON, extract body field
                if k == b"payload":
                    try:
                        d = json.loads(v)
                        return d.get("body", "")
                    except Exception:
                        return v
                return v
        return str(fields)
    except Exception as e:
        return f"(err: {e})"

# ─── TEST CASES ─────────────────────────────────────────────────────────────

results = []

def record(test_id: str, passed: bool, details: str):
    results.append({"id": test_id, "passed": passed, "details": details})
    icon = "✓" if passed else "✗"
    print(f"  {icon} {test_id}: {details}")

def run_test(test_name: str, fn):
    print(f"\n[TEST] {test_name}")
    try:
        fn()
    except Exception as e:
        record(test_name, False, f"EXCEPTION: {e}")

# ─── Test 1: Phase 4 FAIL → CODE-REVISE with v7.32 detail ───────────────────
def test_phase4_fail_code_revise():
    gap = "TEST-FLOW-PH4FAIL"
    setup_synthetic_gap(gap, "Phase 4 fail test")

    # Write a v7.32-format e2e-results.json
    e2e = {
        "gap_id": gap, "iteration": 1, "rating": 3, "recommendation": "REJECT",
        "summary": "test fail",
        "critical_issues": [{
            "severity": "CRITICAL", "category": "syntax-error",
            "dimension": "functional_correctness",
            "file_line": "internal/foo.go:42",
            "description": "missing semicolon",
            "root_cause": "manual test injected error",
            "reproduction": "go build ./internal/foo/...",
            "evidence": "internal/foo.go:42: expected ;",
            "suggested_fix": "Add `;` at end of line 42",
            "acceptance_criteria": "go build passes",
            "prior_attempts": []
        }],
        "dimensions": {"functional_correctness":3, "edge_cases":5, "security":5,
                       "performance":5, "concurrency":5, "resilience":5, "error_handling":5},
        "evidence": {}, "trace_id": f"trace_test_{gap}"
    }
    e2e_path = ITROOT / gap / "phase-3-coding" / "iteration-1" / "e2e-results.json"
    e2e_path.write_text(json.dumps(e2e, indent=2))

    # Inject
    R.xadd("stream:orchestrator", {
        "from": "code-blind-tester", "to": "orchestrator",
        "subject": f"[E2E-RESULTS] {gap} iteration 1",
        "body": "", "gap_id": gap, "trace_id": e2e["trace_id"]
    })
    time.sleep(5)

    # Verify CODE-REVISE dispatched to backend
    events = grep_journal(15, [f"CODE-REVISE] {gap}", "→ backend"])
    has_revise = any("CODE-REVISE] " + gap in e for e in events)
    record(f"phase4-fail.{gap}.code_revise_dispatched", has_revise,
           f"events: {len([e for e in events if gap in e])}")

    # Verify backend body has v7.32 markers
    body = latest_stream_body("stream:backend-worker")
    markers_found = [m for m in ["ISSUE #1", "WHY (root cause)", "REPRODUCE", "SUGGESTED FIX", "ACCEPTANCE", "missing semicolon"] if m in body]
    record(f"phase4-fail.{gap}.v732_detail_in_backend",
           len(markers_found) >= 5,
           f"v7.32 markers found: {markers_found}")

    # Verify cbt + tester re-dispatched (v7.33.1)
    tester_q = stream_xlen("stream:tester-agent")
    cbt_q = stream_xlen("stream:code-blind-tester")
    record(f"phase4-fail.{gap}.testers_re_dispatched",
           tester_q > 0 or cbt_q > 0,
           f"tester={tester_q} cbt={cbt_q}")
    cleanup_synthetic_gap(gap)

# ─── Test 2: Phase 4 PASS → DevOps deploy ───────────────────────────────────
def test_phase4_pass_to_devops():
    gap = "TEST-FLOW-PH4PASS"
    setup_synthetic_gap(gap)
    e2e = {
        "gap_id": gap, "iteration": 1, "rating": 9, "recommendation": "APPROVE",
        "summary": "all green", "critical_issues": [],
        "dimensions": {"functional_correctness":9,"edge_cases":9,"security":9,
                       "performance":9,"concurrency":9,"resilience":9,"error_handling":9},
        "evidence": {}, "trace_id": f"trace_test_{gap}"
    }
    e2e_path = ITROOT / gap / "phase-3-coding" / "iteration-1" / "e2e-results.json"
    e2e_path.write_text(json.dumps(e2e, indent=2))
    R.xadd("stream:orchestrator", {
        "from": "code-blind-tester", "to": "orchestrator",
        "subject": f"[E2E-RESULTS] {gap} iteration 1",
        "body": "", "gap_id": gap, "trace_id": e2e["trace_id"]
    })
    time.sleep(5)

    events = grep_journal(15, [f"PRODUCTION] {gap}", "→ devops", "PASSED coding loop"])
    has_prod = any("PRODUCTION" in e and gap in e for e in events)
    has_devops = any("→ devops" in e and gap in e for e in events)
    record(f"phase4-pass.{gap}.production_dispatched",
           has_prod or has_devops,
           f"events: {[e[:80] for e in events]}")
    cleanup_synthetic_gap(gap)

# ─── Test 3: INFRA-FIX route (service-unavailable) ──────────────────────────
def test_infra_route():
    gap = "TEST-FLOW-INFRA"
    setup_synthetic_gap(gap)
    e2e = {
        "gap_id": gap, "iteration": 1, "rating": 1, "recommendation": "REJECT",
        "summary": "service down",
        "critical_issues": [{
            "severity": "CRITICAL", "category": "service-unavailable",
            "dimension": "functional_correctness", "description": "service offline",
            "root_cause": "test", "reproduction": "systemctl status x", "evidence": "inactive",
            "suggested_fix": "restart service", "acceptance_criteria": "active"
        }],
        "dimensions": {"functional_correctness":1,"edge_cases":5,"security":5,
                       "performance":5,"concurrency":5,"resilience":5,"error_handling":5},
        "evidence": {}, "trace_id": f"trace_test_{gap}"
    }
    e2e_path = ITROOT / gap / "phase-3-coding" / "iteration-1" / "e2e-results.json"
    e2e_path.write_text(json.dumps(e2e, indent=2))
    R.xadd("stream:orchestrator", {
        "from": "code-blind-tester", "to": "orchestrator",
        "subject": f"[E2E-RESULTS] {gap} iteration 1",
        "body": "", "gap_id": gap, "trace_id": e2e["trace_id"]
    })
    time.sleep(5)

    events = grep_journal(15, [f"INFRA-FIX] {gap}", "→ devops", "v7.23.2"])
    has_infra = any("INFRA-FIX" in e and gap in e for e in events)
    record(f"infra-route.{gap}.routed_to_devops",
           has_infra,
           f"events: {[e[:80] for e in events]}")
    cleanup_synthetic_gap(gap)

# ─── Test 4: Subject normalizer ([COMPLETE] → [E2E-RESULTS]) ────────────────
def test_subject_normalizer():
    gap = "TEST-FLOW-NORMALIZE"
    setup_synthetic_gap(gap)
    # Pre-write e2e-results so disk fallback finds it
    e2e = {
        "gap_id": gap, "iteration": 1, "rating": 3, "recommendation": "REJECT",
        "summary": "norm test", "critical_issues": [],
        "dimensions": {"functional_correctness":3,"edge_cases":5,"security":5,
                       "performance":5,"concurrency":5,"resilience":5,"error_handling":5},
        "evidence": {}, "trace_id": f"trace_test_{gap}"
    }
    e2e_path = ITROOT / gap / "phase-3-coding" / "iteration-1" / "e2e-results.json"
    e2e_path.write_text(json.dumps(e2e, indent=2))
    # Set state to phase=4-testing so normalizer fires
    sp = Path("/var/lib/karios/orchestrator/state.json")
    s = json.loads(sp.read_text())
    s["active_gaps"][gap]["phase"] = "4-testing"
    sp.write_text(json.dumps(s, indent=2))

    # Send [COMPLETE] phase=idle from cbt
    R.xadd("stream:orchestrator", {
        "from": "code-blind-tester", "to": "orchestrator",
        "subject": f"[COMPLETE] code-blind-tester completed gap={gap} phase=idle",
        "body": "", "gap_id": gap, "trace_id": f"trace_test_{gap}"
    })
    time.sleep(5)

    events = grep_journal(15, ["v7.18", "rewriting as [E2E-RESULTS]", "normalized from [COMPLETE]"])
    has_norm = any("v7.18" in e and gap in e for e in events)
    record(f"normalizer.{gap}.complete_to_e2e_results",
           has_norm,
           f"events: {[e[:80] for e in events]}")
    cleanup_synthetic_gap(gap)

# ─── Test 5: Disk fallback (bare body, gap_id present) ──────────────────────
def test_disk_fallback():
    gap = "TEST-FLOW-DISKFB"
    setup_synthetic_gap(gap)
    e2e = {
        "gap_id": gap, "iteration": 2, "rating": 5, "recommendation": "REJECT",
        "summary": "disk test", "critical_issues": [],
        "dimensions": {"functional_correctness":5,"edge_cases":5,"security":5,
                       "performance":5,"concurrency":5,"resilience":5,"error_handling":5},
        "evidence": {}, "trace_id": f"trace_test_{gap}"
    }
    (ITROOT / gap / "phase-3-coding" / "iteration-2").mkdir(parents=True, exist_ok=True)
    (ITROOT / gap / "phase-3-coding" / "iteration-2" / "e2e-results.json").write_text(json.dumps(e2e, indent=2))

    R.xadd("stream:orchestrator", {
        "from": "code-blind-tester", "to": "orchestrator",
        "subject": f"[E2E-RESULTS] {gap} iteration 2",
        "body": "",  # empty body triggers disk fallback
        "gap_id": gap, "trace_id": f"trace_test_{gap}"
    })
    time.sleep(5)

    events = grep_journal(15, [f"disk fallback.*{gap}", f"v7.20.*{gap}"])
    has_fb = any("disk fallback" in e and gap in e for e in events)
    record(f"disk-fallback.{gap}.fired",
           has_fb,
           f"events: {[e[:120] for e in events]}")
    cleanup_synthetic_gap(gap)

# ─── Test 6: Gap-id recovery (subject has no gap) ───────────────────────────
def test_gap_id_recovery():
    gap = "TEST-FLOW-NOGAP"
    setup_synthetic_gap(gap)
    # Write e2e
    e2e = {
        "gap_id": gap, "iteration": 1, "rating": 4, "recommendation": "REJECT",
        "summary": "nogap test", "critical_issues": [],
        "dimensions": {"functional_correctness":4,"edge_cases":5,"security":5,
                       "performance":5,"concurrency":5,"resilience":5,"error_handling":5},
        "evidence": {}, "trace_id": f"trace_test_{gap}"
    }
    (ITROOT / gap / "phase-3-coding" / "iteration-1" / "e2e-results.json").write_text(json.dumps(e2e, indent=2))

    R.xadd("stream:orchestrator", {
        "from": "code-blind-tester", "to": "orchestrator",
        "subject": "[E2E-RESULTS]",  # NO gap_id in subject
        "body": "",
        "gap_id": gap,  # but gap_id field is set; v7.21.1 falls back via state
        "trace_id": f"trace_TEST_FLOW_NOGAP_{int(time.time())}"
    })
    time.sleep(5)

    events = grep_journal(15, ["v7.21.1", "no gap in subject", "recovered gap_id"])
    has_recovery = any("v7.21.1" in e for e in events)
    record(f"gap-recovery.{gap}.fallback_fired",
           has_recovery,
           f"events: {[e[:120] for e in events]}")
    cleanup_synthetic_gap(gap)

# ─── Test 7: format_critical_issues_for_revise output ───────────────────────
def test_format_helper():
    sys.path.insert(0, "/var/lib/karios/orchestrator")
    import importlib
    if "event_dispatcher" in sys.modules:
        del sys.modules["event_dispatcher"]
    import event_dispatcher as ed
    test_input = [{
        "severity": "CRITICAL", "category": "build-failure",
        "dimension": "functional_correctness",
        "file_line": "test.go:1", "description": "test",
        "root_cause": "test cause", "reproduction": "go build",
        "evidence": "evidence", "suggested_fix": "fix it",
        "acceptance_criteria": "build passes", "prior_attempts": []
    }]
    out = ed.format_critical_issues_for_revise(test_input, kind="code")
    markers = ["ISSUE #1", "WHY (root cause)", "REPRODUCE", "SUGGESTED FIX", "ACCEPTANCE"]
    found = [m for m in markers if m in out]
    record("helper.format_critical_issues",
           len(found) == 5,
           f"5/5 markers found" if len(found)==5 else f"missing: {[m for m in markers if m not in found]}")

# ─── Test 8: Classify error (v7.23-A hyphen mapping) ────────────────────────
def test_classify_error():
    sys.path.insert(0, "/var/lib/karios/orchestrator")
    if "event_dispatcher" in sys.modules:
        del sys.modules["event_dispatcher"]
    import event_dispatcher as ed
    cases = [
        ("syntax-error build broken", "coding"),
        ("service-unavailable port-not-listening", "infra"),
        ("api-contract-violation wrong-status-code", "api_contract_violation"),
        ("totally random unrelated text 123", "unknown"),
    ]
    all_pass = True
    for input_text, expected_cat in cases:
        cat, _ = ed.classify_error(input_text)
        if cat != expected_cat:
            all_pass = False
            print(f"  classify('{input_text[:30]}') = {cat}, expected {expected_cat}")
    record("helper.classify_error_cases", all_pass, f"4 cases tested")

# ─── Test 9: Telegram alert sends ───────────────────────────────────────────
def test_telegram_pipe():
    """Verify telegram_alert function works (read TELEGRAM env vars)."""
    sys.path.insert(0, "/var/lib/karios/orchestrator")
    if "event_dispatcher" in sys.modules:
        del sys.modules["event_dispatcher"]
    import event_dispatcher as ed
    try:
        ed.telegram_alert("🧪 PIPELINE-TEST: telegram_alert smoke test")
        record("telegram.smoke_test", True, "telegram_alert call succeeded (check Telegram channel)")
    except Exception as e:
        record("telegram.smoke_test", False, f"err: {e}")

# ─── Test 10: Langfuse trace ingestion ──────────────────────────────────────
def test_langfuse_trace():
    """Verify a fresh trace can be created."""
    import os
    import urllib.request, base64
    for line in open(SECRETS).read().splitlines():
        if line.startswith("LANGFUSE_") and "=" in line:
            k, _, v = line.partition("=")
            os.environ[k.strip()] = v.strip()
    sys.path.insert(0, "/root/agentic-workflow/pipeline/integrations/3-langfuse")
    if "kairos_langfuse_wrapper" in sys.modules:
        del sys.modules["kairos_langfuse_wrapper"]
    import kairos_langfuse_wrapper as lf
    ok = lf.init_langfuse()
    if ok:
        with lf.trace_dispatch("PIPELINE-TEST", "test-agent", "[SMOKE-TEST]") as t:
            pass
        if lf._client:
            lf._client.flush()
        record("langfuse.trace_ingestion", True, "trace created + flushed")
    else:
        record("langfuse.trace_ingestion", False, "init_langfuse returned False")

# ─── Test 11: state.json write/read consistency ─────────────────────────────
def test_state_persist():
    sp = Path("/var/lib/karios/orchestrator/state.json")
    s = json.loads(sp.read_text())
    g_test = "TEST-FLOW-STATE"
    s.setdefault("active_gaps", {})[g_test] = {"phase":"X","iteration":42,"state":None}
    sp.write_text(json.dumps(s, indent=2))
    s2 = json.loads(sp.read_text())
    saved = s2.get("active_gaps", {}).get(g_test, {}).get("iteration") == 42
    # cleanup
    s2["active_gaps"].pop(g_test, None)
    sp.write_text(json.dumps(s2, indent=2))
    record("state.persist_round_trip", saved, "iter=42 written + read back")

# ─── RUN ALL ────────────────────────────────────────────────────────────────
print("=" * 70)
print(f"PIPELINE INTEGRATION TEST — {datetime.now().strftime('%H:%M:%S')}")
print("=" * 70)

run_test("helper.format_critical_issues_for_revise", test_format_helper)
run_test("helper.classify_error", test_classify_error)
run_test("state.persist", test_state_persist)
run_test("telegram.smoke", test_telegram_pipe)
run_test("langfuse.trace", test_langfuse_trace)
run_test("disk-fallback", test_disk_fallback)
run_test("gap-id-recovery", test_gap_id_recovery)
run_test("subject-normalizer", test_subject_normalizer)
run_test("phase4-fail-code-revise", test_phase4_fail_code_revise)
run_test("phase4-pass-to-devops", test_phase4_pass_to_devops)
run_test("infra-route", test_infra_route)

print("\n" + "=" * 70)
print("RESULTS SUMMARY")
print("=" * 70)
passed = sum(1 for r in results if r["passed"])
total = len(results)
print(f"  PASSED: {passed}/{total}")
for r in results:
    icon = "✓" if r["passed"] else "✗"
    print(f"  {icon} {r['id']}: {r['details'][:120]}")

# Save report
report_path = Path("/var/lib/karios/orchestrator/pipeline_test_report.json")
report_path.write_text(json.dumps({
    "timestamp": datetime.now().isoformat(),
    "passed": passed, "total": total,
    "results": results
}, indent=2))
print(f"\n  report saved: {report_path}")
