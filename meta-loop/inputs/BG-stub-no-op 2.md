# BG-stub-no-op — Pipeline Self-Test Gap

## Summary

A trivially-implementable backend gap that exercises all 6 phase boundaries
of the KAIROS pipeline. Each phase must fire within a defined timeout.
Exit 0 from `karios-self-test` = pipeline healthy.

## Implementation

- **Backend (Go)**: Add `GET /api/v1/stub/ok` returning `{"ok": true, "timestamp": "<iso>"}`
- **Frontend**: Add "Pipeline Self-Test" button in Control Center, calls the above endpoint
- **Orchestrator**: Naturally exercises all phases as it dispatches this gap

## Phase Boundaries (must all fire within timeout)

| Phase | Boundary | Timeout |
|-------|----------|---------|
| 0 → 1 | `[REQUIREMENT]` received | 30s |
| 1 → 2 | `[RESEARCH-COMPLETE]` received | 120s |
| 2 → 3 | `[ARCH-COMPLETE]` + `[ARCH-REVIEWED]` (rating ≥ 8) | 300s |
| 3 → 4 | `[CODING-COMPLETE]` received | 300s |
| 4 → 5 | `[DEPLOYED-STAGING]` received | 300s |
| 5 → 6 | `[DEPLOYED-PROD]` received | 300s |
| 6 → done | `[MONITORING-COMPLETE]` received (or 24h watchdog) | 86400s |

## Success Criteria

- All 7 phase transitions observed in orchestrator logs
- Telegram notification for each phase transition received
- `karios-self-test` exits 0 within 30 minutes
- `GET /api/v1/stub/ok` returns `{"ok": true, "timestamp": "<iso>"}`

## Files Modified/Created

- `internal/server/server.go`: Added `GET /api/v1/stub/ok` handler
- `internal/server/server_test.go`: Added `TestStubOK` unit test
- `/usr/local/bin/karios-self-test`: CLI script for self-test
- `/var/lib/karios/coordination/requirements/BG-stub-no-op.md`: This document

## Notes

- This is a "no-op" gap — it doesn't implement any real migration features
- It exists solely to exercise the pipeline and verify all phase transitions work
- The orchestrator treats it like any other gap, dispatching to appropriate agents
- BG = "Blind-gap" designation meaning it goes through the full review loop
