# META-LOOP ITERATION 5 (ARCH-IT-ARCH-v10) — INPUT

You are improving the KAIROS multi-agent pipeline (v7.4 LIVE on .106).

## What v7.4 just shipped (verify before proposing changes)

1. **code-review-graph integrated**: 4 main repos have pre-built graph DBs. MCP server auto-starts via `.mcp.json`. Use `get_minimal_context(task="...")` FIRST to save 8-16x tokens. Skill at `/root/.hermes/skills/software-development/code-review-graph/`.
2. **Gitea push protocol** in agent prompts: `git pull --rebase` → push to `gitea.karios.ai/KariosD/<repo>`. Conflicts: `karios-merge-resolve <repo> <file>` consults vault.
3. **`.gitignore` blacklist** in all 4 repos blocking pipeline files (`*.hermes`, `karios-pipeline/`, `multi-agent-architecture*.md`, `ARCH-IT-ARCH*`, `iteration-tracker/`, `karios-meta-*`, etc) — pipeline-internal stays internal until Sai's personal repo is given.
4. **`[MONITORING-COMPLETE]` handler** added — Phase 6 gap closure now works.
5. **Iteration-level Telegram** — every `[ARCH-REVIEWED]` and `[E2E-RESULTS]` already triggers `notify_phase_transition` with score + handoff (architect-revise vs backend+frontend; backend-revise vs devops).
6. **Defensive KeyError handling** in `handle_arch_review` — bad JSON drops, doesn't crash orchestrator.
7. **Subject-kind detection** restricted to AGENT-APPROPRIATE subjects — no more mis-routing when prose mentions other subjects.

## Your task — Make v10 PRODUCTION READY and BATTLE-TESTED

A. **Tool-use enforcement at Hermes level**: round-3+4 architect produced 320K of prose without a single `write_file` call. Profile changes (HARD PRE-SUBMIT GATE) don't help because the gate IS a tool call. Propose Hermes-side fix:
   - watchdog kills Hermes if no tool call within first 30K output tokens
   - prompt template change: "FIRST run `karios-vault search ...`, THEN produce JSON, THEN write files. NO PROSE FIRST."
   - `--require-tool-use` Hermes flag (if exists)

B. **JSON schema validation at message boundary**: Pydantic-style. Agents validate before send. Orchestrator validates before processing. On schema violation: reject + return reason to sender. Apply to all subjects.

C. **End-to-end self-test**: design a `BG-stub-no-op` gap that runs through Phase 1-6 with measurable success per phase. Run it. Pipeline becomes self-validating.

D. **code-review-graph rubric**: was `get_minimal_context(...)` called by every agent that touches code in this iteration? Score per agent. Refuse advance if not.

E. **Gitea push verification**: after Phase 5 deploy, the gap's commit must be pushed to gitea.karios.ai. Verify via `git rev-list --left-right --count origin/<branch>...HEAD` returns 0/0. Refuse `[PROD-DEPLOYED]` otherwise.

F. **No telegram from human admin**: only `notify_phase_transition()` and pre-existing `telegram_alert()` calls inside dispatcher should fire. Sai will only see pipeline-driven messages.

## You have full vault visibility + code-review-graph

  /usr/local/bin/karios-vault search "<keywords>"   # cross-agent prior knowledge
  cd <repo> && uvx code-review-graph serve           # get_minimal_context, etc

Use them BEFORE writing prose.
---
title: "KAIROS Multi-Agent Architecture v7.3 — LIVE on 192.168.118.106"
type: architecture
tags: [agents, architecture, v7.3, idempotency, dlq, telegram, blind-tester, jsonfirst, vault-source-of-truth, session-flush, meta-loop]
date: 2026-04-19
status: active
version: "7.3"
agents: [orchestrator, architect, backend, frontend, devops, tester, monitor, architect-blind-tester, code-blind-tester]
---

# KAIROS Multi-Agent Architecture v7.3

> **Status:** Active | **Version:** 7.3 | **Date:** 2026-04-19 | **Cluster:** mgmt-2 (192.168.118.106)
>
> Supersedes [[multi-agent-architecture-v6|v6.0]] (2026-04-19 morning) and v7.0/v7.1/v7.2 incremental builds. **All 9 agents live. v7.3 dispatcher is the production binary at `/var/lib/karios/orchestrator/event_dispatcher.py`.**

---

## What lands in v7.3 (delta over v7.0 staging)

v7.0 was the autonomous proposal devops generated during the meta-loop. v7.1/v7.2/v7.3 layered live patches:

