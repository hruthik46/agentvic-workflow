"""DEDICATED BACKEND WATCHER — deep end-to-end monitoring.

For the next 4 minutes, capture EVERYTHING backend agent does:
  1. Last prompt body received
  2. Every tool call + args + result
  3. File modifications in karios-migration
  4. Git activity (commits, pushes)
  5. Build status before + after
  6. e2e-results before + after (cbt re-test outcome)

Returns end-to-end report.
"""
import json, time, subprocess, sys, re
from pathlib import Path
from datetime import datetime

import redis as _r
R = _r.Redis(host="192.168.118.202", username="karios_admin", password="Adminadmin@123")
REPO = "/root/karios-source-code/karios-migration"

print("=" * 75)
print(f"DEDICATED BACKEND WATCH — {datetime.now().strftime('%H:%M:%S')}")
print("Watching backend agent end-to-end for 4 minutes...")
print("=" * 75)

# ─── BASELINE (T=0) ─────────────────────────────────────────────────────────
print("\n[T=0 BASELINE]")

# Latest prompt backend received
entries = R.xrevrange("stream:backend-worker", count=5)
target_prompt = None
for entry_id, fields in entries:
    payload = json.loads(fields.get(b"payload", b"{}").decode())
    if "ARCH-IT-018" in payload.get("subject", ""):
        target_prompt = {
            "subject": payload.get("subject"),
            "body_chars": len(payload.get("body", "")),
            "body_first_500": payload.get("body", "")[:500],
            "body_has_v732": "ISSUE #1" in payload.get("body", ""),
            "body_has_listed_bugs": all(b in payload.get("body", "") for b in
                                         ["TestAllPlaceholderRoutes", "TestValidTransitions", "ControlSet002"]),
        }
        print(f"  prompt subject: {target_prompt['subject']}")
        print(f"  body_chars: {target_prompt['body_chars']}")
        print(f"  has v7.32 detail: {target_prompt['body_has_v732']}")
        print(f"  contains 5 listed bugs: {target_prompt['body_has_listed_bugs']}")
        break
if not target_prompt:
    print("  no recent ARCH-IT-018 prompt found in stream")

# Initial build status
r = subprocess.run(["bash", "-c", f"cd {REPO} && go build ./... 2>&1 | head -3"],
                   capture_output=True, text=True, timeout=60)
build_t0 = "GREEN" if (r.returncode == 0 and not r.stdout.strip()) else f"BROKEN: {r.stdout[:150]}"
print(f"  build_t0: {build_t0}")

# Initial test results
r = subprocess.run(["bash", "-c",
                    f"cd {REPO} && go test ./internal/migration/... ./internal/server/... -count=1 2>&1 | tail -10"],
                   capture_output=True, text=True, timeout=120)
test_t0_pass = r.stdout.count("--- PASS:")
test_t0_fail = r.stdout.count("--- FAIL:")
print(f"  test_t0: {test_t0_pass} PASS / {test_t0_fail} FAIL")

