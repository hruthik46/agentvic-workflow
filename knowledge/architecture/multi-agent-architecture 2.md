---
title: "Multi-Agent Communication Architecture"
type: architecture
tags: [agents, architecture, communication, orchestration, multi-agent, obsidian, redis]
date: 2026-04-15
status: active
version: "1.0"
agents: [orchestrator, backend, frontend, devops, tester, monitor]
---

# Multi-Agent Communication Architecture

> **Status:** Active | **Version:** 1.0 | **Last Updated:** 2026-04-15

This document describes the complete multi-agent communication system for the Karios migration platform. It is the **source of truth** for agent design, communication protocols, handoff patterns, and continuous improvement loops.

**Update this document whenever any part of the agent system changes.** The architecture lives here — not in anyone's memory.

---

## System Overview

The system consists of **6 autonomous agents** that communicate via a structured Context Packet protocol. The Orchestrator drives task assignments while agents can also communicate **peer-to-peer** without going through the Orchestrator.

```
┌─────────────────────────────────────────────────────────────────┐
│                      ORCHESTRATOR                                │
│  • Task assignment via context packets                          │
│  • Pipeline state tracking (state.json)                         │
│  • Routes failures to correct agents                            │
│  • Daily synthesizer + weekly research loop                     │
│  • Alerts Sai via Telegram on critical issues                   │
└───────────────┬─────────────────────────────────────────────────┘
                │ Context Packets + Redis Events
    ┌───────────┼───────────┬───────────┬───────────┬────────────┐
    ▼           ▼           ▼           ▼           ▼            ▼
┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐
│BACKEND │ │FRONTEND│ │ DEVOPS │ │ TESTER │ │MONITOR │ │  (all) │
│Worker  │ │ Worker │ │ Agent  │ │ Agent  │ │Worker  │ │ agents │
└────────┘ └────────┘ └────────┘ └────────┘ └────────┘ └────────┘
     │           │           │           │           │
     └───────────┴───────────┴───────────┴───────────┘
                         │ peer-to-peer messaging

┌─────────────────────────────────────────────────────────────────┐
│                     WATCHDOG (systemd service)                   │
│  • Runs every 60s, checks all agent heartbeats                   │
│  • Alerts if agent silent > 2 minutes                           │
│  • Telegram alert if agent silent > 5 minutes                   │
│  • Writes incidents to monitor's inbox                           │
└─────────────────────────────────────────────────────────────────┘
```

---

## The 6 Agents

### 1. Orchestrator (`orchestrator-agent.hermes`)

**Profile:** `/root/.hermes/profiles/orchestrator-agent.hermes`

**Primary Role:** Chief coordinator. Drives the event loop, assigns tasks, tracks pipeline state, self-improves.

**Key Responsibilities:**
- Pick tasks from SQLite queue (`/var/lib/karios/task-queue.db`) and assign to agents
- Track all in-flight tasks in `state.json`
- Respond to Redis events AND agent inbox messages
- Route failures to correct remediation agents
- Run daily learning synthesizer + weekly research loop
- Alert Sai via Telegram on critical failures

**Entry Point:** `/var/lib/karios/orchestrator/event_dispatcher.py` (runs as `karios-orchestrator-sub.service`)

---

### 2. Backend Worker (`backend-worker.hermes`)

**Profile:** `/root/.hermes/profiles/backend-worker.hermes`

**Primary Role:** Go backend implementation.

**Key Responsibilities:**
- Implement Go features from task queue
- Write unit tests (coverage must increase)
- Run `golangci-lint` and `go test ./...` — both must pass before push
- Create PR targeting `main`, assign `sivamani` as author, `saihruthik` as reviewer
- Update `api-contract.json` if new endpoints added
- Write Obsidian summary after every task
- Write self-critique after every task
- **Send context packet to DevOps after every deployment-ready PR merge**

**Workspace:** `/root/karios-source-code/karios-migration`

---

### 3. Frontend Worker (`frontend-worker.hermes`)

**Profile:** `/root/.hermes/profiles/frontend-worker.hermes`

**Primary Role:** React/TypeScript UI implementation.

**Key Responsibilities:**
- Implement React features matching the karios-web design system
- Use **only existing shared components** from `src/lib/shared/components/`
- Read `api-contract.json` and `ui-patterns.json` before every task
- Write Playwright E2E tests for every feature
- Create PRs in both karios-web and karios-playwright repos
- Write self-critique after every task
- **Send context packet to DevOps after PR merge**

