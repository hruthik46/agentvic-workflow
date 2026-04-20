# Deployment Plan — ARCH-IT-ARCH-v11 (iteration 1)

## Overview

Deploy all 6 items (A–F) of ARCH-IT-ARCH-v11. Item F is deferred — documentation only.
Items A, C, D, E modify orchestrator or agent-worker code. Item B adds a new gap + CLI.

**Deployment type**: Incremental — all items are additive (no breaking changes to existing v7.5 behavior).

**Rollback plan**: Each item can be independently disabled via feature flags in orchestrator config.

---

## Pre-Flight Checklist

Before deploying any changes:

```bash
# 1. Verify v7.5 is live
curl -s http://localhost:8080/readyz 2>/dev/null || echo "Orchestrator not reachable"

# 2. Verify all agents are heartbeat-fresh
for agent in backend frontend devops tester monitor orchestrator; do
  age=$(($(date +%s) - $(stat -c %Y /var/lib/karios/heartbeat/${agent}.beat 2>/dev/null || echo 0)))
  echo "${agent}: ${age}s ago"
done

# 3. Verify state.json is healthy
python3 -c "import json; s=json.load(open('/var/lib/karios/coordination/state.json')); print('active_gaps:', len(s.get('active_gaps',{})))"

# 4. Verify git repos are clean
for repo in karios-migration karios-web karios-core karios-bootstrap; do
  cd /root/karios-source-code/$repo && git status --porcelain | head -1 || echo "$repo: clean"
done

# 5. Verify pydantic is available in orchestrator venv
python3 -c "import pydantic; print('pydantic', pydantic.__version__)"
```

---

## Item A: Pydantic Schema Validation

### Files Created
- `/var/lib/karios/orchestrator/message_schemas.py` (new)

### Files Modified
- `/var/lib/karios/orchestrator/event_dispatcher.py` (add `validate_message()` call in `parse_message()`)

### Deployment Steps

**Step A-1**: Create schema file
```bash
cat > /var/lib/karios/orchestrator/message_schemas.py << 'PYEOF'
# (full content from architecture.md Section A.2)
PYEOF
chmod 644 /var/lib/karios/orchestrator/message_schemas.py
```

**Step A-2**: Verify Python syntax
```bash
python3 -m py_compile /var/lib/karios/orchestrator/message_schemas.py && echo "Syntax OK"
```

**Step A-3**: Modify `parse_message()` in `event_dispatcher.py`
- Add import: `from message_schemas import validate_message, SCHEMA_MAP`
- In `parse_message()`, after `body = data.get("body", "")` and before any subject prefix checks, add:
```python
# Item A: Schema validation (log-only for iteration 1)
_valid, _reason, _instance = validate_message(subject, body)
if not _valid:
    print(f"[dispatcher] SCHEMA VIOLATION (log-only): {subject[:40]} — {_reason}")
# (do NOT block — log-only in iteration 1)
```

**Step A-4**: Restart orchestrator
```bash
systemctl restart karios-orchestrator-sub
sleep 5
systemctl status karios-orchestrator-sub --no-pager
```

**Step A-5**: Verify log shows schema loading
```bash
journalctl -u karios-orchestrator-sub --no-pager -n 20 | grep -i "schema\|import\|pydantic"
```

### Feature Flag
```yaml
# In orchestrator config (future iteration 2)
schema_validation_mode: "log-only"  # or "enforce"
```

### Rollback
```bash
# Remove message_schemas.py import + validate_message() call from event_dispatcher.py
# Restart orchestrator
```

---

## Item B: BG-stub-no-op Self-Test

### Files Created
- `/var/lib/karios/coordination/requirements/BG-stub-no-op.md`
- `/usr/local/bin/karios-self-test` (CLI)

### Files Modified
- `/var/lib/karios/orchestrator/event_dispatcher.py` (accelerated timeouts for BG-stub-no-op)

### Deployment Steps

**Step B-1**: Create requirement file
```bash
cat > /var/lib/karios/coordination/requirements/BG-stub-no-op.md << 'MDEOF'
# BG-stub-no-op — Pipeline Self-Test Gap
... (content from architecture.md Section B.1)
MDEOF
```

**Step B-2**: Create self-test CLI
```bash
cat > /usr/local/bin/karios-self-test << 'BASH_EOF'
#!/bin/bash
set -e
... (content from architecture.md Section B.2)
BASH_EOF
chmod +x /usr/local/bin/karios-self-test
```

**Step B-3**: Verify CLI is executable
```bash
test -x /usr/local/bin/karios-self-test && echo "OK" || echo "FAIL"
```

**Step B-4**: Create self-test results directory
```bash
mkdir -p /var/lib/karios/self-test-results
chmod 755 /var/lib/karios/self-test-results
```

