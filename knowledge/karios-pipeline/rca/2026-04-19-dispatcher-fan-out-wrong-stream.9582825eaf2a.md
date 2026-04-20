---
type: rca
created: 2026-04-19T07:52:07.787242+00:00
agent: system
incident_id: DISPATCHER-FAN-OUT-WRONG-STREAM
severity: HIGH
files_affected: ["/var/lib/karios/orchestrator/event_dispatcher.py"]
tags: ["rca", "system", "high"]
---

# RCA: DISPATCHER-FAN-OUT-WRONG-STREAM

## Symptom
Architecture APPROVED but backend+frontend never received the FAN-OUT [CODE-REQUEST]; messages looped back to orchestrator stream as Unhandled

## Root Cause
fan_out() called stream_publish() which always writes to STREAM_KEY (=stream:orchestrator) regardless of the to= field. Dispatcher published to its own inbox, not to backend/frontend.

## Fix
Replaced stream_publish() call inside fan_out() with send_to_agent() which correctly XADDs to stream:{agent}.

## Files Affected
- /var/lib/karios/orchestrator/event_dispatcher.py

## Lessons
_none recorded_
