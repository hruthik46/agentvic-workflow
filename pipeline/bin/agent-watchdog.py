#!/usr/bin/env python3
"""
agent-watchdog v6.0 — Monitor all 9 agent heartbeats with two-tier probes.

Runs as a systemd service. Checks every 60 seconds.

Improvements over v5:
  - check_process() actually tries fallback patterns (was returning early on first miss)
  - 9 agents (added architect-blind-tester, code-blind-tester)
  - Two-tier probes: liveness (process+heartbeat) + readiness (stream advanced or queue moved)
  - Telegram dedup keyed on agent name (not status string) — one alert per DOWN transition
  - Telegram alerts loud on send failure; secrets read from /etc/karios/secrets.env
  - DOWN/UP transition events also written to monitor inbox

Usage:
  agent-watchdog              # Run once
  agent-watchdog --daemon      # Run continuously (60s loop)
"""

import os
import sys
import json
import time
import subprocess
from datetime import datetime, timezone
from pathlib import Path

HEARTBEAT_DIR = Path("/var/lib/karios/heartbeat")
COORDINATION = Path("/var/lib/karios/coordination")
STATE_FILE = COORDINATION / "state.json"
INBOX_DIR = Path("/var/lib/karios/agent-msg/inbox")
ALERT_MARKER = COORDINATION / "last_alerted_agents.json"

# All 9 agents in v6.0 pipeline
AGENTS = [
    "orchestrator",
    "architect",
    "backend",
    "frontend",
    "devops",
    "tester",
    "monitor",
    "architect-blind-tester",
    "code-blind-tester",
]

MAX_AGE = 120         # liveness threshold
CRITICAL_AGE = 300    # Telegram-alert threshold
READINESS_AGE = 600   # Stream-progress threshold (semantic readiness)

# Process patterns — substring matches via pgrep -f
PROCESS_NAMES = {
    "orchestrator":           ["event_dispatcher.py"],
    "architect":              ["agent-worker architect"],
    "backend":                ["agent-worker backend"],
    "frontend":               ["agent-worker frontend"],
    "devops":                 ["agent-worker devops"],
    "tester":                 ["agent-worker tester"],
    "monitor":                ["agent-worker monitor"],
    "architect-blind-tester": ["agent-worker architect-blind-tester"],
    "code-blind-tester":      ["agent-worker code-blind-tester"],
}

# Stream key per agent (for semantic-readiness probe)
STREAM_KEYS = {
    "orchestrator":           "stream:orchestrator",
    "architect":              "stream:architect",
    "backend":                "stream:backend",
    "frontend":               "stream:frontend-worker",
    "devops":                 "stream:devops-agent",
    "tester":                 "stream:tester-agent",
    "monitor":                "stream:monitor",
    "architect-blind-tester": "stream:architect-blind-tester",
    "code-blind-tester":      "stream:code-blind-tester",
}

# Secrets — env first, fallback to /etc/karios/secrets.env, fallback to defaults (dev only)
def _load_secrets():
    env_file = Path("/etc/karios/secrets.env")
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

_load_secrets()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
REDIS_HOST = os.environ.get("REDIS_HOST", "192.168.118.202")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_USER = os.environ.get("REDIS_USER", "karios_admin")
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "")


def now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def load_json(path):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return {}


def save_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2))


