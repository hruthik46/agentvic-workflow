---
type: rca
created: 2026-04-19T07:52:07.818645+00:00
agent: system
incident_id: DISPATCHER-STREAM-NAME-MAP-DRIFT
severity: HIGH
files_affected: ["/var/lib/karios/orchestrator/event_dispatcher.py", "/usr/local/bin/agent-worker"]
tags: ["rca", "system", "high"]
---

# RCA: DISPATCHER-STREAM-NAME-MAP-DRIFT

## Symptom
After fan_out fix, backend stream:backend got the message but agent kept reporting empty; frontend same

## Root Cause
agent-worker maps short names to systemd-style stream keys: backend->backend-worker, frontend->frontend-worker, devops->devops-agent, tester->tester-agent. The dispatchers send_to_agent computed stream_key=f"stream:{agent}" which produced stream:backend, but backend reads stream:backend-worker. The same v5.1 RCA fix was applied in agent-worker but the inverse mapping was missing in the dispatcher.

## Fix
Added DISPATCH_STREAM_MAP in send_to_agent mirroring the agent-worker STREAM_NAME_MAP. Drained stuck messages from stream:backend and stream:frontend into the correct -worker / -agent streams.

## Files Affected
- /var/lib/karios/orchestrator/event_dispatcher.py
- /usr/local/bin/agent-worker

## Lessons
_none recorded_
