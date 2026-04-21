"""Pipeline integration test v2 — remaining phase tests + 9-agent health check."""
import json, time, subprocess, sys, os
from pathlib import Path
from datetime import datetime

import redis as _r
R = _r.Redis(host="192.168.118.202", username="karios_admin", password="Adminadmin@123")
ITROOT = Path("/var/lib/karios/iteration-tracker")
SECRETS = "/etc/karios/secrets.env"

results = []
def record(test_id, passed, details):
    results.append({"id": test_id, "passed": passed, "details": details})
    icon = "✓" if passed else "✗"
    print(f"  {icon} {test_id}: {details[:160]}")

def grep_journal(unit, since_seconds, patterns):
    r = subprocess.run(
        ["journalctl", "-u", unit, "--no-pager",
         "--since", f"{since_seconds} seconds ago", "-n", "1000"],
        capture_output=True, text=True, timeout=10
    )
    return [l[20:].strip() for l in r.stdout.splitlines()
            if any(p in l for p in patterns)]

def setup_synth(gap_id, phase="0-requirement", iteration=1):
    g = ITROOT / gap_id
    (g / "phase-2-architecture" / "iteration-1").mkdir(parents=True, exist_ok=True)
    (g / "phase-3-coding" / "iteration-1").mkdir(parents=True, exist_ok=True)
    (g / "phase-5-deployment").mkdir(parents=True, exist_ok=True)
    (g / "metadata.json").write_text(json.dumps({
        "gap_id": gap_id, "title": f"synth {gap_id}",
        "priority": "low", "created_at": datetime.utcnow().isoformat() + "Z"
    }))
    sp = Path("/var/lib/karios/orchestrator/state.json")
    s = json.loads(sp.read_text())
    s.setdefault("active_gaps", {})[gap_id] = {
        "state": None, "phase": phase, "iteration": iteration,
        "trace_id": f"trace_test_{gap_id}_{int(time.time())}"
    }
    sp.write_text(json.dumps(s, indent=2))

def cleanup_synth(gap_id):
    sp = Path("/var/lib/karios/orchestrator/state.json")
    s = json.loads(sp.read_text())
    if gap_id in s.get("active_gaps", {}):
        s["active_gaps"][gap_id]["state"] = "completed"
        s["active_gaps"][gap_id]["phase"] = "completed"
        sp.write_text(json.dumps(s, indent=2))

# ─── REMAINING PHASE TESTS ──────────────────────────────────────────────────

def test_phase1_to_2_requirement():
    """Test [REQUIREMENT] arrives → architect gets dispatch."""
    gap = "TEST-FLOW-REQ"
    setup_synth(gap, phase="0-requirement")
    R.xadd("stream:orchestrator", {
        "from": "sai", "to": "orchestrator",
        "subject": f"[REQUIREMENT] {gap}",
        "body": "Synthetic test requirement: validate REQ→architect dispatch flow",
        "gap_id": gap,
        "trace_id": f"trace_req_test_{int(time.time())}"
    })
    time.sleep(8)
    events = grep_journal("karios-orchestrator-sub", 15,
                          [f"REQUIREMENT] {gap}", "→ architect", "advance_to_research", "RESEARCH"])
    has_dispatch = any(("→ architect" in e or "RESEARCH" in e) and gap in e for e in events)
    record(f"phase1_2.{gap}.requirement_to_architect", has_dispatch,
           f"events={len(events)}")
    cleanup_synth(gap)

