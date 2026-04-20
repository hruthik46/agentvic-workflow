# Deployment Plan — ARCH-IT-ARCH-v10 (iteration 1)

## Overview

Deploy v10 changes in 5 sequential phases. Each phase is independently testable and reversible. BG-stub-no-op self-test runs after Phase 5 to validate all 6 phases end-to-end.

**Estimated total deploy time**: 45–60 minutes
**Rollback time**: < 5 minutes via `karios-meta-runner rollback`

---

## Pre-Deploy Checklist

- [ ] Archive current v7.4 state: `karios-meta-runner archive`
- [ ] All 9 agent services healthy: `systemctl list-units 'karios-*' | grep running`
- [ ] Redis healthy: `redis-cli -h 192.168.118.202 ping` → `PONG`
- [ ] Telegram bot token valid: check `/etc/karios/secrets.env`
- [ ] Gitea credentials valid: test `git push --dry-run` to gitea.karios.ai
- [ ] Backup all modified files
- [ ] Notify Sai: "Starting v10 deployment — Telegram may be quiet for ~60 minutes"

---

## Phase 1: Message Schemas + parse_message Validation (Stateless)

**Risk**: Low — adds Pydantic validation, falls back to unvalidated on any exception.

### Files Changed
1. **Create**: `/var/lib/karios/orchestrator/message_schemas.py`
   - Pydantic models for all message subjects
   - Schema registry dict
2. **Modify**: `/var/lib/karios/orchestrator/event_dispatcher.py`
   - Import `message_schemas`
   - Add schema validation in `parse_message()`
   - Add `[SCHEMA-REJECTED]` handling
3. **Modify**: `/var/lib/karios/coordination/state-schema.json`
   - Add `self_test_running`, `graph_usage_score`, `last_push_verify` fields

### Deploy Steps
```bash
# 1. SCP to orchestrator node
scp /var/lib/karios/iteration-tracker/ARCH-IT-ARCH-v10/phase-2-architecture/iteration-1/message_schemas.py \
   root@192.168.118.106:/var/lib/karios/orchestrator/message_schemas.py

# 2. Patch event_dispatcher.py (use patch tool)
# Apply the parse_message enhancement

# 3. Reload orchestrator (no restart needed — dispatcher is event loop)
# Just verify the file loads:
python3 -c "import sys; sys.path.insert(0,'/var/lib/karios/orchestrator'); import message_schemas; print('OK')"
```

### Validation
```bash
# Test schema loads
python3 -c "from message_schemas import MESSAGE_SCHEMAS, ArchCompleteBody; print(list(MESSAGE_SCHEMAS.keys()))"

# Test valid message
python3 -c "
from message_schemas import ArchCompleteBody
body = {
    'phase': 'phase-2-arch',
    'iteration': 1,
    'gap_id': 'BG-test',
    'trace_id': 'trace_test',
    'files_changed': ['architecture.md','edge-cases.md','test-cases.md','api-contract.md','deployment-plan.md'],
    'doc_sizes': {'architecture.md': 4096, 'edge-cases.md': 4096, 'test-cases.md': 4096, 'api-contract.md': 4096, 'deployment-plan.md': 4096}
}
b = ArchCompleteBody.model_validate(body)
print('Valid:', b.gap_id)
"

# Test invalid message (should raise)
python3 -c "
from message_schemas import ArchCompleteBody
body = {'phase': 'phase-2-arch', 'iteration': 1, 'gap_id': 'BG-test', 'trace_id': 'trace_test',
        'files_changed': ['architecture.md'], 'doc_sizes': {'architecture.md': 512}
try:
    ArchCompleteBody.model_validate(body)
    print('ERROR: should have raised')
except Exception as e:
    print('Caught:', str(e)[:100])
"
```

### Rollback
```bash
# Restore from backup
cp /var/lib/karios/backups/<timestamp>-pre-v10/message_schemas.py /var/lib/karios/orchestrator/message_schemas.py
# Restore event_dispatcher.py from git
cd /var/lib/karios/orchestrator && git checkout event_dispatcher.py
```

---

## Phase 2: Agent-Worker Watchdog (Process-Level)

**Risk**: Medium — adds SIGKILL mechanism. Test with WATCHDOG_ENABLED=0 first.

### Files Changed
1. **Modify**: `/usr/local/bin/agent-worker`
   - Replace `subprocess.run` with `subprocess.Popen` + watchdog thread
   - Add token counter and tool-call detection
   - Add SIGKILL via process group

### Deploy Steps
```bash
# 1. Copy new agent-worker (keep old as backup)
cp /usr/local/bin/agent-worker /usr/local/bin/agent-worker.v7.4.bak

# 2. Deploy new agent-worker
# (Apply patch to run_hermes function)

# 3. Test without watchdog (env var = 0)
WATCHDOG_ENABLED=0 systemctl restart karios-backend-worker
sleep 5
systemctl status karios-backend-worker | grep running

# 4. Test WITH watchdog on a non-critical agent first (architect)
WATCHDOG_ENABLED=1 systemctl restart karios-architect-worker
sleep 5
# Send a simple task
agent send orchestrator "[ARCH-DESIGN] ARCH-IT-ARCH-v10 — Phase 2: Architecture Design"
# Watch logs
journalctl -u karios-architect-worker -n 50 --no-pager
```

