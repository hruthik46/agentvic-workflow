# Deployment Plan — ARCH-IT-ARCH-v9 (iteration 1)

## Overview

This deployment plan covers:
1. How to deploy the self-validating pipeline to production
2. How to run BG-stub-feature-no-op as a smoke test
3. Rollback procedure if self-test fails
4. Monitoring and alerting for pipeline health

---

## 1. Self-Validating Pipeline Deployment

### 1.1 Deployment Overview

The self-validating pipeline (BG-stub-feature-no-op) is deployed as a standard T1 gap through the orchestrator. When deployed to production, it serves as a smoke test that verifies all 6 phases work correctly.

### 1.2 Deployment Sequence

```
Step 1: Deploy orchestrator v7.3 (if not already deployed)
  - Location: /var/lib/karios/orchestrator/
  - Service: karios-orchestrator-sub.service
  - Verify: systemctl status karios-orchestrator-sub
  
Step 2: Deploy agent-worker v3.0 to all agents
  - Location: /usr/local/bin/agent-worker
  - Verify: agent-worker --version
  
Step 3: Deploy event_dispatcher.py v7.3
  - Location: /var/lib/karios/orchestrator/event_dispatcher.py
  - Verify: python3 /var/lib/karios/orchestrator/event_dispatcher.py --version
  
Step 4: Verify Redis streams and consumer groups exist
  - redis-cli XINFO GROUPS stream:orchestrator
  - redis-cli XINFO GROUPS inbox:architect
  - redis-cli XINFO GROUPS inbox:backend
  - etc.
  
Step 5: Verify Telegram bot connectivity
  - curl https://api.telegram.org/bot<REDACTED-TELEGRAM-BOT-TOKEN>/getMe
  - Expected: {"ok":true,"result":{"id":..., "username":"Migrator_hermes_bot"}}
```

### 1.3 Component Versions

| Component | Version | Location | Service |
|----------|---------|----------|---------|
| orchestrator | v7.3 | /var/lib/karios/orchestrator/event_dispatcher.py | karios-orchestrator-sub.service |
| agent-worker | v3.0 | /usr/local/bin/agent-worker | karios-backend-worker.service etc. |
| a2a-server | v1.0 | /usr/local/bin/karios-a2a-server | karios-a2a-server.service |
| karios-migration | built from HEAD | /root/karios-source-code/karios-migration/ | karios-migration.service |

### 1.4 Pre-Deployment Checklist

```
[ ] Redis is running and accessible
[ ] Redis AUTH is configured (DEC-004 pending — may use stunnel)
[ ] All 6 agent services are enabled and running
[ ] Orchestrator service is enabled and running
[ ] A2A server is running on port 8093
[ ] Telegram bot token is valid
[ ] All Obsidian vault directories are writable
[ ] Staging host 192.168.118.105 is reachable via SSH
[ ] Deployment script exists at /var/lib/karios-migration/staging/deploy.sh
[ ] Go build tooling is available (go version >= 1.21)
```

---

## 2. Running BG-stub-feature-no-op Smoke Test

### 2.1 When to Run

The BG-stub-feature-no-op smoke test should be run:
1. After any orchestrator upgrade (v7.3 patch, etc.)
2. After any agent-worker upgrade
3. After any Redis infrastructure change
4. On-demand by Sai (weekly recommended)

### 2.2 How to Dispatch

```bash
# Connect to orchestrator Redis
redis-cli -p 6379

# Create the gap
XADD stream:orchestrator * \
  type "create_gap" \
  gap_id "BG-stub-feature-no-op" \
  tier "T0" \
  requirement "Add a no-op feature flag to karios-migration" \
  trace_id "trace_BG-stub-noop_self-test_$(date +%s)"

# The orchestrator will pick up the gap and dispatch to architect
```

Or via the orchestrator CLI:
```bash
python3 /var/lib/karios/orchestrator/event_dispatcher.py \
  dispatch-gap \
  --gap-id BG-stub-feature-no-op \
  --tier T0 \
  --requirement "Add a no-op feature flag"
```

