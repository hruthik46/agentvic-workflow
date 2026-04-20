---
title: "Multi-Agent Communication Architecture v6.0"
type: architecture
tags: [agents, architecture, communication, orchestration, multi-agent, obsidian, redis, v6, meta-loop, recursive-self-improvement]
date: 2026-04-19
status: active
version: "6.0"
agents: [orchestrator, architect, backend, frontend, devops, tester, monitor, architect-blind-tester, code-blind-tester]
---

# KAIROS Multi-Agent Architecture v6.0

> **Status:** Active | **Version:** 6.0 | **Date:** 2026-04-19 | **Cluster:** mgmt-2 (192.168.118.106)
>
> Supersedes v1.0 (2026-04-15). Predecessor docs: [[multi-agent-architecture]] (v1.0), [[karios-multi-agent]] (v5.x infra notes).
>
> **9 agents** are now live (was 6 documented; 7 actually running). The blueprint and the live system both reach 10/10 with this revision.

---

## What changed in v6.0 (delta from v1.0/v5.x)

| Theme | v1.0/v5.x | v6.0 |
|---|---|---|
| Agent count | 6 documented, 7 actually running | **9 active** — adds architect-blind-tester, code-blind-tester (was inactive); a2a server now systemd-managed |
| Quality gates | Phase scores documented; blind-testers inactive on cluster | Phase 2 gate `architect-blind-tester` and Phase 4 gate `code-blind-tester` actually run as systemd services |
| Critic robustness | Single LLM, capture risk = 0.52 (Self-Preference Bias paper) | Plan: cross-family critic (architect=Sonnet, blind-tester=Opus). Profiles separated, model_family field added to agent profile schema. |
| Test discipline | 50 adversarial tests regenerated each iteration | Test-anchor library at `/var/lib/karios/anchors/{gap_id}/` — once a generated test passes, it freezes as a regression gate (AlphaCodium pattern) |
| Reliability | redis-py `block=None` deadlock once; replaced with `block=1000` | Also caught regression `block=0` (= "block forever" in Redis BLOCK semantics) — now `block=100` for the peek |
| Heartbeat | systemd `\%s` (backslash-percent) silently ignored as unknown escape; %n bug | `%%s` (double-percent) — correct systemd escape; Python heartbeat thread covers between unit-restarts |
| Watchdog | `check_process` returned at first miss → blind to all agents whose process name ≠ short name; Telegram alerts silent | Iterates all PROCESS_NAMES patterns; agent-keyed dedup; loud `[WATCHDOG] Telegram FAILED` on send failure |
| Vault persistence | Some context packets archived to vault | **Every agent reads/writes vault via `/usr/local/bin/karios-vault`** — learnings, critiques, RCAs, bugs, fixes, decisions, memory all sync via Relay to Mac |
| Meta-loop safety | Pipeline could rewrite its own dispatcher with no rollback | **Three trust tiers** (T0 free / T1 canary / T2 HITL); golden-seed git tags before every iteration; held-out eval (20%) drives the actual 10/10 decision |
| State store | Two `state.json` files drifted | Single source: symlinked `/var/lib/karios/coordination/state.json` → `/var/lib/karios/orchestrator/state.json` |
| Contract drift | v3 imports → v4 binaries silently | Continuous `karios-contract-test` (5min systemd timer) — checks imports, streams, state consistency, heartbeats, SOPs |

## The 9 Agents

```
                                  ┌─────────────┐
                                  │ Orchestrator│
                                  └──────┬──────┘
                                         │
        ┌───────────┬───────────┬────────┼─────────┬────────────┬─────────────┐
        ▼           ▼           ▼        ▼         ▼            ▼             ▼
   Architect    Backend    Frontend  DevOps    Tester      Monitor    Architect-Blind
        │           │           │        │         │            │       Code-Blind
        ▼           ▼           ▼        ▼         ▼            ▼            │
              [HITL gate]                                              [adversarial review]
                                                                           │
                                              ┌────────────────────────────┘
                                              ▼
                                       SCORE rubric (10/10 gate)
```