| Capability | Source | Status |
|---|---|---|
| `MessageEnvelope` + idempotency-key + DLQ + exponential backoff | v7.0 (devops-proposed) | LIVE in dispatcher |
| Subject aliases for agent-invented forms (`[ARCHITECTURE-COMPLETE]`, `[BLIND-E2E-RESULTS]`, `[E2E-COMPLETE]`, `[DEPLOYED-STAGING]`, `[PRODUCTION-DEPLOYED]`) | v7.3 patch | LIVE |
| **Telegram phase-transition notifications** — `notify_phase_transition()` fires on every `[ARCH-REVIEWED]`, `[E2E-RESULTS]`, `[STAGING-DEPLOYED]`, `[PROD-DEPLOYED]` with score + handoff target | v7.3 patch | LIVE |
| Architect profile **HARD PRE-SUBMIT GATE** — all 5 docs must be ≥2KB, no "placeholder" string, before `[ARCH-COMPLETE]` | v7.3 profile | LIVE |
| Both blind-tester profiles **STRICT OUTPUT CONTRACT** — JSON FIRST in fenced block, total <30K chars (avoids Hermes context exhaustion) | v7.3 profiles | LIVE |
| `sop_engine.check_pre_conditions` no longer requires output_files to exist on iter 1 (was blocking every dispatch) | v7.3 patch | LIVE |
| `load_gap` fallback to `state.json` when `metadata.json` missing | v7.3 patch | LIVE |
| `send_to_agent` `[PRODUCTION]` dispatch passes gap_id+trace_id kwargs (was None-XADD failure) | v7.3 patch | LIVE |
| `karios-flush-decide` invoked before every Hermes call; pre-flush vault brief written when action≠continue | v7.2 wiring | LIVE |
| Cross-Agent Vault Context injected into Hermes prompts (top-8 relevant entries) + CLI usage instructions | v7.2 wiring | LIVE |
| `obsidian_bridge` writes critique/bug/learning/rca/decision/fix/memory after every Hermes call | v6.0 hook | LIVE |
| Centralized Telegram listener (`karios-hitl-listener`) — only one process long-polls bot (was 9 → HTTP 409) | v6.0 | LIVE |
| 9 agents alive (architect-blind-tester + code-blind-tester were inactive; v6.0 systemd units brought them up) | v6.0 | LIVE |
| `karios-dlq` CLI (`list`, `replay`, `stats`, `trim`, `force-replay`) | v7.0 | LIVE |
| `karios-contract-test.timer` every 5 min (imports + streams + state consistency + heartbeats + SOPs) | v6.0 | LIVE |
| Two-tier watchdog probes (process + heartbeat-age + stream-progress) | v6.0 | LIVE |
| Meta-safety harness — golden-seed git tags, sandbox dry-run, held-out eval set | v6.0 | LIVE |

## The 9-agent topology

```
                                  ┌──────────────────────┐
                                  │  Orchestrator (v7.3) │
                                  │  • Idempotency SETNX │
                                  │  • DLQ on retry      │
                                  │  • Telegram on every │
                                  │    phase transition  │
                                  └─────┬────────────────┘
                                        │ MessageEnvelope
        ┌───────────┬───────────┬───────┼───────┬────────────┬─────────────┐
        ▼           ▼           ▼       ▼       ▼            ▼             ▼
   Architect   Backend    Frontend   DevOps   Tester    Monitor     Blind-testers
        │           │           │       │       │           │           ↑   ↑
        ▼           ▼           ▼       ▼       ▼           ▼           │   │
        └───────────┴───────────┴───────┴───────┴───────────┘           │   │
                              │ all write/read vault                    │   │
                              ▼                                         │   │
            /opt/obsidian/config/vaults/My-LLM-Wiki/                    │   │
              raw/karios-pipeline/                                       │   │
                ├── critiques/  (auto on every Hermes success)          │   │
                ├── bugs/       (auto on every Hermes failure)          │   │
                ├── rca/        (manual + contract-test fail)           │   │
                ├── learnings/                                          │   │
                ├── decisions/                                          │   │
                ├── fixes/                                              │   │
                ├── memory/     (incl. session_brief_pre_flush_*)       │   │
                └── context-packets/  (every handoff archived)          │   │
                                                                        │   │
       Phase 2 gate ────────────────────────────────────────────────────┘   │
       Phase 4 gate ────────────────────────────────────────────────────────┘
                              ALWAYS-FRESH per session-flush policy
```

## Telegram visibility (NEW in v7.3)

You now get notified at **every** phase transition with score + handoff:

```
🔍 [ARCH-REVIEWED] ARCH-IT-ARCH-v9 — score 8/10
Handing off: architect-blind-tester → backend+frontend (Phase 3)
  recommendation=APPROVE; v9 design addresses placeholder bug + JSON contract

🧪 [E2E-RESULTS] ARCH-IT-ARCH-v9 — score 9/10
Handing off: code-blind-tester+tester → devops (Phase 5 deploy)
  recommendation=APPROVE; all 7 dimensions ≥7

📦 [STAGING-DEPLOYED] ARCH-IT-ARCH-v9
Handing off: devops → tester+code-blind-tester (Phase 4 E2E)

🚀 [PROD-DEPLOYED] ARCH-IT-ARCH-v9
Handing off: devops → monitor (Phase 6 24h watch)
```