### 2.3 Expected Outcome

If all 6 phases pass naturally:

```
Phase 1 (Research):     ~5 minutes  → [RESEARCH-COMPLETE]
Phase 2 (Architecture):  ~30 minutes → [ARCH-COMPLETE], blind-review 10/10
Phase 3 (Coding):       ~15 minutes → [CODING-COMPLETE], build succeeds
Phase 4 (API-SYNC):     ~5 minutes  → [API-SYNC]
Phase 5 (Deploy):       ~10 minutes → [STAGING-DEPLOYED], health 200
Phase 6 (Complete):     ~1 minute   → Telegram to Sai

Total: ~66 minutes
```

### 2.4 Monitoring the Smoke Test

```bash
# Watch orchestrator logs
tail -f /var/log/karios/orchestrator.log | grep "BG-stub-feature-no-op"

# Watch Redis stream for phase changes
redis-cli XREADGROUP og og stream:orchestrator ">" | grep BG-stub-feature-no-op

# Watch agent heartbeats
watch -n 5 'cat /var/lib/karios/agents/*/heartbeat.json 2>/dev/null | jq -c .'

# Check Telegram for notifications
# (Sai will receive notifications at each phase transition)
```

---

## 3. Rollback Procedure

### 3.1 When to Rollback

Rollback the self-validating pipeline if:
- Phase 2 (Architecture) fails after 3 iterations (blind-review cannot reach 10/10)
- Phase 3 (Coding) fails after 3 iterations (build keeps failing)
- Phase 5 (Deploy) fails after 3 iterations (staging unreachable or health check failing)
- Any phase causes a cascade failure affecting other gaps

### 3.2 Rollback Steps

**Step 1: Stop the Gap**

```bash
# Mark gap as rolled-back in state.json
python3 /var/lib/karios/orchestrator/event_dispatcher.py \
  rollback-gap \
  --gap-id BG-stub-feature-no-op \
  --reason "Build failed after 3 iterations"
```

**Step 2: Restore Previous Version**

```bash
# If orchestrator was upgraded, revert to previous version
cd /var/lib/karios/orchestrator/
git checkout v7.2  # or whatever previous tag
systemctl restart karios-orchestrator-sub

# If agent-worker was upgraded, revert
cd /usr/local/bin/
cp agent-worker agent-worker.v7.3
cp agent-worker.v7.2 agent-worker
systemctl restart karios-backend-worker karios-frontend-worker karios-devops-agent karios-tester-agent
```

**Step 3: Verify Rollback**

```bash
# Check orchestrator version
python3 /var/lib/karios/orchestrator/event_dispatcher.py --version

# Check agent-worker version
/usr/local/bin/agent-worker --version

# Check services are running
systemctl status karios-orchestrator-sub
systemctl status karios-backend-worker
```

**Step 4: Resume Normal Operations**

Other T1 gaps (not BG-stub-feature-no-op) can continue. BG-stub-feature-no-op should be dispatched again after the underlying issue is fixed.

### 3.3 Emergency Stop

If the orchestrator is in a runaway state (constantly dispatching, consuming resources):

```bash
# Stop orchestrator immediately
systemctl stop karios-orchestrator-sub

# Block the orchestrator Redis key to prevent auto-restart
redis-cli SET orchestrator:paused "true" EX 3600

# All agents will eventually stall (heartbeat will stop)
# Sai can then investigate and fix the issue
```

---

## 4. Monitoring and Alerting

### 4.1 Key Metrics

| Metric | Target | Alert Threshold |
|--------|--------|----------------|
| Pipeline success rate | > 90% | < 80% in 24h |
| Phase 2 blind-review first-attempt score | >= 10/10 | < 8/10 |
| Phase 3 build success rate | > 95% | < 85% |
| Phase 5 deploy success rate | > 95% | < 85% |
| Orchestrator heartbeat latency | < 30s | > 60s |
| Agent heartbeat latency | < 60s | > 120s |
| Redis consumer lag | < 100 msgs | > 500 msgs |

