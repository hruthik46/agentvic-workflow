# v5.0 Infrastructure Bug Fixes

**Date:** 2026-04-18
**Author:** Hermes Agent (session)
**Status:** ✅ Live — 3 of 5 bugs fixed; 2 pending (Redis AUTH TLS, Token Budgets)

---

## Summary

The AB-Tester pipeline (ARCH-IT-008) reached Phase 3 fan-out dispatch but both agents went IDLE immediately with `coding_complete=true` — they never did any work. Root cause analysis identified 5 v4.0 bugs. 3 are now fixed in production.

---

## Bugs Fixed

### Bug 1: RECOVER Handler Hardcoded Phase ✅

**File:** `/usr/local/bin/agent-worker` (line 320)

**Root cause:** `if "[RECOVER]" in subject` was grouped with `[RESEARCH]`, hardcoding `phase = "1-research"` regardless of what phase the gap was actually in.

**Before:**
```python
if "[RESEARCH]" in subject or "[RECOVER]" in subject:
    phase = "1-research"
```

**After:** `[RECOVER]` gets its own branch that parses phase from message body:
- `"was in research"` → `"1-research"`
- `"was in arch"` → `"2-arch-loop"`
- `"was in coding"` → `"3-coding"`
- Regex fallback: extracts raw phase name from body
- Subject-context fallback if body parsing fails

---

### Bug 2: STALLED Loop No Backoff ✅

**File:** `/var/lib/karios/orchestrator/event_dispatcher.py` (main loop)

**Root cause:** `check_stalled_gaps()` ran every 5s loop iteration. Every stalled gap triggered Telegram + NUDGE every single tick. With 5 stalled gaps: 5 × 12 ticks/min = 60 Telegram msgs/minute.

**Fix:** Exponential backoff with gap-state tracking:
```python
STALLED_BACKOFF = [5, 10, 20, 40, 60]  # seconds; cap at 60s

# Gap state now tracks:
gap["nudge_count"]    # how many nudges sent
gap["last_nudge_ts"]  # when last nudge was sent

backoff_idx = min(nudge_count, len(STALLED_BACKOFF) - 1)
backoff_seconds = STALLED_BACKOFF[backoff_idx]

# Telegram throttled to every 3rd nudge (not every tick)
if nudge_count % 3 == 0:
    telegram_alert(...)
```

---

### Bug 3: Stale Redis Consumer Entries ✅

**Files:** New — `/usr/local/bin/consumer-health-monitor.py`, `/etc/systemd/system/consumer-health-monitor.{service,timer}`

**Root cause:** When an agent dies mid-work, its messages sit stuck in Redis Streams PEL (Pending Entries List) with no delivery attempt. New instances of the same agent get different consumer names, so those stale entries are never reclaimed.

**Fix:** New systemd timer runs `consumer-health-monitor.py` every 30s:
- Calls `XPENDING` to find entries idle > 60s
- Calls `XCLAIM` to transfer ownership to a fresh recovery consumer
- Also detects dead consumers (idle > 5min) and logs them

**API discovery:** `r.xpending()` returns a **dict** in this redis-py version:
```python
# This redis-py returns dict, NOT tuple:
{'pending': 0, 'min': None, 'max': None, 'consumers': [...]}

# NOT:
(min_id, max_id, count, [(id, consumer, idle_ms, delivered)])
```

Timer enabled: `systemctl enable --now consumer-health-monitor.timer`

---

### Bug 5: Hermes Silent Failure Detection ✅

**File:** `/usr/local/bin/agent-worker` (`process_message()`)

**Root cause:** `run_hermes()` returned raw subprocess output with zero validation. Agents treated empty or error output as success — `coding_complete=true` even when Hermes crashed silently.

**Fix:** Output validation after every Hermes call:
```python
HERMES_ERROR_INDICATORS = [
    "ERROR: Hermes not found",
    "ERROR: subprocess",
    "Traceback (most recent call last)",
    "FileNotFoundError",
    "No such file or directory",
    "hermes",
    "PermissionError",
    "timeout",
]
is_hermes_error = any(err in result for err in HERMES_ERROR_INDICATORS)
min_output_chars = 20
is_meaningful_output = len(result.strip()) >= min_output_chars and not is_hermes_error

if is_hermes_error or not is_meaningful_output:
    status = "error"
    coding_complete = False
else:
    status = "completed"
    coding_complete = True
```

---

## Bugs NOT YET Fixed (Architecture Designed, Deployment Pending)

### Bug 4: Redis AUTH + TLS

**Status:** Redis already has AUTH enabled (`karios_admin` / `<REDACTED-REDIS-PASSWORD>`)

**Pending:** TLS via stunnel. Full rollout in 5-phase deployment (see `deployment-plan.md` in iteration-tracker).

**Note:** The design doc said "Redis no AUTH" — this was wrong. AUTH was already active. The pending work is adding TLS encryption on top.

### Bug 6: Token Budgets

**Status:** Design documented in architecture.md. Implementation pending.

---

## Key Finding: PROFILE_MAP Was NOT Wrong

The v4.0 design doc claimed Bug 5 was "PROFILE_MAP maps `backend` → `backend-worker` but profile is `backend`". This was **incorrect for the current codebase**.

Current `agent-worker` PROFILE_MAP:
```python
PROFILE_MAP = {
    "architect-blind-tester": "architect-blind-tester",
    "code-blind-tester": "code-blind-tester",
    "architect": "architect",
    "backend": "backend",        # Correct — matches profile dir name
    "frontend": "frontend",      # Correct
    "devops": "devops",          # Correct
    "tester": "tester",          # Correct
    "monitor": "monitor",          # Correct
    "orchestrator": "orchestrator",  # Correct
}
```

Profile directories that exist:
- `/root/.hermes/profiles/backend/` (correct — matches)
- `/root/.hermes/profiles/backend-worker.hermes` (hermes file, not a profile dir)

**Actual Bug 5** was Hermes silent failure (see above), not PROFILE_MAP.

---

## Architecture Docs Location

All v5.0 architecture iteration docs:
```
/var/lib/karios/iteration-tracker/ARCH-IT-009/phase-2-arch-loop/
  iteration-1/  (iteration 1 — 7/10)
  iteration-2/  (iteration 2 — 10/10, gate passed)
    architecture.md
    edge-cases.md
    test-cases.md
    api-contract.md
    deployment-plan.md
    review.json
```

Also at:
- `/var/lib/karios/coordination/ab-tester-v4-design.md`
- `/root/karios/multi-agent/AB-TESTER-V4-DESIGN.md`