**Workspace:** `/root/karios-source-code/karios-web` + `/root/karios-source-code/karios-playwright`

---

### 4. DevOps Agent (`devops-agent.hermes`)

**Profile:** `/root/.hermes/profiles/devops-agent.hermes`

**Primary Role:** Infrastructure deployment and health management.

**Key Responsibilities:**
- Subscribe to Redis channel `migration/events`
- On `backend:merged` → deploy backend to ALL 3 mgmt nodes (not just one)
- On `frontend:merged` → deploy frontend to all 3 mgmt nodes
- Run health checks after every deployment (curl metrics endpoint)
- On failure: rollback immediately, publish `deployment:failed`
- Update `deployment.json` after every deployment
- Write infra tests to `karios-playwright/tests/infra/`
- Write self-critique after every deployment
- **Send context packet to Tester after successful deployment**
- **Alert Orchestrator immediately on deployment failure**

**Mgmt Nodes:** `192.168.118.105`, `192.168.118.106`, `192.168.118.2`

---

### 5. Tester Agent (`tester-agent.hermes`)

**Profile:** `/root/.hermes/profiles/tester-agent.hermes`

**Primary Role:** E2E testing and quality assurance.

**Key Responsibilities:**
- Subscribe to Redis channel `migration/events`
- On `backend:deployed` → run backend E2E tests against staging
- On `frontend:deployed` → run frontend E2E tests against staging
- Write Playwright E2E tests for every new feature
- Maintain the regression test suite
- Capture screenshots + logs on failure
- Write `test-results.json` after every run
- Write self-critique after every test run
- **Send context packet to Orchestrator after every test run**
- **On failure: send to both Orchestrator and relevant developer agent**

**Playwright Config:** `/root/karios-source-code/karios-playwright/playwright.config.ts`

---

### 6. Monitor Worker (`monitor-worker.hermes`)

**Profile:** `/root/.hermes/profiles/monitor-worker.hermes`

**Primary Role:** System observability and alerting.

**Key Responsibilities:**
- Read watchdog inbox for agent failure alerts
- Read agent inboxes for health signals
- Aggregate health status from all agents
- Track agent uptime and performance metrics
- Alert Sai via Telegram on critical issues
- Write daily system health reports to Obsidian
- Track incidents in `state.json`

**Alert Criteria (CRITICAL):**
- Any agent DOWN for > 5 minutes
- Deployment failure
- Multiple E2E test failures
- Redis unavailable
- API down on >1 node

---

## Communication Protocol

### Core Principle: Context Packets Over Signals

**Every agent-to-agent communication uses a Context Packet** — not just a signal or event name. A Context Packet contains the full task state: what was done, key decisions, current state, next steps, and notes for the receiver.

This eliminates the "handoff problem" where Agent B receives a signal from Agent A but has no idea what Agent A actually did or what Agent B should do next.

### `agent msg` CLI

**Location:** `/usr/local/bin/agent msg`

**Primary Commands:**

```bash
# Send a message with optional context packet
agent msg send <to_agent> <message> \
  [--priority high|normal|low] \
  [--context /path/to/context-packet.json]

# Read messages from inbox
agent msg read [--unread] [--from <agent>] [--format json|text]

# Acknowledge a message (archives it)
agent msg ack <packet_id>

# Show inbox/outbox/heartbeat status
agent msg status

# Broadcast to all agents
agent msg broadcast <message> [--priority high|normal|low]
```

**Valid agents:** `orchestrator`, `backend`, `frontend`, `devops`, `tester`, `monitor`

**Examples:**

```bash
# Backend → DevOps handoff after PR merge
HERMES_AGENT=backend agent msg send devops "BG-01 merged. PR #42. Deploying now." \
  --priority high \
  --context /var/lib/karios/context-bus/packets/pckt_abc123.json

# DevOps → Tester after successful deployment
HERMES_AGENT=devops agent msg send tester "BG-01 deployed. SHA abc123. Ready for E2E." \
  --priority high \
  --context /var/lib/karios/context-bus/packets/pckt_def456.json

# Tester → Orchestrator on failure
HERMES_AGENT=tester agent msg send orchestrator "BG-01 E2E FAILED: 3 tests. Details in test-results.json" \
  --priority high

# Orchestrator → Backend with fix request
HERMES_AGENT=orchestrator agent msg send backend "BG-01 E2E failed: log stream timeout. Fix and re-deploy." \
  --priority high

# Check your inbox
HERMES_AGENT=backend agent msg read --unread
```

