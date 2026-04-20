#!/usr/bin/env python3
"""
agent-heartbeat — Write heartbeat for current agent.

Usage:
  agent-heartbeat           # Write heartbeat for HERMES_AGENT env var
  agent-heartbeat <agent>  # Explicit agent name

Writes timestamp to /var/lib/karios/heartbeat/<agent>.beat
Watchdog alerts if heartbeat is older than 120 seconds.
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timezone

HEARTBEAT_DIR = Path("/var/lib/karios/heartbeat")
HEARTBEAT_DIR.mkdir(parents=True, exist_ok=True)

def get_agent() -> str:
    agent = os.environ.get("HERMES_AGENT", "")
    if not agent:
        unit = os.environ.get("SYSTEMD_UNIT", "")
        # karios-backend-worker.service → backend
        if unit.startswith("karios-"):
            agent = unit.replace("karios-", "").replace("-worker", "").replace("-agent", "").replace(".service", "")
        else:
            agent = "unknown"
    return agent

def main():
    agent = sys.argv[1] if len(sys.argv) > 1 else get_agent()
    beat_file = HEARTBEAT_DIR / f"{agent}.beat"
    ts = int(datetime.now(timezone.utc).timestamp())
    beat_file.write_text(str(ts))
    # Also touch Redis for observability
    try:
        import redis
        r = redis.Redis(host="192.168.118.202", port=6379,
                        username="karios_admin",
                        password=os.environ.get("REDIS_PASSWORD", "karios_admin"),
                        decode_responses=True)
        r.setex(f"heartbeat:{agent}", 120, str(ts))
    except Exception:
        pass  # Redis is optional for heartbeat

if __name__ == "__main__":
    main()