If the score is below 8 the handoff is back to the architect/coder for the next iteration.

## Session-flush policy (LIVE per v7.2)

| Agent | Strategy | Trigger |
|---|---|---|
| **architect-blind-tester** | `always_fresh` | every task — no `--resume` ever |
| **code-blind-tester** | `always_fresh` | every task |
| **devops** | `flush_after_event: deploy_complete` | event-driven |
| **tester** | `flush_after_event: test_run_complete` | event-driven |
| **monitor** | `sliding_window 50 events`, hard flush 4h | window + time |
| **architect / backend / frontend** | `flush_on_task_boundary` | task_id change |
| **orchestrator** | `summarize_and_restart at 50K tokens` | tokens |

Universal triggers: tokens > 50K, tool_calls > 30 without progress, idle > 30 min, wall > 2 h, loop detected, quality plateau Δ<0.05 over 3 cycles.

**Pre-flush vault brief**: when `karios-flush-decide` returns `flush` or `summarize`, agent-worker writes `obsidian_bridge.write_memory(key="session_brief_pre_flush_<ts>", value={trace_id, gap_id, phase, task_excerpt, continuity_hint})` to vault BEFORE invoking the new fresh Hermes session. Continuity preserved without context bloat.

## Vault as single source of truth (LIVE per v7.2)

Every Hermes prompt now includes a `## Cross-Agent Vault Context` section with top-8 most-relevant vault entries (kind, path, snippet) — searched against `(gap_id + phase + agent + task[:200])`.

Every prompt also includes CLI usage:
```
karios-vault search "<keywords>"
karios-vault recent --limit 10 --kind rca|critique|decision|fix
karios-vault recent --kind learning --agent backend
```

Vault writes also instrumented:
```
karios-vault learning --agent X --title T --body B --severity S --category C
karios-vault critique --agent X --task-id T --worked W... --failed F... --improve I... --for-next N...
karios-vault rca --incident-id I --symptom S --root-cause R --fix F --severity S
karios-vault bug --reporter X --summary S --severity S --repro-steps ... --expected E --actual A
karios-vault fix --agent X --file F --description D --commit C --addresses ...
karios-vault decision --decision-id D --title T --context C --decision D --consequences C
karios-vault memory --agent X --key K --value JSON
```

Auto-write hooks in agent-worker post every Hermes call.

## Phase pipeline + gates

| Phase | Owner | K_max | Gate | Telegram alert? |
|---|---|---|---|---|
| 1. Research | Architect | 3 | quality ≥ 7 + ≥5 sources + ≥3 frameworks | — |
| 2. Architecture | Architect | 5 | Architect-Blind-Tester score ≥ 8 + RESILIENCE pass | ✅ on `[ARCH-REVIEWED]` |
| 3. Implementation | Backend + Frontend (parallel) | 3 | both compile + lint + integration ✓ | — (FAN-IN logged) |
| 4. Testing | Tester + Code-Blind-Tester | 3 | code-blind-tester score ≥ 8 + ERROR_HANDLING pass | ✅ on `[E2E-RESULTS]` |
| 5. Deployment | DevOps | 1 | all 3 mgmt nodes healthy + HITL approve | ✅ on `[STAGING-DEPLOYED]` + `[PROD-DEPLOYED]` |
| 6. Monitor | Monitor | n/a | 24h, no incidents | ✅ on `[MONITORING-COMPLETE]` |

## What landed live this session (full timeline)

| Time | Event |
|---|---|
| `02:34` | Orchestrator deadlock surfaced — `block=0` regression |
| `02:36–02:40` | Triage: `block=0→100`, `\%s→%%s`, secrets to `/etc/karios/secrets.env`, blind-tester systemd units, A2A unit, watchdog v6.0 rewrite |
| `02:43` | Obsidian bridge + `karios-vault` CLI + auto-critique hook |
| `02:48` | Meta-runner + golden-seed git, ARCH-IT-ARCH-v6 dispatched (round 1) |
| `02:50–04:50` | **Round 1**: 11 dispatcher bugs surfaced and patched live; devops produced v7.0 (idempotency+DLQ); 1/6 phases natural |
| `06:32` | v6.0 architecture doc written to vault (15.4 KB) |
| `07:32` | Telegram chat_id rotated to Hermes channel `-1003999467717` |
| `07:37` | Centralized HITL listener — single Telegram poller |
| `11:30` | **v7.1 deployed** (v7.0 staging + 11 round-1 fixes) |
| `11:33` | **Round 2 (ARCH-IT-ARCH-v7)** dispatched on v7.1 — 5/6 natural advances |
| `12:33` | v7.2 wiring (flush-decide called, pre-flush brief, vault read in prompt); Round 3 (ARCH-IT-ARCH-v8) dispatched |
| `12:42` | Backend went off-script and worked on BG-01 using vault context — wrote real commit `d61853b` + 30 unit tests |
| `13:03` | **v7.3 deployed** (subject aliases, Telegram phase notifications, hard pre-submit gate, JSON-FIRST contract, SOP postcondition fix) |
| `13:06` | **Round 4 (ARCH-IT-ARCH-v9)** dispatched on v7.3 — in flight |