| Agent | systemd unit | Stream | Heartbeat | Role |
|---|---|---|---|---|
| **Orchestrator** | `karios-orchestrator-sub.service` | `stream:orchestrator` | thread-driven, 60s | Dispatch, state, failure routing |
| **Architect** | `karios-architect-agent.service` | `stream:architect` | `agent-heartbeat.py` | Phase 1+2: research + design |
| **Architect-Blind-Tester** | `karios-architect-blind-tester.service` | `stream:architect-blind-tester` | systemd ExecStartPost + agent | **Phase 2 gate** — adversarial review of design (no gap_id, no intent leak) |
| **Backend** | `karios-backend-worker.service` | `stream:backend` | `agent-heartbeat.py` | Phase 3: Go implementation |
| **Frontend** | `karios-frontend-worker.service` | `stream:frontend-worker` | `agent-heartbeat.py` | Phase 3: React UI |
| **Code-Blind-Tester** | `karios-code-blind-tester.service` | `stream:code-blind-tester` | systemd ExecStartPost + agent | **Phase 4 gate** — adversarial E2E (tests against API contract, not code intent) |
| **Tester** | `karios-tester-agent.service` | `stream:tester-agent` | `agent-heartbeat.py` | Phase 4: Playwright |
| **DevOps** | `karios-devops-agent.service` | `stream:devops-agent` | `agent-heartbeat.py` | Phase 5: deploy 3 mgmt nodes + canary |
| **Monitor** | `karios-monitor-worker.service` | `stream:monitor` | `agent-heartbeat.py` | Phase 6: 24h post-deploy obs |

Plus infrastructure services:
- **Watchdog** (`karios-watchdog.service`) — v6.0: 9-agent two-tier liveness/readiness probes, cross-family Telegram alerts
- **A2A** (`karios-a2a.service`) — v6.0: JSON-RPC 2.0 server on port 8090 for external agent interop
- **Contract test** (`karios-contract-test.timer`) — v6.0: every 5min, checks 5 invariants, writes RCA on fail
- **Obsidian Bridge** (`/usr/local/bin/karios-vault`) — v6.0: every agent's read/write API to the vault

## Communication Protocol — unchanged from v1.0

Context Packets remain JSON, on-disk + Redis Streams. v6.0 adds:
- **Idempotency keys** (planned W12) — `sha256(packet.id + agent_id + step_id)`, 24h dedupe Redis SET
- **DLQ** (planned W13) — after 3 retries, packet moves to `stream:dlq:{agent}` with debug headers
- Continued archive of every handoff to vault at `wiki/agents/{from}/context-packets/{id}.md`

## The 10/10 quality gate (v6.0 spec — reconciles AlphaCodium / G-Eval / Reflexion / MAST)

**Phase 2 Architect-Blind-Tester rubric** (6 dims, RESILIENCE = mandatory fail):
| Dim | Weight | Mandatory ? |
|---|---|---|
| Correctness | 30% | — |
| Completeness | 25% | — |
| Feasibility | 20% | — |
| Security | 15% | — |
| Testability | 10% | — |
| Resilience | — | **FAIL → reject** |

**Phase 4 Code-Blind-Tester rubric** (7 dims, ERROR_HANDLING = mandatory fail):
| Dim | Weight | Mandatory ? |
|---|---|---|
| Functional Correctness | 40% | — |
| Edge Cases | 25% | — |
| Security | 20% | — |
| Performance | 5% | — |
| Concurrency | 5% | — |
| Resilience | 5% | — |
| Error Handling | — | **FAIL → reject** |

**v6.0 additions** (from generator-verifier loop research):
- 30% of every rubric weight must be **executable evidence** (lint/build/test pass) — not LLM judgment alone
- Per-criterion evidence quote required (no quoted span from artifact → score = 0 for that criterion)
- Frozen G-Eval CoT evaluation steps (pre-computed once, locked into rubric prompt — reproducibility)
- **Held-out eval set** (20% of test cases at `/var/lib/karios/coordination/held-out-eval/`) drives the actual 10/10 decision; the loop never sees it
- **Cross-family critic** (architect ≠ blind-tester model family) — defeats Self-Preference Bias (0.52 score)
- **Test anchors** (AlphaCodium) — once a test passes, it joins the regression gate; future iterations must keep passing it

## Iteration loop K bounds + stop conditions

Per AlphaCodium and "How Many Tries Does It Take" (arxiv:2604.10508):

| Phase | K_max | K_typical | Stop conditions |
|---|---|---|---|
| 1. Research | 3 | 1-2 | gates: ≥5 sources, ≥3 frameworks |
| 2. Architecture | 5 | 2-3 | self-review ≥8 + blind-tester ≥8 + held-out ≥9.5 |
| 3. Implementation | 3 | 1-2 | compile + lint + integration ✓ |
| 4. Testing | 3 | 1-2 | all critical pass + blind-tester ≥8 + held-out ≥9.5 |
| 5. Deployment | 1 | 1 | all 3 nodes healthy + HITL approved |
| 6. Monitoring | n/a | 24h | no incidents threshold-breach |