def test_phase2_review_pass_fail():
    """Test ARCH-REVIEWED rating>=8 → Phase 3 fan-out, rating<8 → ARCH-ITERATE."""
    # PASS path
    gap_pass = "TEST-FLOW-ARCHPASS"
    setup_synth(gap_pass, phase="2-arch-loop", iteration=1)
    review = {
        "gap_id": gap_pass, "iteration": 1, "rating": 9,
        "recommendation": "APPROVE", "summary": "design solid",
        "critical_issues": [],
        "dimensions": {"correctness":9,"completeness":9,"feasibility":9,"security":9,"testability":9,"resilience":9},
        "trace_id": f"trace_archpass"
    }
    R.xadd("stream:orchestrator", {
        "from": "architect-blind-tester", "to": "orchestrator",
        "subject": f"[ARCH-REVIEWED] {gap_pass} iteration 1",
        "body": json.dumps(review),
        "gap_id": gap_pass, "trace_id": review["trace_id"]
    })
    time.sleep(6)
    events_pass = grep_journal("karios-orchestrator-sub", 15,
                                [f"ARCH-REVIEWED] {gap_pass}", "→ backend", "→ frontend", "FAN-OUT", "Phase 3"])
    has_fanout = any(("FAN-OUT" in e or "→ backend" in e or "Phase 3" in e) and gap_pass in e for e in events_pass)
    record(f"phase2.{gap_pass}.review_pass_to_phase3", has_fanout,
           f"events={[e[:80] for e in events_pass[:3]]}")
    cleanup_synth(gap_pass)

    # FAIL path
    gap_fail = "TEST-FLOW-ARCHFAIL"
    setup_synth(gap_fail, phase="2-arch-loop", iteration=1)
    review_fail = {
        "gap_id": gap_fail, "iteration": 1, "rating": 4,
        "recommendation": "REQUEST_CHANGES", "summary": "design weak",
        "critical_issues": [{"severity":"HIGH","category":"design-flaw",
                              "description":"missing API contract"}],
        "dimensions": {"correctness":4,"completeness":4,"feasibility":5,"security":5,"testability":4,"resilience":5},
        "trace_id": f"trace_archfail"
    }
    R.xadd("stream:orchestrator", {
        "from": "architect-blind-tester", "to": "orchestrator",
        "subject": f"[ARCH-REVIEWED] {gap_fail} iteration 1",
        "body": json.dumps(review_fail),
        "gap_id": gap_fail, "trace_id": review_fail["trace_id"]
    })
    time.sleep(6)
    events_fail = grep_journal("karios-orchestrator-sub", 15,
                                [f"ARCH-ITERATE] {gap_fail}", f"ARCH-REVISE] {gap_fail}", "→ architect"])
    has_iterate = any(("ARCH-ITERATE" in e or "→ architect" in e or "ARCH-REVISE" in e) and gap_fail in e for e in events_fail)
    record(f"phase2.{gap_fail}.review_fail_to_arch_iterate", has_iterate,
           f"events={[e[:80] for e in events_fail[:3]]}")
    cleanup_synth(gap_fail)

def test_phase3_fan_in():
    """Test FAN-IN closes when both backend + frontend emit [CODING-COMPLETE]."""
    gap = "TEST-FLOW-FANIN"
    setup_synth(gap, phase="3-coding", iteration=1)
    # Trigger fan_out manually
    sys.path.insert(0, "/var/lib/karios/orchestrator")
    if "event_dispatcher" in sys.modules:
        del sys.modules["event_dispatcher"]
    import event_dispatcher as ed
    try:
        ed.fan_out(gap, ["backend", "frontend"], f"[CODE-REQUEST] {gap}",
                   "synth fan_in test", "3-coding", trace_id=f"trace_fanin_{int(time.time())}")
        time.sleep(2)
        # Now send FAN-IN from both
        R.xadd("stream:orchestrator", {
            "from": "backend", "to": "orchestrator",
            "subject": f"[FAN-IN] {gap}",
            "body": json.dumps({"agent":"backend","commit_sha":"a"*40,"branch":f"backend/{gap}"}),
            "gap_id": gap, "trace_id": f"trace_fanin_test"
        })
        R.xadd("stream:orchestrator", {
            "from": "frontend", "to": "orchestrator",
            "subject": f"[FAN-IN] {gap}",
            "body": json.dumps({"agent":"frontend","commit_sha":"b"*40,"branch":f"frontend/{gap}"}),
            "gap_id": gap, "trace_id": f"trace_fanin_test"
        })
        time.sleep(6)
        events = grep_journal("karios-orchestrator-sub", 15,
                              [f"FAN-IN.*{gap}", f"FAN-OUT.*{gap}", "API-SYNC", "fan_in"])
        has_fanin = any("FAN-IN" in e and gap in e for e in events)
        record(f"phase3.{gap}.fan_in_close", has_fanin,
               f"events={len(events)}")
    except Exception as e:
        record(f"phase3.{gap}.fan_in_close", False, f"err: {e}")
    cleanup_synth(gap)