def telegram_alert(message: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[WATCHDOG] Telegram skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set", file=sys.stderr)
        return False
    try:
        import urllib.request
        import urllib.parse
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": TELEGRAM_CHAT_ID, "text": message}).encode()
        req = urllib.request.Request(url, data=data)
        resp = urllib.request.urlopen(req, timeout=10)
        body = resp.read().decode("utf-8", errors="replace")
        if '"ok":true' in body:
            return True
        print(f"[WATCHDOG] Telegram returned non-ok: {body[:200]}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[WATCHDOG] Telegram FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        return False


def check_process(agent: str) -> bool:
    """Check if any process matching the agent's pattern is running."""
    patterns = PROCESS_NAMES.get(agent, [agent])
    for p in patterns:
        try:
            result = subprocess.run(
                ["pgrep", "-f", p],
                capture_output=True, timeout=5
            )
            if result.returncode == 0:
                return True
        except Exception:
            continue
    return False


def check_heartbeat_age(agent: str) -> int:
    """Return age in seconds of the agent's heartbeat file. Returns -1 if missing/bad."""
    beat_file = HEARTBEAT_DIR / f"{agent}.beat"
    if not beat_file.exists():
        return -1
    try:
        ts = int(beat_file.read_text().strip())
        return now_ts() - ts
    except Exception:
        return -1


def check_stream_progress(agent: str) -> str:
    """Semantic readiness — check stream/consumer state. Returns short status string."""
    stream = STREAM_KEYS.get(agent)
    if not stream:
        return "no-stream-config"
    try:
        import redis
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, username=REDIS_USER,
                        password=REDIS_PASSWORD, decode_responses=True,
                        socket_timeout=5, socket_connect_timeout=5)
        try:
            length = r.xlen(stream)
        except redis.ResponseError:
            length = 0
        # Track length over time to detect "queue grew but didn't shrink"
        marker = COORDINATION / "stream_progress.json"
        prev = load_json(str(marker)) or {}
        prev_len = prev.get(agent, {}).get("length", 0)
        prev_ts = prev.get(agent, {}).get("ts", 0)
        prev[agent] = {"length": length, "ts": now_ts()}
        save_json(str(marker), prev)
        if length == 0:
            return f"idle (len=0)"
        elif length > prev_len and (now_ts() - prev_ts) > READINESS_AGE:
            return f"STUCK (len {prev_len}→{length}, no progress for {READINESS_AGE}s)"
        return f"active (len={length})"
    except Exception as e:
        return f"redis-err: {type(e).__name__}"


def check_agent(agent: str) -> dict:
    """Returns {alive, ready, status_msg, age, process, stream_status}"""
    process_ok = check_process(agent)
    age = check_heartbeat_age(agent)
    stream_status = check_stream_progress(agent)

    # Liveness: process exists AND heartbeat fresh (or process exists and we'll wait for first beat)
    if not process_ok:
        if age >= 0 and age <= MAX_AGE:
            # Heartbeat fresh but no process — odd. Trust the heartbeat.
            alive = True
            status = f"alive-via-beat ({age}s)"
        else:
            alive = False
            status = f"DOWN (no process, beat age={age}s)" if age >= 0 else "DOWN (no process, no beat)"
    else:
        # Process running. Heartbeat must be fresh, OR agent must be processing actual work.
        if age < 0:
            alive = True
            status = "alive (process up, no beat yet)"
        elif age <= MAX_AGE:
            alive = True
            status = f"alive ({age}s)"
        else:
            # Process up but heartbeat stale — likely deadlocked (the v5.4 GIL bug pattern)
            alive = False
            status = f"DEADLOCK? (process up, beat age={age}s) stream={stream_status}"

    return {
        "alive": alive,
        "ready": alive and "STUCK" not in stream_status,
        "status_msg": status,
        "age": age,
        "process": process_ok,
        "stream_status": stream_status,
    }


def write_incident(agent: str, info: dict, is_critical: bool):
    """Write/update an incident in state.json + monitor inbox. Dedup by agent."""
    state = load_json(str(STATE_FILE))
    incidents = state.get("monitor_agent", {}).get("incidents", [])
    existing_idx = None
    for i, e in enumerate(incidents):
        if e.get("agent") == agent and e.get("resolved") is None:
            existing_idx = i
            break
    incident = {
        "id": f"inc_{agent}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        "agent": agent,
        "status": info["status_msg"],
        "is_critical": is_critical,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": "agent_down",
        "stream_status": info.get("stream_status", "?"),
        "process_running": info.get("process", False),
        "heartbeat_age_s": info.get("age", -1),
    }
    if existing_idx is not None:
        incidents[existing_idx].update(incident)
        incidents.insert(0, incidents.pop(existing_idx))
    else:
        incidents.insert(0, incident)
    state.setdefault("monitor_agent", {})["incidents"] = incidents[:50]
    state["monitor_agent"]["last_health_check"] = datetime.now(timezone.utc).isoformat()
    save_json(str(STATE_FILE), state)

    # Monitor inbox
    monitor_inbox = INBOX_DIR / "monitor"
    monitor_inbox.mkdir(parents=True, exist_ok=True)
    pid_str = incident["id"]
    packet = {
        "id": pid_str,
        "type": "alert",
        "from": "watchdog",
        "to": "monitor",
        "status": "pending",
        "priority": "high" if is_critical else "normal",
        "created_at": incident["timestamp"],
        "message": f"AGENT DOWN: {agent} — {info['status_msg']}",
        "incident": incident,
        "metadata": {"packet_version": "1.0", "protocol": "agent-comm-v1"},
    }
    (monitor_inbox / f"{pid_str}.json").write_text(json.dumps(packet, indent=2))


def resolve_incidents(agent: str):
    """Mark all unresolved incidents for an agent as resolved when it comes back up."""
    state = load_json(str(STATE_FILE))
    incidents = state.get("monitor_agent", {}).get("incidents", [])
    changed = False
    for e in incidents:
        if e.get("agent") == agent and e.get("resolved") is None:
            e["resolved"] = datetime.now(timezone.utc).isoformat()
            changed = True
    if changed:
        save_json(str(STATE_FILE), state)


def run_check():
    """Run one check of all agents."""
    results = {}
    down_agents = []  # agents currently DOWN
    for agent in AGENTS:
        info = check_agent(agent)
        results[agent] = info
        if not info["alive"]:
            is_critical = info["age"] > CRITICAL_AGE if info["age"] > 0 else True
            write_incident(agent, info, is_critical=is_critical)
            down_agents.append(agent)
        else:
            resolve_incidents(agent)

    # Print summary
    ts_iso = datetime.now(timezone.utc).isoformat()[:19]
    alive_count = sum(1 for r in results.values() if r["alive"])
    print(f"[{ts_iso}] Agents: {alive_count}/{len(AGENTS)} alive")
    for agent, info in results.items():
        icon = "✓" if info["alive"] else "✗"
        ready_icon = "" if info.get("ready", True) else " [NOT-READY]"
        print(f"  {icon} {agent:25s} {info['status_msg']}{ready_icon}")

    # Telegram dedup — keyed on AGENT NAME only (not status string)
    last = load_json(str(ALERT_MARKER))
    last_alerted = set(last.get("agents", []))
    now_down = set(down_agents)
    newly_down = now_down - last_alerted
    newly_up = last_alerted - now_down

    if newly_down:
        msg_lines = [f"  • {a}: {results[a]['status_msg']}" for a in sorted(newly_down)]
        ok = telegram_alert("[WATCHDOG] Agent(s) DOWN:\n" + "\n".join(msg_lines))
        print(f"[WATCHDOG] Telegram DOWN-alert sent={ok} for {sorted(newly_down)}")
    if newly_up:
        msg = "[WATCHDOG] Agent(s) recovered:\n" + "\n".join(f"  • {a}" for a in sorted(newly_up))
        ok = telegram_alert(msg)
        print(f"[WATCHDOG] Telegram UP-alert sent={ok} for {sorted(newly_up)}")

    save_json(str(ALERT_MARKER), {"agents": sorted(now_down), "ts": now_ts()})
    return results


def main():
    if "--daemon" in sys.argv:
        print("[WATCHDOG v6.0] daemon — checking every 60s")
        while True:
            try:
                run_check()
            except Exception as e:
                print(f"[WATCHDOG] check loop error: {type(e).__name__}: {e}", file=sys.stderr)
            time.sleep(60)
    elif "--test-telegram" in sys.argv:
        ok = telegram_alert("[WATCHDOG] test ping from agent-watchdog v6.0")
        print(f"telegram test: ok={ok}")
        sys.exit(0 if ok else 1)
    else:
        run_check()


if __name__ == "__main__":
    main()
