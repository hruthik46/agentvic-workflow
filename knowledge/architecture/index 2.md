---
title: Orchestrator Agent
type: agent
subtype: orchestrator
tags: [agent, orchestrator, telegram, redis, coordination]
created: 2026-04-14
updated: 2026-04-15
systemd: karios-orchestrator-sub.service
access: {level: full, vault_path: /opt/obsidian/config/vaults/My-LLM-Wiki/wiki}
---

# Orchestrator Agent

The Orchestrator is the central coordination agent. It dispatches tasks to specialized agents, tracks state, monitors events, and is the single source of truth for the agent system's health.

**It is the only agent that:**
- Reads and writes ALL coordination files
- Subscribes to Redis pub/sub events
- Sends Telegram messages to Sai
- Decides task sequencing based on `blockers.json`

**All other agents report to the Orchestrator, not to each other.**

---

## Agent Identity

| Field | Value |
|-------|-------|
| Service | `karios-orchestrator-sub.service` |
| Telegram bot | `@Migrator_hermes_bot` |
| Chat ID | `6817106382` (Sai Hruthik) |
| Redis channel | `migration/events` |
| Coordination dir | `/var/lib/karios/coordination/` |
| Vault access | Full read/write — `/opt/obsidian/config/vaults/My-LLM-Wiki/wiki/agents/` |

---

## How It Works

```
Sai (Telegram)
    |
    v
@Migrator_hermes_bot  -->  Hermes Gateway  -->  Orchestrator (event_dispatcher.py)
    |                                              |
    |                                              +--> Backend Worker (systemd)
    |                                              +--> Frontend Worker (systemd)
    |                                              +--> DevOps Agent (systemd)
    |                                              +--> Tester Agent (systemd)
    |                                              +--> Monitor Agent (systemd)
    |
    v
State written to /var/lib/karios/coordination/state.json
Docs written to /opt/obsidian/.../wiki/agents/<type>/
```

---

## Commands (Telegram)

| Command | Action |
|---------|--------|
| `/start` | Begin orchestrator |
| `/status` | Full system status |
| `/list` | List all tasks |
| `/assign <task-id>` | Manually assign a task |
| `/block <task-id>` | Mark task blocked |
| `/done <task-id>` | Mark task done |
| `/pr <agent>` | Show latest PR from agent |
| `/incident` | Report an incident |
| `/pause` | Pause all agents |
| `/resume` | Resume all agents |

---

## Owned Coordination Files

The Orchestrator owns these files — other agents READ them, Orchestrator WRITES them:

- `state.json` — current system state, updated after every event
- `blockers.json` — feature dependency graph, updated when blocks change
- `decisions.json` — architectural decisions (append-only)

## Maps (Index)

The Orchestrator maintains indexes to all agent documents:

- Memory — persistent cross-session state
- Learnings — patterns discovered over time
- Config — agent system configuration

## Sub-Agents It Coordinates

- [[agents/backend/index|Backend Worker]] — Go implementation
- [[agents/frontend/index|Frontend Worker]] — React/TypeScript UI
- [[agents/devops/index|DevOps Agent]] — deployment
- [[agents/tester/index|Tester Agent]] — Playwright E2E
- [[agents/monitor/index|Monitor Agent]] — health + incidents

## Related

- [[agents/index|Agent System Overview]]
- `state.json` (coordination)
- `blockers.json` (coordination)
