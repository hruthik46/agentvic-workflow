# KAIROS Multi-Agent Pipeline — Agentic Workflow

This repo is the **disaster-recovery + replication source of truth** for the KAIROS 9-agent pipeline running on `192.168.118.106`. If the live cluster is destroyed, every file needed to rebuild it is here.

**Live status (2026-04-19 night)**: v7.6 deployed, grade ~9.5/10. v11 closed all 6 phases naturally including autonomous `[PROD-DEPLOYED]`.

---

## What this is

A 9-agent recursive-self-improvement pipeline built on:
- **Hermes Agent v0.9.0** as the LLM runtime per agent (MiniMax-M2.7 backend)
- **Redis Streams** (`stream:orchestrator`, `stream:<agent>-worker`) for inter-agent messaging with `MessageEnvelope` v7 idempotency + DLQ + exponential backoff
- **Obsidian vault** at `/opt/obsidian/config/vaults/My-LLM-Wiki/raw/karios-pipeline/` as cross-agent shared memory
- **Telegram channel `Hermes`** (id `-1003999467717`) for human-visible phase-transition notifications
- **Gitea** (`gitea.karios.ai`) for autonomous code push from agents
- **code-review-graph MCP server** (`uvx code-review-graph serve`) for 8.2× token reduction on code-touching tasks
- **Per-agent session-flush policy** (always-fresh blind-testers, event-flush devops/tester, sliding-window monitor)

The 9 agents:
1. **orchestrator** — dispatches phases, runs gates, fans out/in
2. **architect** — Phase 1 research + Phase 2 architecture design
3. **architect-blind-tester** — Phase 2 adversarial review (always-fresh sessions)
4. **backend** — Phase 3 backend coding (Go/Python)
5. **frontend** — Phase 3 frontend coding (React)
6. **devops** — Phase 5 deploy to .106 cluster + push to Gitea
7. **tester** — Phase 4 functional tests
8. **code-blind-tester** — Phase 4 adversarial E2E (always-fresh sessions)
9. **monitor** — Phase 6 24h post-deploy watch

The 6 phases:
| # | Phase | Owner | Gate | Telegram |
|---|---|---|---|---|
| 1 | Research | architect | quality ≥ 7 + ≥5 sources + ≥3 frameworks | — |
| 2 | Architecture | architect | architect-blind-tester rating ≥ 8 | ✅ ARCH-REVIEWED |
| 3 | Coding | backend + frontend (parallel) | both compile + lint + integration ✓ | ✅ CODING-COMPLETE (FAN-IN) |
| 4 | E2E Testing | tester + code-blind-tester | code-blind-tester rating ≥ 8 | ✅ E2E-RESULTS |
| 5 | Deploy | devops | all 3 mgmt nodes healthy + Gitea push verified | ✅ STAGING/PROD-DEPLOYED |
| 6 | Monitor | monitor | 24h, no incidents | ✅ MONITORING-COMPLETE |

Per-iteration rating gate is **8/10**, not 10/10. K_max iterations per phase: 5/3/3 (Phase 2/3/4). After K_max, gap escalates with Telegram alert.

---

## Repo layout