### 4.2 Alert Channels

| Alert Type | Channel | Contact |
|------------|---------|---------|
| Critical (orchestrator down) | Telegram | Sai (6817106382) |
| Warning (success rate drop) | Telegram | Sai |
| Info (gap completed) | Telegram | Sai |
| Debug (phase transitions) | Redis pub/sub | Orchestrator log |

### 4.3 Health Check Endpoints

```bash
# Orchestrator health
curl http://localhost:8080/health  # karios_core
curl http://localhost:8089/health  # karios_migration

# Redis health
redis-cli PING
# Expected: PONG

# Agent worker health
cat /var/lib/karios/agents/architect/heartbeat.json | jq .last_beat
# If > 60s ago: agent is stalled

# Telegram bot
curl https://api.telegram.org/bot<REDACTED-TELEGRAM-BOT-TOKEN>/getMe
# Expected: {"ok":true}
```

### 4.4 Log Locations

| Component | Log Location |
|-----------|-------------|
| Orchestrator | /var/log/karios/orchestrator.log |
| Backend agent | /var/log/karios/backend-worker.log |
| Frontend agent | /var/log/karios/frontend-worker.log |
| DevOps agent | /var/log/karios/devops-agent.log |
| Tester agent | /var/log/karios/tester-agent.log |
| A2A server | /var/log/karios/a2a-server.log |
| karios-migration | /var/log/karios/karios-migration.log |
| deploy.sh | stdout/stderr to /var/log/karios/deploy.log |

### 4.5 Dashboard (Optional)

If Grafana is available:

```
Panels:
1. Pipeline success/failure rate (last 24h)
2. Phase durations (P50, P95, P99)
3. Active gaps by phase
4. Redis consumer lag
5. Agent heartbeat latency
6. Telegram notification success rate
```

---

## 5. Dependencies

### 5.1 External Systems

| System | Host | Purpose | SLA |
|--------|------|---------|-----|
| Redis | localhost:6379 | Message queue, state | 99.9% |
| ESXi NodeA | 192.168.115.232 | VMware infra testing | 99% |
| ESXi NodeB | 192.168.115.23 | VMware infra testing | 99% |
| CloudStack | 192.168.118.106:8080 | CloudStack infra testing | 99% |
| Ceph | 192.168.118.240/69 | Storage pool testing | 99% |
| Staging Host | 192.168.118.105 | Deployment target | 99% |
| Telegram API | api.telegram.org | Notifications | 99.5% |
| Obsidian Vault | /opt/obsidian/... | Document storage | 99% |

### 5.2 Internal Dependencies

```
orchestrator (event_dispatcher.py)
  → Redis (streams, state)
  → Obsidian vault (docs)
  → Telegram bot API
  → Agent inbox streams
  
agent-worker (v3.0)
  → Redis (inbox streams, heartbeat)
  → Obsidian vault (coordination docs)
  → A2A server (8093)
  
karios-migration (Go service)
  → Redis (circuit breaker state)
  → vCenter (ESXi hosts)
  → CloudStack API
  → Ceph RBD
```

---

## 6. Verification Checklist

After deploying the self-validating pipeline, verify:

```
Pre-deployment:
[ ] All dependencies reachable
[ ] All services enabled and healthy
[ ] Telegram bot responsive
[ ] Obsidian vault writable
[ ] Redis streams exist

Post-deployment:
[ ] Orchestrator picks up BG-stub-feature-no-op within 30s
[ ] Phase 1 completes with >= 512B research doc
[ ] Phase 2 completes with all 5 docs >= 2048B
[ ] Blind-review produces JSON < 30K chars, score >= 10/10
[ ] Phase 3 build succeeds
[ ] Phase 4 API-SYNC finds no mismatches
[ ] Phase 5 deploy succeeds, health check 200
[ ] Phase 6 Telegram sent to Sai

Total time should be ~66 minutes for happy path.
```

---

## Trace ID

trace_ARCH-IT-ARCH-v9_v6_1776618349