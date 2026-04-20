---
type: rca
created: 2026-04-19T08:37:22.516636+00:00
agent: system
incident_id: AGENT-WORKER-HERMES-INDICATOR-FP-ROUND-2
severity: HIGH
files_affected: ["/usr/local/bin/agent-worker"]
tags: ["rca", "system", "high"]
---

# RCA: AGENT-WORKER-HERMES-INDICATOR-FP-ROUND-2

## Symptom
After removing the lowercase hermes indicator, code-blind-tester + backend STILL false-positived. Output was 258K-482K chars (real work happened). Indicators like No such file or directory match naturally in long Hermes tool execution logs.

## Root Cause
Indicator search scanned the FULL output (482K chars). Tool execution within Hermes (file probes, etc.) produces these strings naturally.

## Fix
Restrict indicator check to first 500 chars (startup/spawn failure window). Removed loose indicators; kept only spawn-specific ones. If Hermes printed its banner the agent is running — anything after is real work.

## Files Affected
- /usr/local/bin/agent-worker

## Lessons
_none recorded_