### Context Packet Schema

Every handoff packet is a JSON file at `/var/lib/karios/context-bus/packets/<packet_id>.json`:

```json
{
  "id": "pckt_<uuid>",

  "type": "task_assignment|handoff|deployment_complete|test_complete|
           incident_alert|escalation|closure",

  "from": "<agent_name>",
  "to": "<agent_name>",

  "status": "pending|acknowledged|completed|archived",

  "priority": "high|normal|low",

  "created_at": "<ISO8601>",

  "read_at": null,
  "acknowledged_at": null,

  "message": "<human-readable summary>",

  "task": {
    "task_id": "BG-01",
    "title": "CPU/RAM morphing",
    "summary": "<what this task involves>",
    "artifacts": [
      "/root/karios-source-code/karios-migration/internal/migration/morph.go"
    ],
    "branch": "feature/BG-01-cpu-morph",
    "pr_url": "https://gitea.karios.ai/KariosD/karios-migration/pull/42",
    "commit_sha": "abc123",
    "acceptance_criteria": ["criterion 1", "criterion 2"],
    "blocked_by": [],
    "unblocks": ["FG-01"]
  },

  "handoff": {
    "what_was_done": "<specific implementation details>",
    "current_state": "<e.g., PR merged, ready to deploy>",
    "key_decisions": ["decision 1", "decision 2"],
    "next_steps": ["step 1", "step 2"],
    "open_questions": ["question 1"],
    "blocking_tasks": []
  },

  "comms": {
    "notes_for_receiver": "<anything the receiver needs to know>",
    "questions_for_receiver": [],
    "receiver_should_know": "<e.g., All tests pass, golangci-lint clean>"
  },

  "metadata": {
    "packet_version": "1.0",
    "protocol": "agent-comm-v1",
    "retry_count": 0,
    "ttl_hours": 72,
    "outbox_path": "/var/lib/karios/agent-msg/outbox/<agent>/<packet_id>.json"
  }
}
```

### Packet Lifecycle

```
DRAFT → ACTIVE → ACKNOWLEDGED → COMPLETED → ARCHIVED
         ↑
    (sent to inbox)
```

1. **DRAFT:** Agent creates packet locally
2. **ACTIVE:** Sent to receiver's inbox + context-bus/packets/
3. **ACKNOWLEDGED:** Receiver calls `agent msg ack <packet_id>` — packet moves to archive
4. **COMPLETED:** Task/operation confirmed done
5. **ARCHIVED:** Packet retained in `/var/lib/karios/context-bus/archive/` for 7 days

### Directory Structure

```
/var/lib/karios/
  agent-msg/
    inbox/
      orchestrator/    # Messages FOR orchestrator
      backend/         # Messages FOR backend
      frontend/        # Messages FOR frontend
      devops/          # Messages FOR devops
      tester/          # Messages FOR tester
      monitor/         # Messages FOR monitor
    outbox/
      <agent>/         # Audit trail of what each agent sent

  context-bus/
    packets/           # Active context packets (source of truth)
    pending/           # Unacknowledged packets (retry queue)
    archive/           # Completed/acknowledged packets

  heartbeat/
    orchestrator.beat
    backend.beat
    frontend.beat
    devops.beat
    tester.beat
    monitor.beat

  learnings/
    critiques/
      orchestrator/
      backend/
      frontend/
      devops/
      tester/
      monitor/
    synthesized/        # Daily synthesized reports
    research/          # Weekly research findings
```

### Redis Events (Ephemeral Signal Channel)

Redis pub/sub on channel `migration/events` carries **ephemeral signals** — not context. Agents listen for these and respond with context packets.

**Event Format:**
```json
{
  "agent": "<agent_name>",
  "event": "<event_type>",
  "gap_id": "<task_id>",
  "timestamp": "<ISO8601>",
  "data": {}
}
```

**Key Events:**
| Event | Triggered By | Expected Response |
|-------|--------------|-------------------|
| `backend:pr-created` | Backend | Orchestrator updates state, monitors pipeline |
| `backend:merged` | Gitea/webhook | Orchestrator assigns DevOps |
| `backend:deployed` | DevOps | Orchestrator assigns Tester |
| `frontend:merged` | Gitea/webhook | Orchestrator assigns DevOps |
| `frontend:deployed` | DevOps | Orchestrator assigns Tester |
| `test:passed` | Tester | Orchestrator closes task, notifies Sai |
| `test:failed` | Tester | Orchestrator routes to developer |
| `deployment:failed` | DevOps | Orchestrator alerts Sai, triggers rollback |