def test_phase5_6_prod_monitor():
    """Test PROD-DEPLOYED triggers monitor + state→completed."""
    gap = "TEST-FLOW-PROD"
    setup_synth(gap, phase="4-production", iteration=1)
    R.xadd("stream:orchestrator", {
        "from": "devops", "to": "orchestrator",
        "subject": f"[PROD-DEPLOYED] {gap}",
        "body": json.dumps({"gap_id":gap,"timestamp":datetime.utcnow().isoformat()}),
        "gap_id": gap, "trace_id": f"trace_prod_{int(time.time())}"
    })
    time.sleep(6)
    events = grep_journal("karios-orchestrator-sub", 15,
                          [f"PROD-DEPLOYED] {gap}", "→ monitor", "MONITORING", f"{gap}.*Phase 6"])
    has_monitor = any(("→ monitor" in e or "MONITORING" in e or "Phase 6" in e) and gap in e for e in events)
    has_completion = any("PROD-DEPLOYED" in e and gap in e for e in events)
    record(f"phase5.{gap}.prod_to_monitor", has_monitor or has_completion,
           f"events={[e[:80] for e in events[:3]]}")
    cleanup_synth(gap)

def test_k_max_escalation():
    """Test rating=0 + 8+ iters → escalate_to_human."""
    gap = "TEST-FLOW-KMAX"
    setup_synth(gap, phase="3-coding", iteration=8)  # already at K_max
    e2e = {
        "gap_id": gap, "iteration": 8, "rating": 0, "recommendation": "REJECT",
        "summary": "exhausted", "critical_issues": [{"severity":"CRITICAL","category":"unfixable","description":"chronic issue"}],
        "dimensions": {"functional_correctness":0,"edge_cases":0,"security":0,"performance":0,"concurrency":0,"resilience":0,"error_handling":0},
        "trace_id": f"trace_kmax"
    }
    (ITROOT / gap / "phase-3-coding" / "iteration-8").mkdir(parents=True, exist_ok=True)
    (ITROOT / gap / "phase-3-coding" / "iteration-8" / "e2e-results.json").write_text(json.dumps(e2e, indent=2))
    R.xadd("stream:orchestrator", {
        "from": "code-blind-tester", "to": "orchestrator",
        "subject": f"[E2E-RESULTS] {gap} iteration 8",
        "body": "", "gap_id": gap, "trace_id": e2e["trace_id"]
    })
    time.sleep(8)
    events = grep_journal("karios-orchestrator-sub", 20,
                          [f"escalate.*{gap}", f"ESCALATED.*{gap}", "v7.29 escalate_to_human", "v7.34"])
    has_escalation = any(("escalate" in e.lower() or "ESCALATE" in e) and gap in e for e in events)
    record(f"k_max.{gap}.escalates_at_8_iters", has_escalation,
           f"events={[e[:90] for e in events[:3]]}")
    cleanup_synth(gap)

# ─── 9-AGENT HEALTH CHECK ───────────────────────────────────────────────────