### Validation
```bash
# Verify watchdog thread starts
grep -i watchdog /var/log/karios/architect.log

# Send task that produces long prose (mock test)
# Watchdog should NOT fire on normal task
# Watchdog should fire on mock Hermes that produces 30K+ tokens without tool

# Test token counting
python3 -c "
# Mock test of token counter logic
text = 'word ' * 35000  # 35000 tokens
tokens = len(text) // 4
print(f'Tokens: {tokens}')
"
```

### Rollback
```bash
cp /usr/local/bin/agent-worker.v7.4.bak /usr/local/bin/agent-worker
systemctl restart karios-backend-worker karios-frontend-worker karios-devops-agent \
                  karios-tester-agent karios-monitor-worker \
                  karios-architect-worker karios-architect-blind-tester \
                  karios-code-blind-tester
```

---

## Phase 3: tool_use_enforcement: strict (Config Change)

**Risk**: Medium — may cause Hermes to loop on non-coding agents. Only apply to coding agents first.

### Files Changed
1. **Modify**: `/root/.hermes/config.yaml` — global default (careful!)
2. **Modify**: Per-profile configs:
   - `/root/.hermes/profiles/architect/config.yaml`
   - `/root/.hermes/profiles/backend/config.yaml`
   - `/root/.hermes/profiles/frontend/config.yaml`

### Deploy Steps
```bash
# 1. Add tool_use_enforcement: strict to ONLY coding agents first (not all 9)
for profile in architect backend frontend; do
  echo "  tool_use_enforcement: strict" >> /root/.hermes/profiles/$profile/config.yaml
done

# 2. Restart coding agents
systemctl restart karios-architect-worker karios-backend-worker karios-frontend-worker

# 3. Watch for 5 minutes — any infinite loops?
journalctl -u karios-backend-worker -n 100 --no-pager | grep -i "error\|loop\|timeout"
```

### Validation
```bash
# Test: hermes should use a tool on first turn
hermes chat --query "What files are in /tmp?" --profile backend --toolsets terminal,file 2>&1 | head -50
# Expected: first response contains tool call or tool result

# Compare with auto mode (control test)
# Run same query with a temp config: tool_use_enforcement: auto
```

### If Problems Found
- Keep `auto` for monitor, tester, devops, blind-testers
- Only architect, backend, frontend get `strict`

### Rollback
```bash
# Remove strict lines from profile configs
for profile in architect backend frontend; do
  sed -i '/tool_use_enforcement: strict/d' /root/.hermes/profiles/$profile/config.yaml
done
systemctl restart karios-architect-worker karios-backend-worker karios-frontend-worker
```

---

## Phase 4: Gitea Push Verification + Self-Test Trigger

**Risk**: Low — only affects Phase 5→6 transition. No impact on existing running gaps.

### Files Changed
1. **Modify**: `/var/lib/karios/orchestrator/event_dispatcher.py`
   - Add `verify_gitea_push()` function
   - Add `check_graph_rubric()` function
   - Modify `[PROD-DEPLOYED]` handler to call `verify_gitea_push()`
   - Add `[SELF-TEST]` handler
   - Add `stream:graph-audit` and `stream:schema-violations` Redis stream setup

### Deploy Steps
```bash
# 1. Deploy dispatcher patch (verify_gitea_push + check_graph_rubric + SELF-TEST handler)

# 2. Create BG-stub-no-op requirement file
mkdir -p /var/lib/karios/coordination/requirements/
cat > /var/lib/karios/coordination/requirements/BG-stub-no-op.md << 'EOF'
(gap definition from architecture.md Section C)
EOF

# 3. Verify Redis streams exist (create if not)
redis-cli -h 192.168.118.202 XADD stream:graph-audit '*' \
  dummy_field 'init' 'gap_id' 'SYSTEM_BOOT' 'agent' 'orchestrator'

# 4. Restart orchestrator to pick up new code
systemctl restart karios-orchestrator

# 5. Verify
redis-cli -h 192.168.118.202 XLEN stream:graph-audit
```

### Validation
```bash
# Test: Manual push verification
cd /root/karios-source-code/karios-migration
git fetch origin
# Test the git rev-list command
git rev-list --left-right --count origin/main...HEAD

# Test: SELF-TEST trigger
agent send orchestrator "[SELF-TEST]"

# Watch orchestrator logs
journalctl -u karios-orchestrator -f -n 100 | grep -i "self-test\|graph-audit\|push-verify"
```

### Rollback
```bash
cd /var/lib/karios/orchestrator && git checkout event_dispatcher.py
systemctl restart karios-orchestrator
```

---

## Phase 5: Telegram Filter + Final Integration

**Risk**: Low — removes human command handlers. Emergency bypass still works.