**Redis Config:** `192.168.118.202:6379`, user `karios_admin`

---

## Continuous Improvement Loops

### 1. Daily Learning Synthesizer

**Schedule:** `0 0 * * *` (midnight UTC) via cron

**Command:** `python3 /usr/local/bin/synthesize-learnings.py`

**What it does:**
1. Scans `/var/lib/karios/learnings/critiques/<agent>/` for last 24h
2. Parses each critique for: what worked, what failed, for-next-agent notes
3. Identifies **cross-agent patterns** — repeated successes or failures across 2+ agents
4. Generates synthesized report at:
   `Obsidian: agents/orchestrator/synthesized/YYYY-MM-DD.md`
5. Updates `agents/orchestrator/learnings.md` with pattern insights
6. Proposes new architectural decisions for `decisions.json`

**Critique Format** (written by each agent after every task):

```markdown
# Self-Critique: <Task ID> <Title>

**Agent:** <agent>
**Date:** YYYY-MM-DD
**Task:** <task_id> — <title>

## What Worked
- bullet
- bullet

## What Didn't Work
- bullet

## What to Improve
- [ ] actionable item

## For the Next Agent Doing Similar Work
- specific guidance
```

**Synthesizer Output Example:**

```markdown
### Repeated Failures (3 patterns)

- *({count}x)* CPU morphing round-trip lost precision on odd socket counts
- *({count}x)* DevOps had to ask Backend for config changes twice

### Context Losses

- **backend**: "Tester didn't know I changed the API response shape"
```

---

### 2. Weekly Research Loop

**Schedule:** `0 2 * * 0` (Sunday 02:00 UTC) via cron

**Command:** `python3 /usr/local/bin/orchestrator-research.py`

**What it does:**
1. Searches curated multi-agent research sources (AutoGen, CrewAI, LangGraph, Reflexion papers)
2. Extracts key insights: context preservation, handoff mechanisms, self-improvement patterns
3. Generates research report at:
   `Obsidian: agents/orchestrator/research/YYYY-WWW.md`
4. Proposes specific workflow changes based on research
5. Updates `agents/orchestrator/learnings.md` with research-triggered changes

**Research Sources:**
- AutoGen Paper (arxiv:2308.00352)
- CrewAI Blog
- LangGraph Docs
- Swarm Paper (arxiv:2408.07978)
- Reflexion Paper (arxiv:2303.11381)
- Self-Refine Paper (arxiv:2303.17651)

---

### 3. Watchdog Heartbeat Monitor

**Schedule:** Every 60 seconds (systemd service `karios-watchdog.service`)

**Command:** `python3 /usr/local/bin/agent-watchdog.py --daemon`

**Status:** `systemctl status karios-watchdog` — **active (running)**

**What it does:**
1. Checks `/var/lib/karios/heartbeat/<agent>.beat` for all 6 agents
2. If any agent's heartbeat is **>120 seconds old** → writes incident to monitor's inbox
3. If any agent's heartbeat is **>300 seconds old** → Telegram alert to Sai
4. Writes incident to `state.json` (monitor_agent.incidents)
5. Logs to `/var/log/karios-watchdog.log`

**Heartbeat Writer:** `python3 /usr/local/bin/agent-heartbeat.py` (or `/usr/local/bin/agent-heartbeat-wrapper.sh` for background 30s pings)

**Every agent MUST** write heartbeat at the **start of every session.**

---

## Full Feature Pipeline

The complete workflow for a single feature (e.g., BG-01: CPU/RAM morphing):