**Step B-5**: Verify BG-stub-no-op requirement is recognized
- Trigger via orchestrator: `agent send orchestrator "[REQUIREMENT] BG-stub-no-op: pipeline self-test"`
- Verify orchestrator log shows `[REQUIREMENT]` processed

### Feature Flag
```yaml
# In orchestrator config
bg_self_test_enabled: true
bg_self_test_accelerated_timeouts: true  # 5min STALLED instead of 10min
```

### Rollback
```bash
rm /usr/local/bin/karios-self-test
rm /var/lib/karios/coordination/requirements/BG-stub-no-op.md
# Restore standard timeouts in event_dispatcher.py
```

---

## Item C: code-review-graph Rubric Gate

### Files Modified
- `/usr/local/bin/agent-worker` (add `_check_code_review_graph_usage()` and session metadata extraction)
- `/var/lib/karios/orchestrator/event_dispatcher.py` (add CODING-COMPLETE gate)

### Files Copied From Backup
- `/var/lib/karios/backups/20260419-135438-pre-v7.4/agent-worker` → `/usr/local/bin/agent-worker`

### Deployment Steps

**Step C-1**: Backup current agent-worker
```bash
cp /usr/local/bin/agent-worker /var/lib/karios/backups/20260419-ARCH-IT-ARCH-v11-pre/agent-worker
```

**Step C-2**: Modify `/var/lib/karios/backups/20260419-135438-pre-v7.4/agent-worker` with new code
- Add `_check_code_review_graph_usage()` function (see architecture.md Section C.1)
- Modify `run_hermes()` to call `_check_code_review_graph_usage()` after Hermes completes
- Add `_extract_session_metadata()` function
- Modify CODING-COMPLETE message sending to include `session_metadata`

**Step C-3**: Copy modified agent-worker to production
```bash
cp /var/lib/karios/backups/20260419-135438-pre-v7.4/agent-worker /usr/local/bin/agent-worker
chmod 755 /usr/local/bin/agent-worker
```

**Step C-4**: Modify orchestrator `handle_coding_complete()` dispatch
- Add session metadata gate check (see architecture.md Section C.2)
- Add `[CODING-RETRY]` message type

**Step C-5**: Restart all agents
```bash
systemctl restart karios-backend-worker karios-frontend-worker karios-devops-agent
systemctl restart karios-orchestrator-sub
sleep 10
```

**Step C-6**: Verify agents restarted
```bash
for agent in backend frontend devops; do
  age=$(($(date +%s) - $(stat -c %Y /var/lib/karios/heartbeat/${agent}-worker.beat 2>/dev/null || echo 0)))
  echo "${agent}-worker: ${age}s ago"
done
```

### Feature Flag
```yaml
# In orchestrator config
code_review_graph_gate_enabled: true
```

### Rollback
```bash
cp /var/lib/karios/backups/20260419-ARCH-IT-ARCH-v11-pre/agent-worker /usr/local/bin/agent-worker
systemctl restart karios-backend-worker karios-frontend-worker karios-devops-agent
```

---

## Item D: Gitea Push Verification Gate

### Files Modified
- `/var/lib/karios/orchestrator/event_dispatcher.py` (add `verify_gitea_push()` and `read_gap_manifest()`, modify `handle_prod_deployed()`)

### Deployment Steps

**Step D-1**: Add `verify_gitea_push()` and `read_gap_manifest()` to event_dispatcher.py
```python
# See architecture.md Section D.1 for full implementation
```

**Step D-2**: Modify `handle_prod_deployed()` in event_dispatcher.py
- Call `verify_gitea_push()` before Phase 6 transition
- On failure: send `[GITEA-PUSH-PENDING]` to devops, return early
- On success: continue with existing Phase 6 transition

**Step D-3**: Restart orchestrator
```bash
systemctl restart karios-orchestrator-sub
sleep 5
```

**Step D-4**: Create iteration-tracker manifest directory for BG-stub-no-op
```bash
mkdir -p /var/lib/karios/iteration-tracker/BG-stub-no-op
echo '{"gap_id":"BG-stub-no-op","iteration":1,"repos_touched":[],"files_changed":[]}' > /var/lib/karios/iteration-tracker/BG-stub-no-op/manifest.json
```

**Step D-5**: Integration test
- Dispatch BG-stub-no-op requirement
- Verify `[PROD-DEPLOYED]` triggers `verify_gitea_push()` check
- Verify gate passes when git is clean

### Feature Flag
```yaml
# In orchestrator config
gitea_push_gate_enabled: true
```

### Rollback
```bash
# Restore original handle_prod_deployed() in event_dispatcher.py
# Restart orchestrator
```

---

## Item E: Watchdog Kill-on-No-Tool-Call

### Files Modified
- `/usr/local/bin/agent-worker` (replace `subprocess.run` with `run_hermes_pty()`)

### Deployment Steps

**Step E-1**: Backup current agent-worker
```bash
cp /usr/local/bin/agent-worker /var/lib/karios/backups/20260419-ARCH-IT-ARCH-v11-pre/agent-worker-v2
```