### Files Changed
1. **Modify**: `karios-hitl-listener`
   - Add `is_pipeline_origin()` filter
   - Reduce allowed commands to `/status`, `/emergency-unblock`
   - Auto-reply "Pipeline-controlled bot" to unauthorized commands

### Deploy Steps
```bash
# 1. Backup current hitl-listener
cp /usr/local/bin/karios-hitl-listener /usr/local/bin/karios-hitl-listener.v7.4.bak

# 2. Deploy new hitl-listener

# 3. Restart
systemctl restart karios-hitl-listener

# 4. Test /status command
curl -s http://localhost:8081/status  # or Telegram test

# 5. Test unauthorized command gets auto-reply
# Send /help to bot — should get "Pipeline-controlled bot"
```

### Rollback
```bash
cp /usr/local/bin/karios-hitl-listener.v7.4.bak /usr/local/bin/karios-hitl-listener
systemctl restart karios-hitl-listener
```

---

## Phase 6: Self-Test Validation (BG-stub-no-op)

**Trigger**: All Phase 1–5 changes deployed. Run after each phase to validate incrementally.

### Self-Test Run
```bash
# Trigger self-test
agent send orchestrator "[SELF-TEST]"

# Monitor progress
watch -n 10 'cat /var/lib/karios/iteration-tracker/BG-stub-no-op/metadata.json 2>/dev/null | python3 -m json.tool'
```

### Expected Self-Test Results

| Phase | Gate | Expected Result |
|-------|------|-----------------|
| 1 | Research doc >= 512 bytes, >= 3 URLs | PASS |
| 2 | All 5 docs >= 2048 bytes | PASS |
| 2 | Blind-tester score 10/10 | PASS |
| 3 | `go build ./...` exit 0 | PASS |
| 4 | Health check 200 OK | PASS |
| 5 | Deploy to staging success | PASS |
| 6 | Telegram message sent | PASS |

**Total**: All 6 phases pass → v10 is production-ready.

---

## Post-Deploy Checklist

- [ ] All 9 agent services running
- [ ] BG-stub-no-op completed all 6 phases
- [ ] `tool_use_enforcement: strict` active on architect/backend/frontend
- [ ] Schema violations logged (if any during self-test)
- [ ] Gitea push verified (check logs)
- [ ] Telegram notifications working (check Sai's chat)
- [ ] No Hermes processes orphaned (check `ps aux | grep hermes`)
- [ ] Redis streams healthy (`stream:graph-audit`, `stream:schema-violations`)
- [ ] Notify Sai: "v10 deployed and validated. All 6 self-test phases passed."

---

## Rollback Procedure (Full)

If any phase causes issues:

```bash
# Step 1: Stop all agents
systemctl stop karios-backend-worker karios-frontend-worker karios-devops-agent \
              karios-tester-agent karios-monitor-worker karios-architect-worker \
              karios-architect-blind-tester karios-code-blind-tester

# Step 2: Restore orchestrator
cd /var/lib/karios/orchestrator && git checkout event_dispatcher.py

# Step 3: Restore agent-worker
cp /usr/local/bin/agent-worker.v7.4.bak /usr/local/bin/agent-worker

# Step 4: Restore hitl-listener
cp /usr/local/bin/karios-hitl-listener.v7.4.bak /usr/local/bin/karios-hitl-listener

# Step 5: Restore hermes configs (remove strict)
for profile in architect backend frontend; do
  sed -i '/tool_use_enforcement: strict/d' /root/.hermes/profiles/$profile/config.yaml
done

# Step 6: Start all agents
systemctl start karios-orchestrator
sleep 3
systemctl start karios-backend-worker karios-frontend-worker karios-devops-agent \
                karios-tester-agent karios-monitor-worker karios-architect-worker \
                karios-architect-blind-tester karios-code-blind-tester

# Step 7: Verify v7.4
python3 -c "import sys; sys.path.insert(0,'/var/lib/karios/orchestrator'); from message_schemas import MESSAGE_SCHEMAS" 2>&1
# Should fail (no schemas) or just check version
cat /var/lib/karios/coordination/state.json | python3 -m json.tool | grep version
```

---

## File Inventory

| File | Action | Rollback |
|------|--------|---------|
| `/var/lib/karios/orchestrator/message_schemas.py` | Create | Delete |
| `/var/lib/karios/orchestrator/event_dispatcher.py` | Modify | `git checkout` |
| `/usr/local/bin/agent-worker` | Modify | `cp .v7.4.bak` |
| `/usr/local/bin/karios-hitl-listener` | Modify | `cp .v7.4.bak` |
| `/root/.hermes/profiles/architect/config.yaml` | Modify | `sed -i '/strict/d'` |
| `/root/.hermes/profiles/backend/config.yaml` | Modify | `sed -i '/strict/d'` |
| `/root/.hermes/profiles/frontend/config.yaml` | Modify | `sed -i '/strict/d'` |
| `/var/lib/karios/coordination/state-schema.json` | Modify | `git checkout` |
| `/var/lib/karios/coordination/requirements/BG-stub-no-op.md` | Create | Delete |