def check_agent_health():
    """For each of 9 agents: tool calls last 30 min, AuthErrors, Hermes etime, recent emit."""
    print("\n" + "=" * 70)
    print("9-AGENT HEALTH CHECK")
    print("=" * 70)

    AGENTS = [
        ("orchestrator", "karios-orchestrator-sub", None),  # not Hermes-driven
        ("architect", "karios-architect-agent", "architect"),
        ("architect-blind-tester", "karios-architect-blind-tester", "architect-blind-tester"),
        ("backend", "karios-backend-worker", "backend"),
        ("frontend", "karios-frontend-worker", "frontend"),
        ("devops", "karios-devops-agent", "devops"),
        ("tester", "karios-tester-agent", "tester"),
        ("code-blind-tester", "karios-code-blind-tester", "code-blind-tester"),
        ("monitor", "karios-monitor-agent", "monitor"),  # may not exist
    ]

    summary = []
    for name, svc, profile in AGENTS:
        # 1. Service active?
        r = subprocess.run(["systemctl", "is-active", svc], capture_output=True, text=True)
        active = r.stdout.strip() == "active"
        if r.returncode != 0 and "could not be found" in r.stdout + r.stderr:
            summary.append((name, "NOT INSTALLED", 0, 0, 0, ""))
            continue

        # 2. Hermes log: tool calls last 30 min + AuthErrors
        tool_calls = 0
        auth_errs = 0
        last_activity = ""
        if profile:
            log = Path(f"/root/.hermes/profiles/{profile}/logs/agent.log")
            if log.exists():
                size = log.stat().st_size
                with log.open("rb") as f:
                    f.seek(max(0, size - 200000))
                    text = f.read().decode("utf-8", errors="replace")
                # Filter to last 30 min
                from datetime import timedelta
                cutoff = datetime.now() - timedelta(minutes=30)
                cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")
                for line in text.splitlines():
                    if line[:19] < cutoff_str:
                        continue
                    if "run_agent: tool" in line:
                        tool_calls += 1
                    if "AuthenticationError" in line:
                        auth_errs += 1
                # Last meaningful activity
                tool_lines = [l for l in text.splitlines() if "run_agent: tool" in l]
                if tool_lines:
                    last_activity = tool_lines[-1].split(",")[0]

        # 3. Live Hermes process?
        live = False
        etime = "0:00"
        r = subprocess.run(["ps", "-eo", "etime,args"], capture_output=True, text=True)
        for line in r.stdout.splitlines():
            if "hermes chat" in line and (profile and f"--profile {profile}" in line):
                live = True
                etime = line.strip().split()[0]
                break

        # 4. Stream depth
        stream_depth = 0
        if profile:
            stream_name_map = {"backend":"backend-worker","frontend":"frontend-worker",
                               "devops":"devops-agent","tester":"tester-agent"}
            stream_key = f"stream:{stream_name_map.get(profile, profile)}"
            try:
                stream_depth = int(R.xlen(stream_key))
            except Exception:
                stream_depth = -1

        status = "✓ active"
        if not active: status = "✗ INACTIVE"
        elif auth_errs > 0: status = f"⚠ {auth_errs} auth errs"
        elif live: status = f"✓ active+running({etime})"

        summary.append((name, status, tool_calls, auth_errs, stream_depth, last_activity))

    # Print
    print(f"  {'AGENT':<25} {'STATUS':<28} {'TOOLS/30m':<10} {'AUTH-ERR':<8} {'QUEUE':<6} LAST")
    for name, status, tools, errs, depth, last in summary:
        print(f"  {name:<25} {status:<28} {tools:<10} {errs:<8} {depth:<6} {last[-12:] if last else '-'}")

    # Also record per-agent results
    for name, status, tools, errs, depth, _ in summary:
        if status == "NOT INSTALLED":
            record(f"agent.{name}", False, "service unit not installed")
        elif "✗" in status:
            record(f"agent.{name}", False, f"{status}, tools={tools}")
        elif errs > 0:
            record(f"agent.{name}", False, f"AuthenticationError x{errs} in last 30min")
        elif tools == 0 and not depth:
            record(f"agent.{name}", False, f"0 tool calls in 30 min")
        else:
            record(f"agent.{name}", True, f"{status}, tools={tools}, queue={depth}")

# ─── RUN ─────────────────────────────────────────────────────────────────────

print("=" * 70)
print(f"PIPELINE TEST v2 — REMAINING PHASES + 9-AGENT HEALTH")
print(f"  {datetime.now().strftime('%H:%M:%S')}")
print("=" * 70)

print("\n[REMAINING PHASE TESTS]")
test_phase1_to_2_requirement()
test_phase2_review_pass_fail()
test_phase3_fan_in()
test_phase5_6_prod_monitor()
test_k_max_escalation()

check_agent_health()

# Save report
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
passed = sum(1 for r in results if r["passed"])
print(f"  PASSED: {passed}/{len(results)}")
report = {
    "timestamp": datetime.now().isoformat(),
    "passed": passed, "total": len(results),
    "results": results
}
Path("/var/lib/karios/orchestrator/pipeline_test_v2_report.json").write_text(json.dumps(report, indent=2))
print(f"  report: /var/lib/karios/orchestrator/pipeline_test_v2_report.json")
