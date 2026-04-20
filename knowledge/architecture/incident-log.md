
## 2026-04-18: Stream Key Mismatch — Agents Stalled

**Symptom**: Messages sat in Redis streams unconsumed. Agents showed active heartbeats but never picked up tasks.

**Root Cause**: Orchestrator wrote to `stream:backend-worker` but agent-worker read from `stream:backend`. 
- Orchestrator used full service name: `karios-backend-worker` → stream:backend-worker
- agent-worker used `sys.argv[1]` = "backend" → stream:backend
- Same for frontend (backend-worker vs frontend), devops, tester

**Fix**: Patched `/usr/local/bin/agent-worker`:
- Added `STREAM_NAME_MAP` mapping short names to full names
- Replaced `STREAM_KEY` constant with `get_stream_key()` function
- Restarted all 6 agents after fix

**Files changed**: `/usr/local/bin/agent-worker` (lines 58-84)

**Lesson**: Stream key names must match exactly between orchestrator writes and agent reads.