```
┌─────────────────────────────────────────────────────────────────┐
│ STEP 1: Orchestrator assigns to Backend                          │
│  → agent msg send backend "BG-01: CPU/RAM morphing"             │
│     --context packet with full task spec                        │
└───────────────────────────┬─────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ STEP 2: Backend implements                                       │
│  → Reads coordination files (api-contract, decisions, blockers)   │
│  → Implements morph.go with unit tests                          │
│  → golangci-lint passes, go test ./... passes                   │
│  → Creates PR, assigns saihruthik as reviewer                   │
│  → Writes self-critique: learnings/critiques/backend/...        │
│  → Updates state.json                                          │
└───────────────────────────┬─────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ STEP 3: PR merged (webhook → Redis event: backend:merged)        │
│  → Orchestrator reads event, assigns DevOps                     │
│  → agent msg send devops "BG-01 merged. Deploy to 3 nodes."    │
│     --context packet with: SHA, branch, what changed            │
└───────────────────────────┬─────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ STEP 4: DevOps deploys                                           │
│  → Pulls latest, builds binary                                  │
│  → Backs up current on all 3 nodes                              │
│  → SCP binary to all 3 mgmt nodes                               │
│  → systemctl restart on all 3 nodes (parallel)                 │
│  → Wait 5s, health check all 3 nodes                           │
│  → If any fail: rollback all 3, alert orchestrator              │
│  → If all pass: update deployment.json                         │
│  → agent msg send tester "BG-01 deployed. SHA abc123. E2E."     │
│  → agent msg send orchestrator "BG-01 deployed successfully"   │
│  → Writes self-critique: learnings/critiques/devops/...        │
└───────────────────────────┬─────────────────────────────────────┘
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ STEP 5: Tester runs E2E                                          │
│  → cd karios-playwright && npx playwright test                   │
│  → PASS: agent msg send orchestrator "BG-01 E2E: PASSED"       │
│          Writes test-results.json                               │
│          Orchestrator notifies Sai via Telegram                  │
│  → FAIL: agent msg send orchestrator "BG-01 E2E: FAILED"       │
│          agent msg send backend "FG-01 E2E failed: <reason>"   │
│          Writes failure report to Obsidian                      │
│  → Writes self-critique: learnings/critiques/tester/...        │
└─────────────────────────────────────────────────────────────────┘
```

---

## Alerting & Sai Notification

### Telegram Bot

**Bot:** `@Migrator_hermes_bot`
**Token:** `<REDACTED-TELEGRAM-BOT-TOKEN>`
**Chat ID:** `6817106382` (Sai Hruthik)

**When Sai is notified:**
| Trigger | Priority | Message Example |
|---------|----------|----------------|
| Feature E2E passed | Normal | `[BG-01] E2E PASSED — CPU morphing ready for production` |
| Feature E2E failed | High | `[BG-01] E2E FAILED — 3 tests failing. Routing back to backend.` |
| Agent DOWN >5min | Critical | `[WATCHDOG] Agent DOWN: backend — no heartbeat for 6 minutes` |
| Deployment failed | Critical | `[DEVOPS] DEPLOYMENT FAILED: backend on node 192.168.118.106` |
| System maintenance | High | `System going down for maintenance in 15 minutes` |

**Script:** `/var/lib/karios/orchestrator/telegram-status.sh`

---

## System Startup

### To Start All Services

```bash
# Watchdog (health monitoring) — ALWAYS RUNNING
systemctl enable --now karios-watchdog

# Orchestrator (event dispatcher)
systemctl enable --now karios-orchestrator-sub

# All 5 worker agents (each reads its inbox independently)
systemctl enable --now karios-backend-worker
systemctl enable --now karios-frontend-worker
systemctl enable --now karios-devops-agent
systemctl enable --now karios-tester-agent
systemctl enable --now karios-monitor-worker
```

### To Check System Health

```bash
# Watchdog status
systemctl status karios-watchdog

# All agent heartbeats
python3 /usr/local/bin/agent-watchdog.py

# Individual agent inbox
HERMES_AGENT=backend agent msg read --unread
HERMES_AGENT=devops agent msg status

# Orchestrator state
cat /var/lib/karios/coordination/state.json | python3 -m json.tool

# Crontab (synthesizer + research + cleanup)
crontab -l
```

### Cron Jobs Installed

```
# Daily Learning Synthesizer (midnight UTC)
0 0 * * * root /usr/local/bin/synthesize-learnings.py >> /var/log/karios-synthesizer.log 2>&1

# Weekly Research Loop (Sunday 02:00 UTC)
0 2 * * 0 root /usr/local/bin/orchestrator-research.py >> /var/log/karios-research.log 2>&1

# Context Bus Cleanup (daily 03:00, prune old packets after 7 days)
0 3 * * * root find /var/lib/karios/context-bus/packets -name "*.json" -mtime +7 -delete 2>/dev/null
0 3 * * * root find /var/lib/karios/agent-msg/inbox -name "*.json" -mtime +7 -delete 2>/dev/null
```

---

## Key Design Decisions

These are **immutable rules** — do not break them without updating this document.