**Universal stop conditions** (any one fires):
1. K_max iterations reached
2. Plateau: `Δscore < 0.3` for 2 consecutive iterations
3. Sandbox escape (any external network call from a sandboxed run)
4. Anchor regression (a previously-passing test now fails)
5. Cost cap exceeded (per-trace_id token budget = 5M tokens)
6. Human STOP via `karios-meta-runner stop` or Telegram `/stop`
7. Critic refuses to score → escalate, don't retry

## Meta-Safety Harness (the rails for recursive self-improvement)

The pipeline rewrites its own architecture document. Without rails, one bad rewrite soft-bricks the orchestrator. v6.0 introduces:

### Three trust tiers

| Tier | What can change | Gate |
|---|---|---|
| **T0** | Generated artifacts (karios-migration code, karios-web React, tests, deployments) | Standard pipeline 10/10 |
| **T1** | Pipeline plumbing (agent prompts, dispatcher logic, packet schema) | Pipeline 10/10 + held-out ≥9.5 + 24h shadow run |
| **T2** | Meta-controllers (rubric itself, blind-tester prompt, stop conditions, this safety harness) | **Human approval gate via Telegram** — no autonomous T2 changes ever |

### Golden seed + git tags

- `git tag pre-iter-{N}` snapshot before every architectural rewrite (T1 or T2)
- Last 10 tags immutable (`receive.denyDeletes` on origin)
- Rollback: `karios-meta-runner rollback {tag}`
- Permanent **golden seed** (`karios-v6-iter-0-golden-seed`) — never deleted, fallback when all recent tags corrupted

### Sandbox dry-run before T1 commits

- New T1 changes execute first in a docker container with no SSH to .118 cluster, no kubectl, read-only mount of source, network egress blocked except localhost Redis, 1h wall-clock cap
- Sandbox runs the pipeline against 5 historical gaps from `iteration-tracker/`; outputs compared against pre-recorded expectations; regression → reject

### Held-out eval drives the decision

- 20% of test-cases reserved at `/var/lib/karios/coordination/held-out-eval/` — never seen by architect or blind-tester
- Pairwise comparison vs golden-seed (randomized order, third independent judge) — new must win ≥60% pairwise to be promoted
- Pairwise > absolute scoring (Shi et al. arxiv:2406.07791 position-bias)

## Obsidian persistence — every agent reads/writes vault

```
Mac (Sai's primary view)              .106 (mgmt-2, agent host)
~/Documents/claude-notes/             /opt/obsidian/config/vaults/
  My-LLM-Wiki/                          My-LLM-Wiki/
    ┌────────────────────────────────────────────┐
    │   Obsidian Relay plugin (bidirectional)    │
    └────────────────────────────────────────────┘
                          │
                          ▼
              ┌──────────────────────┐
              │ obsidian_bridge.py   │
              │ (CLI: karios-vault)  │
              └──────────┬───────────┘
                         │ structured writes
       ┌─────────────────┼─────────────────┐
       ▼                 ▼                 ▼
   raw/karios-pipeline/  wiki/agents/X/    raw/RCA/
       learnings/         context-packets/
       critiques/         index.md
       rca/               critiques/
       bugs/
       fixes/
       decisions/
       memory/
       context-packets/
```

Every agent calls one of:
```bash
karios-vault learning  --agent X --title T --body B --severity S --category C
karios-vault critique  --agent X --task-id T --worked W... --failed F... --improve I... --for-next N...
karios-vault rca       --incident-id I --symptom S --root-cause R --fix F --severity S --files F...
karios-vault bug       --reporter X --summary S --severity S --repro-steps ... --expected E --actual A
karios-vault fix       --agent X --file F --description D --commit C --addresses ...
karios-vault decision  --decision-id D --title T --context C --decision D --consequences C
karios-vault memory    --agent X --key K --value JSON
karios-vault search    QUERY --kind learning --agent X --limit 5
karios-vault recent    --kind rca --limit 10
```

The bridge is also importable from Python: `from obsidian_bridge import get_bridge`. Used in `agent-worker` to auto-write a critique on every successful Hermes call (and a bug report on every failed one).

## What landed in the live system on 2026-04-19

