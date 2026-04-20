---
type: rca
created: 2026-04-19T07:53:10.713311+00:00
agent: system
incident_id: DISPATCHER-RATING-THRESHOLD-IMPOSSIBLE
severity: HIGH
files_affected: ["/var/lib/karios/orchestrator/event_dispatcher.py"]
tags: ["rca", "system", "high"]
---

# RCA: DISPATCHER-RATING-THRESHOLD-IMPOSSIBLE

## Symptom
Architecture review gate required perfect 10/10 to advance; documented threshold is 8/10. Real blind-tester scores were 5/10 → REJECT, looped forever, never advanced.

## Root Cause
handle_arch_review (line 1325) and similar (line 1550) had if rating >= 10:. Probably aspirational 10/10 from architect rubric draft, but unrealistic for any real review.

## Fix
Patched both gates to >= 8 to match documented threshold in pipeline-phases.md and architect-blind-tester profile. Score 8 + RESILIENCE pass + no CRITICAL → advance.

## Files Affected
- /var/lib/karios/orchestrator/event_dispatcher.py

## Lessons
_none recorded_
