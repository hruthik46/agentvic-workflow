"""v7.18 patch — zombie-Hermes reaper for agent-worker.

Inserts at top of main() before init_stream_consumer_group(). On startup:
  - Find all `hermes` python processes whose argv contains `--profile <AGENT>`
  - Skip the ones whose PPID matches the current agent-worker PID (active children)
  - SIGTERM the rest (orphaned from prior dispatcher restarts)
  - Wait 3s, then SIGKILL any survivors

Idempotent — re-running is a no-op when no zombies present.
"""
import os
import signal
import subprocess
import sys
import time


def reap_zombie_hermes_for_profile(agent: str) -> int:
    """Kill orphaned Hermes processes for this profile that no live agent-worker owns.

    Returns count of processes reaped.
    """
    my_pid = os.getpid()
    my_ppid = os.getppid()
    reaped = 0
    try:
        r = subprocess.run(
            ["ps", "-eo", "pid,ppid,etime,cmd"],
            capture_output=True, text=True, timeout=5
        )
        candidates = []
        for line in r.stdout.splitlines()[1:]:
            parts = line.strip().split(None, 3)
            if len(parts) < 4:
                continue
            pid_s, ppid_s, _etime, cmd = parts
            try:
                pid = int(pid_s)
                ppid = int(ppid_s)
            except ValueError:
                continue
            if pid == my_pid:
                continue
            if "hermes" not in cmd:
                continue
            if f"--profile {agent}" not in cmd and f"--profile={agent}" not in cmd:
                continue
            # Owned by current process tree — leave alone
            if ppid == my_pid or ppid == my_ppid:
                continue
            # Owned by ANY live agent-worker for this profile? (sibling worker)
            # Conservative: only reap if PPID is init (1) or already-dead PID.
            if ppid != 1:
                try:
                    os.kill(ppid, 0)  # check parent alive
                    continue  # parent alive — not orphan
                except ProcessLookupError:
                    pass  # parent dead — orphan, reap
            candidates.append(pid)

        for pid in candidates:
            try:
                os.kill(pid, signal.SIGTERM)
                print(f"[{agent}] zombie-reaper: SIGTERM Hermes PID {pid} (orphaned)")
            except ProcessLookupError:
                continue
            except Exception as e:
                print(f"[{agent}] zombie-reaper: SIGTERM PID {pid} failed: {e}")

        if candidates:
            time.sleep(3)
            for pid in candidates:
                try:
                    os.kill(pid, 0)  # still alive?
                    os.kill(pid, signal.SIGKILL)
                    print(f"[{agent}] zombie-reaper: SIGKILL Hermes PID {pid} (SIGTERM ignored)")
                except ProcessLookupError:
                    pass
                reaped += 1
    except Exception as e:
        print(f"[{agent}] zombie-reaper: failed: {e}")
    return reaped


if __name__ == "__main__":
    # CLI standalone mode for ad-hoc cleanup
    agent = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("HERMES_AGENT", "")
    if not agent:
        print("Usage: zombie_reaper.py <agent_profile_name>")
        sys.exit(1)
    n = reap_zombie_hermes_for_profile(agent)
    print(f"Reaped {n} zombie Hermes process(es) for profile {agent}")