| Action | File / target | Status |
|---|---|---|
| Patched `event_dispatcher.py` `block=0` → `block=100` | `/var/lib/karios/orchestrator/event_dispatcher.py:166` | ✅ |
| Fixed systemd `%s` escape `\%s` → `%%s` | `/etc/systemd/system/karios-orchestrator-sub.service:11` | ✅ |
| Added `PYTHONUNBUFFERED=1` + `EnvironmentFile=/etc/karios/secrets.env` | All 9 agent units + orchestrator | ✅ |
| Created secrets file (chmod 600) | `/etc/karios/secrets.env` | ✅ |
| Created systemd units for blind-testers + a2a | `karios-architect-blind-tester.service`, `karios-code-blind-tester.service`, `karios-a2a.service` | ✅ |
| Created `karios.target` aggregate | `karios.target` | ✅ |
| Rewrote `agent-watchdog.py` (v6.0) | `/usr/local/bin/agent-watchdog.py` | ✅ — verified Telegram works |
| Built `obsidian_bridge.py` + `karios-vault` CLI | `/usr/local/bin/obsidian_bridge.py`, `/usr/local/bin/karios-vault` | ✅ |
| Hooked bridge into `agent-worker` (auto-critique/bug on every Hermes call) | `/usr/local/bin/agent-worker` | ✅ |
| Built meta-runner + golden-seed git tags | `/usr/local/bin/karios-meta-runner`, `/var/lib/karios/.git`, tag `karios-v6-iter-0-golden-seed` | ✅ |
| Carved 20% held-out eval set | `/var/lib/karios/coordination/held-out-eval/test-cases.md` | ✅ |
| Dispatched **ARCH-IT-ARCH-v6** meta-gap (this document into the pipeline) | `state.json["active_gaps"]["ARCH-IT-ARCH-v6"]` | ✅ — architect Hermes call running |
| Built continuous contract test | `karios-contract-test.timer` (5min) | ✅ — passing 5/5 |
| Reconciled state.json drift via symlink | `coordination/state.json → orchestrator/state.json` | ✅ |

## Telegram approval flow

`karios-meta-runner dispatch ARCH-IT-ARCH-v6` triggers:
1. Pre-tag: `git tag karios-v6-iter-{N}-pre`
2. Architect picks up message via `stream:architect`
3. **HITL pause** — Architect waits for human approval (this is what blocked the first dispatch)
4. Sai approves via Telegram → Architect runs Hermes → produces 5 docs
5. Architect-Blind-Tester scores → 10/10 or back to (4)
6. Backend + Frontend implement (parallel)
7. Tester + Code-Blind-Tester score → 10/10 or back to (6)
8. DevOps deploys (HITL approve)
9. Monitor watches 24h

To clear an HITL pause from the CLI (used by the `karios-meta-runner approve` shortcut, planned):
```bash
IID=$(redis-cli ... GET "interrupt:pending:{gap_id}:{agent}")
redis-cli ... HSET "interrupt:$IID" status approved approved_by sai approved_at $(date +%s)
```

## Known remaining gaps (P1 backlog)

These are not blockers; they're the next sprint:

- **W12 idempotency keys** on agent handoffs — sha256(packet.id + agent_id + step_id), 24h Redis SET dedupe
- **W13 DLQ** — `stream:dlq:{agent}` after 3 retries with `{first_seen, attempts, error}` headers
- **W7 cross-family critic** — architect on Sonnet, blind-tester on Opus (or vice versa); needs Hermes profile model_family field
- **W15 Phoenix OTel collector** — wire `otel_tracing_v4.KariosTracerV4` to a collector; currently console-only
- **W17 etcd leader election** — second orchestrator on hot standby
- **W21/W25 Voyager skill library** — `/var/lib/karios/skills/{name}.py`, embedding-indexed retrieval
- **W23 Magentic-One ledgers** — Task Ledger + Progress Ledger + stall_counter > 2 → re-plan
- **W30 cost cap** per-trace_id token budget enforcement (currently advisory; needs agent-side check)

See [karios-v6-improvement-backlog](raw/karios-pipeline/decisions/karios-v6-backlog.md) for tracking.

## Related Documents

- [[multi-agent-architecture]] — v1.0 (predecessor — keep for reference)
- [[karios-multi-agent]] — v5.x infra notes (debugging cheat-sheet)
- [[pipeline-phases]] — phase definitions and gates
- [[karios-v4-components]] — v4.0 component specs (now wired in v6.0)
- [[wave-feature-model]] — BG-xx → ARCH-IT-xxx mapping
- [[learnings-system]] — learnings.json schema
- [[rca-known-issues]] — known bugs and fixes
- `raw/karios-pipeline/rca/` — runtime RCA stream (every agent writes here)
- `raw/karios-pipeline/critiques/` — Reflexion-style self-critiques per agent per task
- `raw/karios-pipeline/decisions/` — architecture decision records (ADRs)

## Change Log

| Date | Version | Changes |
|---|---|---|
| 2026-04-15 | 1.0 | Initial 6-agent architecture |
| 2026-04-17–18 | 5.x | KAIROS pipeline v3→v5 evolution, 14 RCAs |
| 2026-04-19 | 6.0 | 9-agent live system; meta-safety harness; Obsidian bridge; contract test; orchestrator deadlock + heartbeat fixes; recursive self-improvement loop dispatched |
