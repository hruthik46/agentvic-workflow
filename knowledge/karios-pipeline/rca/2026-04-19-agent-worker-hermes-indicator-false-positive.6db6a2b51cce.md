---
type: rca
created: 2026-04-19T07:56:19.380989+00:00
agent: system
incident_id: AGENT-WORKER-HERMES-INDICATOR-FALSE-POSITIVE
severity: HIGH
files_affected: ["/usr/local/bin/agent-worker"]
tags: ["rca", "system", "high"]
---

# RCA: AGENT-WORKER-HERMES-INDICATOR-FALSE-POSITIVE

## Symptom
Frontend Hermes finished in 2.5min and was classified [ERROR], its output prevented from reaching FAN-IN. Architect-blind-tester earlier had same issue.

## Root Cause
agent-worker.HERMES_ERROR_INDICATORS contained substring "hermes" (lowercase) which always matches the Hermes Agent banner in stdout ("Hermes Agent v0.9.0"). 100% false-positive rate on every successful Hermes run.

## Fix
Removed bare "hermes" indicator. Made remaining indicators specific ("PermissionError: ", "subprocess.TimeoutExpired").

## Files Affected
- /usr/local/bin/agent-worker

## Lessons
_none recorded_
