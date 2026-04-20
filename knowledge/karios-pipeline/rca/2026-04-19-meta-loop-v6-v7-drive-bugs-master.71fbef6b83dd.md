---
type: rca
created: 2026-04-19T09:01:44.746538+00:00
agent: system
incident_id: META-LOOP-V6-V7-DRIVE-BUGS-MASTER
severity: HIGH
files_affected: ["/var/lib/karios/orchestrator/event_dispatcher.py"]
tags: ["rca", "system", "high"]
---

# RCA: META-LOOP-V6-V7-DRIVE-BUGS-MASTER

## Symptom
ARCH-IT-ARCH-v6 needed manual nudges at 7 distinct phase boundaries to advance

## Root Cause
Three bug classes: (1) Subject-format mismatch — agents send [TASK-COMPLETE]/[CODING-COMPLETE]/[E2E-RESULTS] in different formats; orchestrator handlers use specific regex that does not normalize; (2) JSON-vs-free-text mismatch — orchestrator handlers expect json.loads(body) but agent Hermes calls produce free-text summaries; (3) Phase-name drift — phase-2-arch-loop vs phase-2-architecture vs 2-arch-loop scattered across handler comparisons; (4) None-to-XADD — Redis XADD does not accept None values but send_to_agent passes them; (5) List-vs-dict in load_learnings — file format drifted from v5 dict to v6 list

## Fix
Add JSON detector with regex fallback in every result handler. Normalize phase names at message boundary. Add filter to send_to_agent that drops None-valued fields. Make load_learnings polymorphic (list-OR-dict). For now: forged proper messages and patched live.

## Files Affected
- /var/lib/karios/orchestrator/event_dispatcher.py

## Lessons
_none recorded_
