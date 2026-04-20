# META-LOOP TASK

You are improving the KAIROS multi-agent pipeline ARCHITECTURE itself.
The current architecture is included verbatim below. Your job: identify the
next-most-impactful improvement, propose it as a DELTA (not a full rewrite),
and produce the 5 architecture deliverables (architecture.md, edge-cases.md,
test-cases.md, api-contract.md, deployment-plan.md) describing the change.

META-SAFETY CONSTRAINTS — do NOT violate:
  T0 (free):    generated artifacts, code in karios-migration / karios-web
  T1 (canary):  agent prompts, dispatcher logic, packet schema
  T2 (HITL):    the rubric itself, blind-tester prompt, stop conditions, this safety harness

If your proposed change is T2, mark it `requires_hitl: true` and stop without applying.

Persistence: write your reasoning + critique + RCA via:
  /usr/local/bin/karios-vault learning|critique|rca|decision  ...
Every entry lands in the Obsidian vault and syncs to Sai's Mac via Relay.

Pre-iteration golden tag (use `karios-meta-runner rollback karios-v6-iter-2-pre` to revert): karios-v6-iter-2-pre

---

## Current architecture (the input you are improving)

# Multi-Agent Architecture v3.0

**System**: Karios Migration — 7 Hermes agents running 24/7 on Linux
**Architecture Version**: 3.0 (upgraded from 2.0 on 2026-04-17)
**Status**: Live — All 10 SOTA improvements implemented and deployed

---

## Overview

The Karios Migration system runs 8 autonomous services that coordinate via:
- **Redis Streams** (`stream:orchestrator`) — primary message transport, event-driven (XREADGROUP)
- **Redis Pub/Sub** (`gap.*`, `agent.*`, `deploy.*`, `agent.stream`) — event notifications
- **Obsidian** (`/opt/obsidian/config/vaults/My-LLM-Wiki/wiki`) — durable knowledge, context packets, learnings
- **`agent-msg` CLI** (`/usr/local/bin/agent-msg`) — peer-to-peer messaging with `banned_from` enforcement

Every agent has its own Obsidian workspace: `wiki/agents/<agent>/index.md`

---

## v3.0 Major Changes from v2.0

1. **Redis Streams** replaced polling `brpop()` with `XREADGROUP` (true event-driven)
2. **Structured Trace IDs** on every message, event, and checkpoint
3. **Persistent Checkpointing** at every phase boundary (crash recovery)
4. **Real-Time Streaming** via `agent.stream` pub/sub channel
5. **Dynamic Routing** based on rating quality (3 tiers)
6. **GitHub Webhook** auto-deploy on PR merge (port 8087)
7. **Cross-Session Agent Memory** (90-day learnings store)
8. **Parallel Gap Pipeline** (Architect pre-researches next gap)
9. **Hierarchical Fan-Out** (auto-decompose large features)
10. **8 services** (added `karios-github-webhook`)

---

## The 8 Services

| Service | Binary | Role | Phase Ownership |
|---------|--------|------|----------------|
| [[orchestrator/index|Orchestrator]] | `event_dispatcher.py` v3.0 | Central coordinator | All phases |
| [[backend/index|Backend]] | `agent-worker` v3.0 | Go backend implementation | Phase 3 (coding) |
| [[frontend/index|Frontend]] | `agent-worker` v3.0 | React frontend implementation | Phase 3 (coding) |
| [[devops/index|DevOps]] | `agent-worker` v3.0 | Deploy/rollback/redeploy | Phase 3, 4 |
| [[tester/index|Tester]] | `agent-worker` v3.0 | Blind architecture review + E2E | Phase 2, 3 |
| [[monitor/index|Monitor]] | `agent-worker` v3.0 | Health, incidents, alerting | All (observe) |
| [[architect/index|Architect]] | `agent-worker` v3.0 | Research + architecture design | Phase 1, 2 |
| `karios-github-webhook` | `github-webhook-server.py` | GitHub webhook receiver | External trigger |

---

## Architecture Diagram (v3.0)

