---
type: bug
created: 2026-04-19T06:58:23.112054+00:00
agent: system
severity: HIGH
tags: ["bug", "system", "high"]
---

# Bug: Watchdog detected orchestrator DOWN for 23 minutes but Telegram alert never fired

## Severity
HIGH

## Reproduction Steps
1. Orchestrator deadlocked at 02:05:17 (block=0 GIL hang)
2. Watchdog correctly logged DOWN every 60s starting 02:05:30
3. Telegram should fire at >5min DOWN per CRITICAL_AGE=300s
4. User reports no Telegram message received in that window

## Expected
Telegram alert at minute 5 of orchestrator silence

## Actual
No Telegram alert; only journal stderr lines