```
agentic-workflow/
├── README.md                       — this file
├── DISASTER-RECOVERY.md            — fresh-node bootstrap runbook
├── HISTORY.md                      — v6 → v7.6 timeline + every patch
├── pipeline/
│   ├── orchestrator/
│   │   ├── event_dispatcher.py     — main orchestrator (47 patches over 6 meta-loop rounds)
│   │   ├── message_schemas.py      — v7.6 Pydantic schemas at message boundary
│   │   └── state.json              — example state (sanitized; v9-v11 completed gaps)
│   ├── bin/
│   │   ├── agent-worker            — Hermes wrapper with PTY watchdog (v7.6 Item E) + code-review-graph rubric (Item C) + vault context injection
│   │   ├── karios-vault            — symlink → obsidian_bridge.py
│   │   ├── karios-merge-resolve    — git conflict resolver with vault lookup + blacklist enforcement
│   │   ├── karios-flush-decide     — session-flush policy helper
│   │   ├── karios-meta-runner      — golden-seed git tags + held-out 20% eval
│   │   ├── karios-dlq              — DLQ management CLI
│   │   ├── karios-contract-test    — 5-test invariant check (runs every 5 min via timer)
│   │   ├── karios-hitl-listener    — single Telegram poller (avoids 9× HTTP 409)
│   │   ├── karios-self-test        — pipeline health-check CLI
│   │   ├── obsidian_bridge.py      — vault read/write API + CLI
│   │   ├── sop_engine.py           — SOP engine with v7.3 postcondition fix
│   │   ├── a2a_protocol.py         — JSON-RPC 2.0 server on port 8090
│   │   ├── agent-watchdog.py       — two-tier process+heartbeat probes
│   │   ├── agent-heartbeat.py      — per-agent heartbeat writer
│   │   ├── agent-checkpoint        — phase-boundary checkpoint writer
│   │   └── agent-stream-progress   — streaming progress markers
│   ├── systemd/                    — 15 .service unit files (one per agent + watchdog + a2a + listener + contract-test)
│   ├── hermes/
│   │   ├── config.yaml             — global Hermes config (tool_use_enforcement: true is the v7.5 fix)
│   │   └── profiles/<agent>/{config.yaml, SOUL.md} — per-agent profile + role doc
│   ├── etc/
│   │   ├── secrets.env.example     — template for /etc/karios/secrets.env (REDACTED)
│   │   └── flush-policy.yaml       — per-agent session-flush rules
│   └── install/                    — bootstrap scripts (see DISASTER-RECOVERY.md)
├── knowledge/
│   ├── PIPELINE-KNOWLEDGE.md       — master narrative covering v6→v7.6, all 47 patches, every lesson
│   ├── architecture/               — multi-agent-architecture v6 / v7.3 + change logs + incident log
│   └── karios-pipeline/            — complete obsidian vault snapshot
│       ├── decisions/              — DEC-04 through DEC-17 (cross-agent decision records)
│       ├── rca/                    — every RCA captured during meta-loops
│       ├── critiques/              — auto-written agent self-critiques (every Hermes session)
│       ├── learnings/              — explicit learning entries
│       ├── fixes/                  — applied-fix log
│       ├── bugs/                   — bug reports
│       └── memory/                 — long-term memory keys (excludes session-flush briefs)
├── meta-loop/
│   └── inputs/                     — every ARCH-IT-ARCH-vN.md requirement that drove a meta-loop iteration
└── iteration-tracker/
    ├── ARCH-IT-ARCH-v9/            — Phase 2-6 artifacts (5 docs + review.json + e2e-results.json + decomposition.json)
    ├── ARCH-IT-ARCH-v10/
    └── ARCH-IT-ARCH-v11/
```

---

## How to talk to the live pipeline

5 ways in (lowest to highest coupling):

1. **Telegram channel `Hermes`** (`-1003999467717`) — read-only for Sai, every `notify_phase_transition()` lands here.
2. **`ssh root@192.168.118.106` + `journalctl -u karios-orchestrator-sub -f`** — live event stream.
3. **`karios-vault search "<keywords>"`** / `karios-vault recent --kind rca|critique|decision|fix` — query cross-agent knowledge.
4. **`/var/lib/karios/agent-msg/inbox/orchestrator/<file>.json`** — drop a JSON packet, dispatcher consumes within 2s. Bad JSON quarantined to `/var/lib/karios/agent-msg/quarantine/`.
5. **`redis-cli -h 192.168.118.202 --user karios_admin --pass <REDACTED> XADD stream:orchestrator '*' from X subject "[...]" body "..."`** — fully-formed envelope injection (matches what real agents produce).

Plus: A2A JSON-RPC on port 8090, HITL listener accepts `/help` `/status` from the Telegram channel, iteration-tracker filesystem at `/var/lib/karios/iteration-tracker/<gap_id>/`.

---

## Where to start reading

- **For "how do I rebuild this on a fresh node"** → [DISASTER-RECOVERY.md](DISASTER-RECOVERY.md)
- **For "how did we get here"** → [HISTORY.md](HISTORY.md)
- **For "what did each meta-loop round teach us"** → [knowledge/PIPELINE-KNOWLEDGE.md](knowledge/PIPELINE-KNOWLEDGE.md)
- **For "what is the actual code"** → [pipeline/orchestrator/event_dispatcher.py](pipeline/orchestrator/event_dispatcher.py) + [pipeline/bin/agent-worker](pipeline/bin/agent-worker)
- **For "what gaps remain"** → bottom of [knowledge/PIPELINE-KNOWLEDGE.md](knowledge/PIPELINE-KNOWLEDGE.md) ("What's Still Rough")

---

## Status as of 2026-04-19 night

- **Live**: v7.6 (47 patches over 6 meta-loop rounds)
- **Grade**: ~9.5/10. Items A/C/D/E live; B (BG-stub-no-op self-test) and F (Anthropic `tool_choice: any` passthrough) deferred with explicit reasons.
- **Last natural full traversal**: ARCH-IT-ARCH-v11 closed all 6 phases at 21:26 EDT. devops emitted `[PROD-DEPLOYED]` autonomously — first time in 6 meta-loops.
- **Real autonomous gitea PRs opened by agents**: `karios-migration` PR #1 (v11), commits `c6e1bb4` and `bf6775f6` (v10 architect-driven).