| ID | Rule | Rationale |
|----|------|-----------|
| DEC-01 | Every handoff = full Context Packet | Eliminates context loss |
| DEC-02 | Context packets archived to Obsidian | Durable, survives Redis flush |
| DEC-03 | Redis for ephemeral signals only | Not the source of truth |
| DEC-04 | Deploy to ALL 3 nodes, never just one | Consistent state across cluster |
| DEC-05 | Health check after every restart | Catch failures before moving forward |
| DEC-06 | Rollback on any node failure | Never leave cluster in inconsistent state |
| DEC-07 | Self-critique after every task | Feeds daily synthesizer |
| DEC-08 | Heartbeat at start of every session | Watchdog depends on it |
| DEC-09 | No agent does another agent's work | Clear ownership, no stepping on toes |
| DEC-10 | Orchestrator is beat/keeper, not implementer | Focus on coordination, not code |

---

## File Inventory

### Agent Profiles

| Agent | Profile Path |
|-------|-------------|
| Orchestrator | `/root/.hermes/profiles/orchestrator-agent.hermes` |
| Backend | `/root/.hermes/profiles/backend-worker.hermes` |
| Frontend | `/root/.hermes/profiles/frontend-worker.hermes` |
| DevOps | `/root/.hermes/profiles/devops-agent.hermes` |
| Tester | `/root/.hermes/profiles/tester-agent.hermes` |
| Monitor | `/root/.hermes/profiles/monitor-worker.hermes` |

### CLI Tools

| Tool | Path | Purpose |
|------|------|---------|
| `agent msg` | `/usr/local/bin/agent msg` | Agent-to-agent messaging |
| `agent-heartbeat.py` | `/usr/local/bin/agent-heartbeat.py` | Write heartbeat |
| `agent-heartbeat-wrapper.sh` | `/usr/local/bin/agent-heartbeat-wrapper.sh` | Background heartbeat pinger (30s) |
| `agent-watchdog.py` | `/usr/local/bin/agent-watchdog.py` | Watchdog daemon + CLI |
| `synthesize-learnings.py` | `/usr/local/bin/synthesize-learnings.py` | Daily synthesizer |
| `orchestrator-research.py` | `/usr/local/bin/orchestrator-research.py` | Weekly research |

### Systemd Services

| Service | Path | Purpose |
|---------|------|---------|
| `karios-watchdog.service` | `/etc/systemd/system/karios-watchdog.service` | Watchdog daemon |
| `karios-orchestrator-sub.service` | (service file in orchestrator dir) | Orchestrator event loop |

### Coordination Files

| File | Path |
|------|------|
| State | `/var/lib/karios/coordination/state.json` |
| API Contract | `/var/lib/karios/coordination/api-contract.json` |
| Decisions | `/var/lib/karios/coordination/decisions.json` |
| Blockers | `/var/lib/karios/coordination/blockers.json` |
| UI Patterns | `/var/lib/karios/coordination/ui-patterns.json` |
| Deployment | `/var/lib/karios/coordination/deployment.json` |
| Test Results | `/var/lib/karios/coordination/test-results.json` |

### Obsidian Vault

| Document | Path |
|----------|------|
| **This Document** | `agents/orchestrator/multi-agent-architecture.md` |
| Orchestrator Index | `agents/orchestrator/index.md` |
| Orchestrator Memory | `agents/orchestrator/memory.md` |
| Orchestrator Learnings | `agents/orchestrator/learnings.md` |
| Backend Index | `agents/backend/index.md` |
| Frontend Index | `agents/frontend/index.md` |
| DevOps Index | `agents/devops/index.md` |
| Tester Index | `agents/tester/index.md` |
| Monitor Index | `agents/monitor/index.md` |
| Agent Hub | `agents/index.md` |
| Daily Synthesized | `agents/orchestrator/synthesized/YYYY-MM-DD.md` |
| Weekly Research | `agents/orchestrator/research/YYYY-WWW.md` |

---

## Change Log

| Date | Version | Changes |
|------|---------|---------|
| 2026-04-15 | 1.0 | Initial architecture — 6 agents, context packet protocol, watchdog, synthesizer, research loop |

---

## Related Documents

- [[agents/orchestrator/index|Orchestrator Hub]]
- [[agents/backend/index|Backend Worker Hub]]
- [[agents/frontend/index|Frontend Worker Hub]]
- [[agents/devops/index|DevOps Agent Hub]]
- [[agents/tester/index|Tester Agent Hub]]
- [[agents/monitor/index|Monitor Worker Hub]]
- [[agents/index|Agent System Hub]]
- `coordination/state.json` — State Tracking
- `coordination/decisions.json` — Architectural Decisions
- `/var/lib/karios/agent-msg/SPEC.md` — Communication Protocol SPEC
