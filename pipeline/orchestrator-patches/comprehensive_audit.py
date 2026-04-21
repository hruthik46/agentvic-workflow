"""Comprehensive audit — find ALL silent failures + architectural gaps."""
import json, subprocess, re, os
from pathlib import Path

print("=" * 75)
print("COMPREHENSIVE PIPELINE AUDIT — silent failures + arch gaps")
print("=" * 75)

issues = []
def report(severity, category, file_line, desc, fix):
    issues.append({"severity": severity, "category": category,
                    "file_line": file_line, "description": desc, "suggested_fix": fix})
    icon = "🔴" if severity == "CRITICAL" else "🟡" if severity == "HIGH" else "⚪"
    print(f"  {icon} [{category}] {file_line}: {desc[:120]}")

# ─── 1. Missing files referenced in prompts/templates ───────────────────────
print("\n[1] MISSING FILES referenced in prompts")
pb = Path("/var/lib/karios/orchestrator/prompt_builder.py").read_text()
ed = Path("/var/lib/karios/orchestrator/event_dispatcher.py").read_text()
referenced_paths = set()
for src in [pb, ed]:
    for m in re.finditer(r"['\"](/(?:root|etc|var|usr|opt)/[\w/.\-]+\.(?:sh|py|yaml|json|md))['\"]", src):
        referenced_paths.add(m.group(1))
for p in referenced_paths:
    if not Path(p).exists() and not any(x in p for x in ["{", "var/lib/karios/iteration", "var/lib/karios/agent-msg"]):
        report("HIGH", "missing-file", p, "Referenced in prompts but file does not exist", f"Create {p} or remove reference")

# ─── 2. Bare except: pass swallowing errors ─────────────────────────────────
print("\n[2] except: pass / silent error swallowing")
for fname in ["/var/lib/karios/orchestrator/event_dispatcher.py", "/usr/local/bin/agent-worker"]:
    text = Path(fname).read_text()
    bare_pass = re.findall(r"except[^:]*:\s*\n\s*pass\b", text)
    if len(bare_pass) > 0:
        report("LOW", "bare-except-pass", fname, f"{len(bare_pass)} silent except: pass blocks", "Audit each: log error or escalate via telegram")

# ─── 3. Hardcoded paths that may not exist on other machines ────────────────
print("\n[3] HARDCODED paths in dispatcher")
hardcoded = re.findall(r"['\"](/root/[\w/.\-]+)['\"]", pb + ed)
unique_hc = sorted(set(hardcoded))[:10]
for p in unique_hc:
    if not Path(p).exists():
        report("MEDIUM", "hardcoded-missing-path", p, "Hardcoded path not present", f"Add existence check or document required state")

# ─── 4. Systemd units referenced but not installed ──────────────────────────
print("\n[4] SYSTEMD units")
expected_units = ["karios-orchestrator-sub", "karios-architect-agent", "karios-architect-blind-tester",
                   "karios-backend-worker", "karios-frontend-worker", "karios-devops-agent",
                   "karios-tester-agent", "karios-code-blind-tester", "karios-monitor-worker"]
for u in expected_units:
    r = subprocess.run(["systemctl", "is-active", u], capture_output=True, text=True, timeout=5)
    if r.stdout.strip() != "active":
        report("HIGH", "systemd-inactive", f"karios-{u}", f"Service {r.stdout.strip()}", f"systemctl start {u}")

# ─── 5. API keys length (truncation check) ──────────────────────────────────
print("\n[5] API KEY truncation check (all 9 profiles)")
key_lens = {}
for cfg in Path("/root/.hermes/profiles").glob("*/config.yaml"):
    text = cfg.read_text()
    m = re.search(r"^\s+api_key:\s+(\S+)\s*$", text, re.MULTILINE)
    if m:
        n = cfg.parent.name
        l = len(m.group(1))
        key_lens[n] = l
        if l < 100:
            report("CRITICAL", "api-key-truncated", str(cfg), f"api_key len={l} (expected 125)", "Replace with full key from working profile")

# ─── 6. Profile config has agent: section ───────────────────────────────────
print("\n[6] PROFILE configs missing agent: section")
for cfg in Path("/root/.hermes/profiles").glob("*/config.yaml"):
    if "agent:" not in cfg.read_text():
        report("HIGH", "missing-agent-section", str(cfg), "No agent: section — tool_use_enforcement defaults to 'auto'", "Add agent: tool_use_enforcement: true")

# ─── 7. Stream backlog (very large = stale) ─────────────────────────────────
print("\n[7] STREAM backlog check")
import redis as _r
R = _r.Redis(host="192.168.118.202", username="karios_admin", password="Adminadmin@123")
for stream in ["stream:backend-worker", "stream:tester-agent", "stream:code-blind-tester",
                "stream:devops-agent", "stream:architect", "stream:architect-blind-tester",
                "stream:frontend-worker", "stream:monitor", "stream:orchestrator"]:
    try:
        n = R.xlen(stream)
        if n > 50:
            report("MEDIUM", "stream-backlog", stream, f"{n} messages — may be stale", "Run XTRIM stream MINID to drop entries >6h old")
    except Exception:
        pass