```
                    ┌─────────────────────────────────────────────────────────────────────┐
                    │                         GitHub / External                             │
                    │                     POST /webhook (port 8087)                      │
                    └──────────────────────────┬──────────────────────────────────────┘
                                               │
                    ┌──────────────────────────▼──────────────────────────────────────┐
                    │            stream:orchestrator (Redis Stream)                    │
                    │         XADD on every message, XREADGROUP consumers               │
                    │                                                                      │
                    │  ┌──────────────────┐  ┌─────────────────────┐                  │
                    │  │orchestrator-cg   │  │  agent-cg-<name>    │                  │
                    │  │ XREADGROUP       │  │  XREADGROUP (per     │                  │
                    │  │ (1 consumer)     │  │  agent, 1 each)     │                  │
                    │  └────────┬─────────┘  └──────────┬──────────┘                  │
                    └───────────┼─────────────────────────┼────────────────────────────┘
                                │                         │
              ┌─────────────────▼─────────┐    ┌─────────▼─────────────────────────────┐
              │   Orchestrator             │    │  Legacy inbox:* (backwards compat)  │
              │   event_dispatcher.py      │    │  rpush/blpop (v2.x agents)          │
              │   v3.0 (event-driven)     │    └──────────────────────────────────────┘
              └─────────────┬──────────────┘
                            │
        ┌──────────────────┼──────────────────────────────────────────────────┐
        │                  │                    Redis Pub/Sub                       │
        │                  │  gap.* | agent.* | test.* | deploy.* | agent.stream │
        │                  ▼                                                     │
        │  ┌──────────────────────────────────────────────────────────────┐   │
        │  │              Monitor (agent-monitor-pubsub.py)              │   │
        │  │  Subscribes to all 9 channels. Forwards critical events      │   │
        │  │  to Telegram. agent.stream → Telegram (rate-limited).        │   │
        │  └──────────────────────────────────────────────────────────────┘   │
        │                                                                     │
        │  ┌─────────┬─────────┬─────────┬─────────┬─────────┬─────────┐       │
        │  │Architect│ Backend │Frontend │  DevOps │ Tester  │ Monitor│       │
        │  │ Worker  │ Worker  │ Worker  │  Agent  │ Worker  │ Worker │       │
        │  └────┬────┴────┬────┴────┬────┴────┬────┴────┬────┴────┬─────┘       │
        └───────┼─────────┼─────────┼─────────┼─────────┼─────────┼──────────────┘
                │         │         │         │         │         │
                ▼         ▼         ▼         ▼         ▼         │
           /var/lib/karios/checkpoints/<agent>/<gap_id>/           │
           (Durable phase checkpoints — crash recovery)               │
                │         │         │         │         │
                └─────────┴─────────┴─────────┴─────────┘
                            │
                ┌───────────▼───────────────────────────────────┐
                │  /var/lib/karios/coordination/               │
                │  learnings.json (cross-session memories)       │
                │  decisions.json (immutable arch rules)         │
                │  blockers.json (wave-based feature gating)     │
                │  event-log.jsonl (all pub/sub events)         │
                │  state.json (orchestrator state)               │
                └───────────────────────────────────────────────┘
                            │
                ┌───────────▼───────────────────────────────────┐
                │  /opt/obsidian/.../My-LLM-Wiki/wiki/         │
                │  wiki/agents/<agent>/context-packets/        │
                │  (Durable handoff archives per agent)          │
                └───────────────────────────────────────────────┘
```

---

## Message Flow

### v3.0: Redis Streams (Primary)

```
Agent → XADD stream:orchestrator → Orchestrator XREADGROUP
         Orchestrator → XADD → Agent XREADGROUP
         Acknowledged with XACK after processing
```

### Legacy: Redis inbox queues (Backward Compatible)

```
Agent → rpush inbox:<agent> → Worker blpop/polling
```

### Events: Redis Pub/Sub (Monitor only)

```
Orchestrator → PUBLISH gap.* | agent.* | deploy.* | agent.stream → Monitor
```

---

## Enforcement at `agent-msg` CLI

The `can_send()` function in `/usr/local/bin/agent-msg` enforces Agent Card constraints at send-time:

```
backend     → tester       BLOCKED (banned_from: ["tester","frontend"])
frontend    → tester       BLOCKED (banned_from: ["tester","backend"])
devops      → tester       BLOCKED (banned_from: ["tester"])
tester      → backend      BLOCKED (banned_from: ["backend","frontend","devops"])
tester      → frontend     BLOCKED (banned_from: ["backend","frontend","devops"])
tester      → devops       BLOCKED (banned_from: ["backend","frontend","devops"])
monitor     → anyone       ALLOWED (no banned_from)
orchestrator → anyone      ALLOWED (no banned_from)
architect   → anyone       BLOCKED except orchestrator
```

All blocked messages are logged to `/var/lib/karios/coordination/state.json:blocked_messages_log[]`.

---

## Dual-Loop Pipeline (Phase 0-4)