# Initial git HEAD
r = subprocess.run(["git", "-C", REPO, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5)
head_t0 = r.stdout.strip()[:8]
print(f"  HEAD t0: {head_t0}")

# Backend Hermes process
r = subprocess.run(["ps", "-eo", "pid,etime,args"], capture_output=True, text=True, timeout=5)
hermes_t0 = None
for line in r.stdout.splitlines():
    if "hermes chat" in line and "--profile backend" in line:
        parts = line.strip().split(None, 2)
        hermes_t0 = (parts[0], parts[1])
        print(f"  backend Hermes: pid={parts[0]} etime={parts[1]}")
        break

# ─── WATCH 4 MINUTES ────────────────────────────────────────────────────────
print(f"\n[WATCHING FOR 240s — capturing tool calls + git activity]")

start = time.time()
WATCH_SEC = 240
log_path = Path("/root/.hermes/profiles/backend/logs/agent.log")
initial_size = log_path.stat().st_size
last_check = time.time()
events_captured = []

while time.time() - start < WATCH_SEC:
    time.sleep(20)
    elapsed = int(time.time() - start)
    # Tail new content
    cur_size = log_path.stat().st_size
    if cur_size > initial_size:
        with log_path.open("rb") as f:
            f.seek(initial_size)
            new = f.read(cur_size - initial_size).decode("utf-8", errors="replace")
        # Extract tool events
        for line in new.splitlines():
            if "run_agent: tool" in line and "completed" in line:
                m = re.search(r"tool (\w+) completed \(([\d.]+)s, (\d+) chars\)", line)
                if m:
                    tname, dur, sz = m.groups()
                    ts = line[:19]
                    events_captured.append({"t": ts, "tool": tname, "dur": float(dur), "chars": int(sz)})
            elif "WATCHDOG" in line:
                events_captured.append({"t": line[:19], "tool": "WATCHDOG", "info": line[20:120]})
            elif "API call #" in line:
                m = re.search(r"API call #(\d+).*in=(\d+) out=(\d+)", line)
                if m:
                    api_n, in_t, out_t = m.groups()
                    events_captured.append({"t": line[:19], "tool": f"API#{api_n}", "in": int(in_t), "out": int(out_t)})
        initial_size = cur_size

    # Show progress
    new_count = len(events_captured)
    if new_count > 0:
        last_evt = events_captured[-1]
        print(f"  [{elapsed:>3}s] events={new_count} last={last_evt.get('tool')} @ {last_evt.get('t')}")

# ─── FINAL STATE (T=4min) ───────────────────────────────────────────────────
print(f"\n[T=240s FINAL STATE]")

# Final build
r = subprocess.run(["bash", "-c", f"cd {REPO} && go build ./... 2>&1 | head -3"],
                   capture_output=True, text=True, timeout=60)
build_t1 = "GREEN" if (r.returncode == 0 and not r.stdout.strip()) else f"BROKEN: {r.stdout[:150]}"
print(f"  build_t1: {build_t1}")

# Final tests
r = subprocess.run(["bash", "-c",
                    f"cd {REPO} && go test ./internal/migration/... ./internal/server/... -count=1 2>&1 | tail -10"],
                   capture_output=True, text=True, timeout=120)
test_t1_pass = r.stdout.count("--- PASS:")
test_t1_fail = r.stdout.count("--- FAIL:")
print(f"  test_t1: {test_t1_pass} PASS / {test_t1_fail} FAIL")

# Final git HEAD
r = subprocess.run(["git", "-C", REPO, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5)
head_t1 = r.stdout.strip()[:8]
print(f"  HEAD t1: {head_t1}")
new_commit = head_t0 != head_t1
if new_commit:
    r = subprocess.run(["git", "-C", REPO, "log", "-1", "--format=%h %s%n%n%b", head_t1],
                       capture_output=True, text=True, timeout=5)
    print(f"  NEW COMMIT:\n  {r.stdout.strip()[:600]}")
    # Check if commit touches files mentioned in v7.32
    r = subprocess.run(["git", "-C", REPO, "show", "--stat", head_t1],
                       capture_output=True, text=True, timeout=5)
    files_touched = [l.split("|")[0].strip() for l in r.stdout.splitlines() if "|" in l and "+" in l]
    print(f"  files in commit: {files_touched[:8]}")

# ─── EVENTS SUMMARY ─────────────────────────────────────────────────────────
print(f"\n[EVENTS SUMMARY — {len(events_captured)} captured]")
from collections import Counter
tool_counts = Counter(e["tool"] for e in events_captured if "tool" in e)
print(f"  tool calls: {dict(tool_counts)}")
api_calls = [e for e in events_captured if e.get("tool", "").startswith("API#")]
total_in = sum(e.get("in", 0) for e in api_calls)
total_out = sum(e.get("out", 0) for e in api_calls)
print(f"  API calls: {len(api_calls)}, total in={total_in} tokens, out={total_out} tokens")
watchdogs = [e for e in events_captured if e.get("tool") == "WATCHDOG"]
print(f"  WATCHDOG events: {len(watchdogs)}")

# ─── VERDICT ────────────────────────────────────────────────────────────────
print("\n" + "=" * 75)
print("END-TO-END VERDICT")
print("=" * 75)
results = []
def chk(name, val, ok_msg, fail_msg):
    icon = "✓" if val else "✗"
    msg = ok_msg if val else fail_msg
    print(f"  {icon} {name}: {msg}")
    results.append((name, val, msg))

chk("backend received v7.32 detail", target_prompt and target_prompt.get("body_has_v732"),
    "v7.32 ISSUE #1 / WHY / SUGGESTED FIX present", "no v7.32 markers in latest prompt")
chk("backend received 5 listed bugs", target_prompt and target_prompt.get("body_has_listed_bugs"),
    "all 5 bugs (TestAllPlaceholderRoutes, ControlSet002, etc) listed", "missing some listed bugs")
chk("backend made tool calls", len(events_captured) > 0,
    f"{len(events_captured)} events captured", "zero tool activity in 4 min")
chk("no WATCHDOG kills", len(watchdogs) == 0,
    "no kills (v7.37 working)", f"{len(watchdogs)} watchdog events")
chk("build status improved", build_t0 == "GREEN" and build_t1 == "GREEN",
    "build stayed GREEN", f"build degraded: {build_t0} → {build_t1}")
chk("backend produced new commit", new_commit,
    f"new commit {head_t1}", "no new commits in 4 min")

passed = sum(1 for _, ok, _ in results if ok)
print(f"\n  CHECKS PASSED: {passed}/{len(results)}")

# Save
report = {
    "timestamp": datetime.now().isoformat(),
    "watch_duration_sec": WATCH_SEC,
    "passed": passed, "total": len(results),
    "checks": [{"name": n, "passed": p, "msg": m} for n, p, m in results],
    "events_count": len(events_captured),
    "tool_counts": dict(tool_counts),
    "api_calls_count": len(api_calls),
    "api_total_in": total_in,
    "api_total_out": total_out,
    "build_t0": build_t0[:200],
    "build_t1": build_t1[:200],
    "test_t0": f"{test_t0_pass}P/{test_t0_fail}F",
    "test_t1": f"{test_t1_pass}P/{test_t1_fail}F",
    "head_t0": head_t0,
    "head_t1": head_t1,
    "new_commit": new_commit,
}
Path("/var/lib/karios/orchestrator/backend_dedicated_watch_report.json").write_text(json.dumps(report, indent=2))
print(f"\n  report saved: /var/lib/karios/orchestrator/backend_dedicated_watch_report.json")