## Files on disk (cluster)

| Path | Purpose |
|---|---|
| `/var/lib/karios/orchestrator/event_dispatcher.py` | v7.3 dispatcher (md5 from current deploy) |
| `/usr/local/bin/agent-worker` | v7.2-patched (envelope unwrap + JSON extract + flush + vault read + auto-critique) |
| `/usr/local/bin/karios-hitl-listener` | Single Telegram poller |
| `/usr/local/bin/karios-a2a` (via systemd) | JSON-RPC 2.0 server on port 8090 |
| `/usr/local/bin/karios-watchdog.py` | v6.0 two-tier probes for 9 agents |
| `/usr/local/bin/karios-vault` | Symlink → `obsidian_bridge.py` CLI |
| `/usr/local/bin/karios-flush-decide` | Session-flush helper |
| `/usr/local/bin/karios-meta-runner` | Meta-safety harness (git tags, sandbox, held-out eval) |
| `/usr/local/bin/karios-dlq` | DLQ management CLI |
| `/usr/local/bin/karios-contract-test` | 5-test invariant check |
| `/usr/local/bin/sop_engine.py` | SOP engine (precondition fix) |
| `/etc/karios/secrets.env` | Telegram + Redis + A2A secrets (chmod 600) |
| `/etc/karios/flush-policy.yaml` | Per-agent session-flush policy |
| `/root/.hermes/profiles/architect-agent.hermes` | + HARD PRE-SUBMIT GATE |
| `/root/.hermes/profiles/architect-blind-tester.hermes` | + STRICT OUTPUT CONTRACT (JSON FIRST) |
| `/root/.hermes/profiles/code-blind-tester.hermes` | + STRICT OUTPUT CONTRACT |
| `/etc/systemd/system/karios-*.service` | 11 services |
| `/var/lib/karios/.git` | golden-seed tags |
| `/var/lib/karios/coordination/held-out-eval/` | 20% reserved tests |
| `/var/lib/karios/sessions/*.json` | per-agent session tracking |
| `/var/lib/karios/backups/{ts}-pre-vN/` | Rollback path for every deploy |

## Honest caveats (v7.3 still has rough edges)

1. **Architect doesn't always honor the pre-submit gate** — round 4 will validate
2. **Blind-testers exhaust context** — JSON-FIRST contract should help but Hermes-side fix may be needed
3. **`send_to_agent` Redis None-error** persists in some code paths — rare but logged
4. **Phase-name normalization** still has corner cases (e.g., trace_id can absorb subject text)
5. **Devops `BUILD FAILURE` subject** doesn't have a dedicated handler — currently "Unhandled message"
6. **2 of 6 phases (Phase 1 research, Phase 6 monitor)** still skipped/forged in meta-loop runs
7. **Architecture self-improvement** is real but bounded — devops proposed v7.0 from v6.0 input; further iterations need richer feedback loops to keep finding novel improvements

## Related docs

- [[multi-agent-architecture-v6|v6.0]] — predecessor; preserved for diff
- [[karios-multi-agent]] — v5.x infra notes
- [[pipeline-phases]] — phase definitions
- [[karios-v4-components]] — component specs
- `raw/karios-pipeline/decisions/` — DEC-11 through DEC-16
- `raw/karios-pipeline/rca/` — every bug captured this session

## Change log

| Date | Version | Changes |
|---|---|---|
| 2026-04-15 | 1.0 | Initial 6-agent system |
| 2026-04-17/18 | 5.x | KAIROS v3→v5 evolution, 14 RCAs |
| 2026-04-19 02:48 | 6.0 | 9-agent live, meta-safety harness, Obsidian bridge, contract test |
| 2026-04-19 11:30 | 7.0/7.1 | MessageEnvelope, idempotency, DLQ + 11 round-1 fixes layered |
| 2026-04-19 12:33 | 7.2 | Flush-decide wired, pre-flush vault brief, vault-read in prompt |
| 2026-04-19 13:03 | 7.3 | Subject aliases + Telegram phase notifications + hard pre-submit gate + JSON-FIRST contract + SOP postcondition fix + load_gap fallback |