**Step E-2**: Implement `run_hermes_pty()` in agent-worker
```python
# See architecture.md Section E.2 for full implementation
# Key changes:
# - Replace subprocess.run with Popen + pty.openpty()
# - Add stream_reader() background thread
# - Token counting with watchdog at 4000 tokens
# - SIGTERM escalation to SIGKILL
# - Retry with explicit prompt prepend
# - Fallback to subprocess.run on PTY failure
```

**Step E-3**: Test PTY availability
```bash
python3 -c "import pty; master, slave = pty.openpty(); print('PTY OK'); import os; os.close(master); os.close(slave)"
```

**Step E-4**: Verify hermes command is available
```bash
which hermes && hermes --version 2>&1 | head -3
```

**Step E-5**: Restart agents
```bash
systemctl restart karios-backend-worker
sleep 3
systemctl status karios-backend-worker --no-pager -n 5
```

**Step E-6**: Smoke test watchdog
- Dispatch a gap that triggers Hermes prose-only (force via mock)
- Verify SIGTERM fires at 4000 tokens
- Verify retry with explicit prompt prepend happens

### Feature Flag
```yaml
# In agent config (per-agent profile)
watchdog_pty_enabled: true
watchdog_token_threshold: 4000
watchdog_retry_with_explicit_prompt: true
```

### Rollback
```bash
# Restore subprocess.run path in agent-worker
# cp /var/lib/karios/backups/20260419-ARCH-IT-ARCH-v11-pre/agent-worker /usr/local/bin/agent-worker
# systemctl restart karios-backend-worker
```

---

## Item F: tool_choice Passthrough — Deferred

No deployment in this iteration. Documentation only.

---

## Integration Test Plan (Post-Deployment)

After ALL items deployed, run the full pipeline self-test:

```bash
# 1. Start karios-self-test
/usr/local/bin/karios-self-test --gap-id BG-stub-no-op --timeout 1800
echo "Exit code: $?"

# 2. Check Telegram for phase notifications
# (manual verification — bot @Migrator_hermes_bot)

# 3. Verify all phase boundaries in orchestrator log
grep -E "SCHEMA|CODING-RETRY|GITEA-PUSH-PENDING|WATCHDOG" /var/lib/karios/orchestrator/event_dispatcher.log | tail -20

# 4. Verify schema-violations directory exists (empty during iteration 1)
ls /var/lib/karios/agent-msg/schema-violations/ 2>/dev/null || echo "dir does not exist yet (iteration 1 log-only)"

# 5. Verify self-test results logged
ls /var/lib/karios/self-test-results/
```

---

## Monitoring and Health Checks

### Post-Deploy Health Check
```bash
# Orchestrator healthy
curl -s http://localhost:8080/readyz | python3 -m json.tool

# All agents heartbeat fresh
find /var/lib/karios/heartbeat/ -name "*.beat" -mmin -5 | wc -l
# Expected: >= 6 (orchestrator + 5 workers)

# State.json consistent
python3 -c "
import json
s = json.load(open('/var/lib/karios/coordination/state.json'))
ag = s.get('active_gaps', {})
for gid, g in ag.items():
    print(f'{gid}: phase={g.get(\"phase\")}, state={g.get(\"state\")}')
"

# Telegram bot responding
curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe" | python3 -c "import sys,json; d=json.load(sys.stdin); print('Bot OK:', d.get('result',{}).get('username','FAIL'))"
```

### Alerting Thresholds
- Orchestrator heartbeat > 120s → Telegram alert
- Agent heartbeat > 300s → Telegram alert  
- SCHEMA VIOLATION rate > 5/min → Telegram alert
- CODING-RETRY rate > 3 per gap → Telegram alert

---

## Deployment Order

| Step | Item | Action | Risk |
|------|------|--------|------|
| 1 | A | Deploy message_schemas.py + validate_message() call | Low (log-only) |
| 2 | B | Deploy BG-stub-no-op.md + karios-self-test CLI | Low |
| 3 | C | Deploy code-review-graph gate in agent-worker + dispatcher | Medium |
| 4 | D | Deploy Gitea push gate in dispatcher | Low |
| 5 | E | Deploy watchdog PTY in agent-worker | Medium |

**Note**: Items C and E both modify agent-worker. Deploy C first, then E.

---

## v7.6 Artifact

After all items deployed and self-test passes, tag the deployment:

```bash
cd /var/lib/karios/orchestrator
git add -A
git commit -m "karios-meta: ARCH-IT-ARCH-v11-iter-1 — v7.6 production gates (A+B+C+D+E)"
git tag -a v7.6 -m "v7.6: schema validation (log-only), self-test CLI, code-review-graph gate, Gitea push gate, watchdog PTY"
git push origin HEAD
git push origin v7.6
```