# ─── 8. Live Hermes process ages (zombies) ──────────────────────────────────
print("\n[8] HERMES process age check (zombies)")
r = subprocess.run(["ps", "-eo", "pid,ppid,etime,args"], capture_output=True, text=True, timeout=5)
for line in r.stdout.splitlines():
    if "hermes chat" in line and "--profile" in line:
        parts = line.strip().split(None, 3)
        try:
            pid, ppid, etime = parts[:3]
            cmd = parts[3]
            profile = "?"
            m = re.search(r"--profile (\S+)", cmd)
            if m: profile = m.group(1)
            # If etime > 30 min, possibly stuck
            if "-" in etime or (":" in etime and etime.count(":") == 2):  # X-HH:MM:SS or HH:MM:SS
                try:
                    if "-" in etime:
                        days, hms = etime.split("-")
                        hours = int(days) * 24 + int(hms.split(":")[0])
                    else:
                        hours = int(etime.split(":")[0])
                    if hours >= 1:
                        report("HIGH", "hermes-stuck", f"pid={pid}", f"Hermes profile={profile} running {etime} (PPID={ppid}) — possibly stuck", "Check if PPID alive; if orphan, SIGTERM")
                except Exception:
                    pass
        except Exception:
            pass

# ─── 9. Stale state.json gaps ───────────────────────────────────────────────
print("\n[9] STATE.JSON stale active gaps")
state = json.loads(Path("/var/lib/karios/orchestrator/state.json").read_text())
import time
for gid, gv in state.get("active_gaps", {}).items():
    if gv.get("state") not in ("completed", "closed", "escalated"):
        # Check last activity (marker file)
        marker = Path(f"/var/lib/karios/agent-memory/{gid}_last_dispatch.ts")
        if marker.exists():
            age_h = (time.time() - marker.stat().st_mtime) / 3600
            if age_h > 6:
                report("LOW", "stale-active-gap", gid, f"No activity for {age_h:.1f}h", "Mark completed if abandoned, or re-trigger")

# ─── 10. Missing required scripts/binaries ──────────────────────────────────
print("\n[10] REQUIRED scripts/binaries")
required = ["/root/deploy-all.sh", "/usr/local/bin/karios-vault", "/usr/local/bin/karios-merge-resolve",
             "/usr/local/bin/karios-contract-test", "/usr/local/bin/karios-eval", "/usr/local/bin/karios-evolve",
             "/usr/local/bin/agent-worker", "/usr/local/bin/agent-heartbeat.py"]
for p in required:
    if not Path(p).exists():
        report("HIGH", "missing-required-binary", p, "Required by pipeline but missing", f"Create or symlink to {p}")

# ─── 11. Karios-migration build status ──────────────────────────────────────
print("\n[11] KARIOS-MIGRATION repo build status")
r = subprocess.run(["bash", "-c", "cd /root/karios-source-code/karios-migration && go build ./... 2>&1"],
                   capture_output=True, text=True, timeout=120)
if r.returncode != 0:
    report("HIGH", "karios-migration-broken-build", "/root/karios-source-code/karios-migration",
           f"go build fails: {r.stdout[:200]}", "Fix build errors")

# ─── 12. Frontend doesnt have Phase 3 work + monitor doesnt do anything ─────
print("\n[12] AGENT INVOLVEMENT — agents that should activate but dont")
for prof in ["frontend", "monitor"]:
    log = Path(f"/root/.hermes/profiles/{prof}/logs/agent.log")
    if log.exists():
        size = log.stat().st_size
        with log.open("rb") as f:
            f.seek(max(0, size - 50000))
            text = f.read().decode("utf-8", errors="replace")
        from datetime import datetime, timedelta
        cutoff = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        recent_tools = sum(1 for l in text.splitlines() if "run_agent: tool" in l and l[:19] > cutoff)
        if recent_tools == 0:
            report("LOW", "agent-idle", prof, f"No tool calls in last hour (may be expected if no work)", "Verify gap routing reaches this agent")

# ─── SUMMARY ────────────────────────────────────────────────────────────────
print("\n" + "=" * 75)
print(f"AUDIT COMPLETE — {len(issues)} issues found")
print("=" * 75)
sev_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
for i in issues:
    sev_counts[i["severity"]] += 1
print(f"  CRITICAL: {sev_counts['CRITICAL']} | HIGH: {sev_counts['HIGH']} | MEDIUM: {sev_counts['MEDIUM']} | LOW: {sev_counts['LOW']}")

# Save report
report_path = Path("/var/lib/karios/orchestrator/comprehensive_audit_report.json")
report_path.write_text(json.dumps(issues, indent=2))
print(f"\n  report: {report_path}")