```
Requirement (Sai via Telegram OR GitHub webhook)
    ↓
PHASE 0: Requirement parsed → REQ-<id>.md → gap created
    ↓
PHASE 1: Research (Architect) ← PARALLEL: can start next gap N+1 research
    Web search + manual infra testing → [RESEARCH-COMPLETE]
    ↓
PHASE 2: Architecture Loop (Architect ↔ Architect-Blind-Tester)
    5 docs → Orchestrator → AB-Tester → rating → Dynamic Routing
    Max 10 iterations, 10/10 required
    Dynamic Routing: >=9 fast-track, <4 immediate escalate, <7 self-diag
    ↓
PHASE 3: Coding Loop (Fan-Out Backend+Frontend ↔ Code-Blind-Tester)
    Architecture gate passed → FAN-OUT to Backend AND Frontend simultaneously
    Both work in parallel → [FAN-IN] each → Orchestrator waits for BOTH
    → [API-SYNC] Gate: both agents confirm API contract alignment
    → DevOps capacity check: if busy, deploy is queued
    → DevOps deploys to staging
    → Code-Blind-Tester E2E
    Max 10 iterations, dynamic routing applies
    ↓
PHASE 4: Production
    DevOps deploys → Code-Blind-Tester final validation → Sai notified
    → Architect starts PARALLEL pre-research on next gap
```

---

## Fan-Out / Fan-In (Google ADK Pattern)

```
Architecture 10/10 gate passed
    ↓
FAN-OUT: Backend + Frontend get tasks in PARALLEL
    ↓                                      ↓
[BACKEND: implements]    [FRONTEND: implements]
    ↓                                      ↓
[BACKEND: FAN-IN]        [FRONTEND: FAN-IN]
    ↓
FAN-IN COMPLETE (orchestrator waits for BOTH)
    ↓
API-SYNC gate (both confirm alignment)
    ↓ (DevOps not busy)
DevOps deploys to staging
    ↓
Code-Blind-Tester E2E
    ↓
Rating >= 10/10 → Phase 4 Production
Rating < 10/10 → FAN-OUT again for fixes
```

Both agents send `[FAN-IN] <gap_id>` when done. Orchestrator tracks pending completions in `/var/lib/karios/orchestrator/fan-state.json` (loaded on restart for crash recovery).

---

## Redis Streams Consumer Groups

8 consumer groups on `stream:orchestrator`:

| Group | Consumer | Purpose |
|-------|----------|---------|
| `orchestrator-consumers` | event_dispatcher.py | Primary orchestrator inbox |
| `agent-consumers-architect` | architect agent | Architect inbox |
| `agent-consumers-backend` | backend agent | Backend inbox |
| `agent-consumers-frontend` | frontend agent | Frontend inbox |
| `agent-consumers-devops` | devops agent | DevOps inbox |
| `agent-consumers-tester` | tester agent | Tester inbox |
| `agent-consumers-monitor` | monitor agent | Monitor inbox |

---

## Coordination Files

- [[decisions.json]] — immutable architectural rules (DEC-001 through DEC-053)
- [[blockers.json]] — wave-based feature dependency graph
- [[state.json]] — current system state
- [[learnings.json]] — cross-session agent learnings (v3.0)
- [[event-log.jsonl]] — all pub/sub events
- [[api-contract.json]] — backend API contract
- [[error-taxonomy.json]] — structured error classification

---

## Key Constraints

- **Orchestrator NEVER implements** — only routes, tracks, and mediates
- **Architect-Blind-Tester sees ONLY arch docs** — context stripped before routing
- **Code-Blind-Tester sees ONLY running system** — context stripped before routing
- **No iteration state in memory** — all state persisted to iteration-tracker/ and checkpoints/
- **All blocked messages logged** — audit trail in state.json:blocked_messages_log
- **Learnings stored for 90 days** — auto-pruned after TTL

---

## Systemd Services

| Service | Binary | Port |
|---------|---------|------|
| `karios-orchestrator-sub.service` | event_dispatcher.py v3.0 | — |
| `karios-architect-agent.service` | agent-worker | — |
| `karios-backend-worker.service` | agent-worker | — |
| `karios-frontend-worker.service` | agent-worker | — |
| `karios-devops-agent.service` | agent-worker | — |
| `karios-tester-agent.service` | agent-worker | — |
| `karios-monitor-worker.service` | agent-worker | — |
| `karios-github-webhook.service` | github-webhook-server.py | **8087** |

---

## Related

- [[orchestrator/index]] — Orchestrator agent docs (v5.0)
- [[orchestrator/v3-changes]] — Detailed v3.0 SOTA improvements
- [[orchestrator/v5-changes]] — v5.0 infrastructure bug fixes (RECOVER, STALLED, Hermes, consumer health)
- [[analyses/2026-04-18-v5-infrastructure-bug-fixes]] — Full RCA and fix documentation
- [[learnings]] — Cross-session agent learnings
- [[architect/index]] — Architect agent docs
- [[backend/index]] — Backend agent docs
- [[frontend/index]] — Frontend agent docs
- [[devops/index]] — DevOps agent docs
- [[tester/index]] — Tester agent docs
- [[monitor/index]] — Monitor agent docs
