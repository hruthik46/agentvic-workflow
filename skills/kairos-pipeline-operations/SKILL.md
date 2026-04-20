---
name: kairos-pipeline-operations
description: Use when operating, debugging, or extending the KAIROS 9-agent pipeline running on 192.168.118.106. Covers the 6-phase lifecycle, all message subjects, the 5 ways to inject work, the iteration loop, and the 47-patch history of v6→v7.6.
version: 1.0.0
author: Sai Hruthik + Claude (Anthropic)
license: MIT
metadata:
  hermes:
    tags: [karios, multi-agent, orchestrator, redis-streams, hermes, meta-loop, devops]
    related_skills: [systematic-debugging, writing-plans, subagent-driven-development]
    homepage: https://github.com/hruthik46/agentvic-workflow
---

# KAIROS Pipeline Operations

## Overview

You are working with the KAIROS 9-agent recursive-self-improvement pipeline. It lives on `192.168.118.106` and uses you (Hermes) as the per-agent LLM runtime.

**Core principle:** Every meaningful change goes through the 6-phase lifecycle. Every phase boundary fires a Telegram notification to channel `Hermes` (id `-1003999467717`). Every agent reads + writes the Obsidian vault at `/opt/obsidian/config/vaults/My-LLM-Wiki/raw/karios-pipeline/`.

If you find yourself wanting to bypass a phase or skip a tool call, stop. The pipeline is designed so prose-without-tool-calls fails the gate.

## When to use this skill

- You are one of the 9 agents (orchestrator, architect, architect-blind-tester, backend, frontend, devops, tester, code-blind-tester, monitor) and need to operate within the pipeline.
- You are debugging a stalled gap, a stuck Hermes session, or a missing Telegram notification.
- You need to dispatch a new requirement, query the vault, or inspect why a gap got escalated.
- You are extending the pipeline — adding a new subject, a new handler, a new gate.

## The 9 agents

| Agent | Role | Phase ownership |
|---|---|---|
| **orchestrator** | Dispatches phases, runs gates, fans out/in | All — coordinator |
| **architect** | Research + architecture design | 1, 2 |
| **architect-blind-tester** | Adversarial review of architect output | 2 (always-fresh sessions) |
| **backend** | Backend coding (Go/Python in karios-migration repo) | 3 |
| **frontend** | Frontend coding (React in karios-web repo) | 3 |
| **devops** | Deploy + Gitea push + cluster health | 5 |
| **tester** | Functional/contract tests | 4 |
| **code-blind-tester** | Adversarial E2E (always-fresh sessions) | 4 |
| **monitor** | 24h post-deploy watch | 6 |

## The 6 phases

| # | Phase | Owner | Gate | Iteration cap |
|---|---|---|---|---|
| 1 | Research | architect | quality ≥ 7 + ≥5 sources + ≥3 frameworks | 3 |
| 2 | Architecture | architect | architect-blind-tester rating ≥ 8 | **5** |
| 3 | Coding | backend + frontend (parallel) | both compile + lint + integration ✓ | **3** |
| 4 | E2E Testing | tester + code-blind-tester | code-blind-tester rating ≥ 8 | **3** |
| 5 | Deploy | devops | all 3 mgmt nodes healthy + Gitea push verified | 1 |
| 6 | Monitor | monitor | 24h, no incidents | n/a |

Per-iteration gate is **8/10**, not 10/10. After K_max iterations without passing, the gap **escalates** (Telegram alert + halt for human review).

## The iteration loop (Sai's question 2026-04-19)

```
[ARCH-COMPLETE]    → architect-blind-tester
                       ↓
                   [ARCH-REVIEWED]
                       ↓
                rating ≥ 8?  ──── yes ───→ FAN-OUT to backend+frontend (Phase 3)
                       │
                       no
                       ↓
                send_to_agent("architect", "[ARCH-REVISE]")  ← critical_issues attached
                       ↓
                iteration += 1; if iteration > K_max → ESCALATE
```

Same shape for `[E2E-RESULTS] → revise backend+frontend` if rating < 8.

## Message subjects (canonical)

| Subject prefix | From → To | Phase boundary |
|---|---|---|
| `[REQUIREMENT]` | human → orchestrator | start |
| `[RESEARCH-COMPLETE]` | architect → orchestrator | 1 → 2 |
| `[ARCH-COMPLETE]` (alias: `[ARCHITECTURE-COMPLETE]`) | architect → orchestrator | 2 → 2-review |
| `[ARCH-REVIEWED]` (alias: `[BLIND-REVIEWED]`) | architect-blind-tester → orchestrator | 2-review → 3 (or revise) |
| `[FAN-OUT] [CODE-REQUEST]` | orchestrator → backend, frontend | 3 dispatch |
| `[CODING-COMPLETE]` (alias: `[FAN-IN]`) | backend, frontend → orchestrator | 3 → 3-API-SYNC |
| `[API-SYNC]` | orchestrator → backend, frontend | API contract verify |
| `[E2E-REVIEW]` | orchestrator → code-blind-tester | 4 dispatch |
| `[TEST-RUN]` | orchestrator → tester | 4 dispatch |
| `[E2E-RESULTS]` (aliases: `[BLIND-E2E-RESULTS]`, `[E2E-COMPLETE]`, `[TEST-RESULTS]`) | code-blind-tester → orchestrator | 4 → 5 (or revise) |
| `[PRODUCTION]` | orchestrator → devops | 5 dispatch |
| `[STAGING-DEPLOYED]` (aliases: `[DEPLOYED-STAGING]`, `[STAGING-COMPLETE]`) | devops → orchestrator | 5-staging |
| `[PROD-DEPLOYED]` (aliases: `[DEPLOYED-PROD]`, `[DEPLOY-DONE]`, `[PRODUCTION-COMPLETE]`) | devops → orchestrator | 5 → 6 |
| `[MONITORING-COMPLETE]` | monitor → orchestrator | 6 → closed |
| `[GITEA-PUSH-PENDING]` | orchestrator → devops | v7.6 D refusal |
| `[SCHEMA-VIOLATION]` | orchestrator → sender | v7.6 A refusal |

When you emit a message:
1. Subject MUST start with one of these prefixes (or a documented alias).
2. Body SHOULD be valid JSON (Pydantic schema enforces a model per subject — see `pipeline/orchestrator/message_schemas.py`).
3. If you want fenced markdown around the JSON, that's fine — the parser strips ```json fences and falls back to the first `{…}` regex.

## How to talk to the live pipeline (5 ways, ascending coupling)

### 1. Telegram channel `Hermes` (`-1003999467717`) — read-only
Every `notify_phase_transition()` call lands here. Sai sees: `🔍 [ARCH-REVIEWED] gap-id — score 8/10  Handing off: architect-blind-tester → backend+frontend (Phase 3)`.

### 2. SSH + `journalctl`
```bash
ssh root@192.168.118.106
journalctl -u karios-orchestrator-sub -f                    # live dispatcher events
journalctl -u karios-architect-agent -f                     # any single agent
systemctl list-units 'karios-*' --no-pager                  # all 17 services
```

### 3. SSH + `karios-vault` CLI (cross-agent shared memory)
```bash
karios-vault search "<keywords>"                            # full-text search
karios-vault recent --kind rca|critique|decision|fix --limit 10
karios-vault learning|critique|rca|bug|fix|decision|memory --agent X --title T --body B
```

### 4. SSH + file-inbox (drop a JSON, dispatcher consumes within 2s)
```bash
cat > /var/lib/karios/agent-msg/inbox/orchestrator/inject.json << 'EOF'
{"from":"human","to":"orchestrator","id":"unique-id","priority":"high",
 "message":"[REQUIREMENT] start gap XYZ — <description>"}
EOF
```
Bad JSON is quarantined to `/var/lib/karios/agent-msg/quarantine/` instead of looping the parser error.

### 5. SSH + Redis stream injection (fully-formed envelope, matches what real agents produce)
```bash
redis-cli -h 192.168.118.202 --user karios_admin --pass <REDACTED> --no-auth-warning \
  XADD stream:orchestrator '*' \
    from architect-blind-tester \
    to orchestrator \
    subject "[ARCH-REVIEWED] gap iter 1" \
    body '{"rating":8,"recommendation":"APPROVE","summary":"..."}' \
    gap_id GAP-X \
    trace_id trace_X
```

## Iteration-tracker filesystem

Per-gap artifacts live at:
```
/var/lib/karios/iteration-tracker/<gap_id>/
├── metadata.json
├── manifest.json                           # repos_touched (drives v7.6 D Gitea verify)
├── phase-2-architecture/iteration-N/{architecture,api-contract,test-cases,edge-cases,deployment-plan}.md
├── phase-2-arch-loop/iteration-N/review.json
├── phase-3-coding/decomposition.json
└── phase-3-coding/iteration-N/e2e-results.json
```

The HARD PRE-SUBMIT GATE (v7.3) requires all 5 phase-2 docs ≥ 2KB before `[ARCH-COMPLETE]` is accepted.

## Tool-use enforcement (v7.5)

`/root/.hermes/config.yaml` has `agent.tool_use_enforcement: true`. This forces tool-use for every model regardless of name (the `auto` default only matched `gpt`/`codex`/`gemini`/`gemma`/`grok`, none of our MiniMax-M2.7 agents).

In addition, `agent-worker` uses `run_hermes_pty()` (v7.6 E) — a PTY-streamed Hermes invocation that counts output tokens and detects `tool_use` events. If you produce >4000 chars without ANY tool call, the watchdog SIGKILLs your session and retries once with the prepend:
```
BEGIN by calling karios-vault.search. Do not output prose first.
```

**Practical implication for you:** start every task with a tool call (`karios-vault search`, `read_file`, `get_minimal_context`, etc.). Don't deliberate in prose first.

## code-review-graph (v7.4) — 8.2× token savings

For any code-touching task (backend/frontend/devops profiles), call this FIRST:
```python
get_minimal_context(task="<5-word description>")
```
Returns ~100 tokens of situational awareness + `next_tool_suggestions`. Use `detail_level="minimal"` on subsequent calls. Target ≤5 tool calls, ≤800 graph tokens per task.

The post-Hermes hook (v7.6 C, `_check_code_review_graph_usage` in `agent-worker`) writes a critique to the vault if you skip this. Don't skip it.

The 4 main repos all have `<repo>/.code-review-graph/graph.db` pre-built:
- `/root/karios-source-code/karios-migration/`
- `/root/karios-source-code/karios-web/`
- `/root/karios-source-code/karios-core/`
- `/root/karios-source-code/karios-bootstrap/`

After writing code: `cd <repo> && uvx code-review-graph update` (incremental, <2s).

## Gitea push protocol (v7.4) — for backend/frontend/devops

```
1. cd /root/karios-source-code/<repo>
2. git pull --rebase origin <branch>
3. <make changes>
4. git add <specific-files>      # NEVER git add -A — blacklist might leak
5. git commit -m "<msg>"
6. git push origin <branch>
7. if conflict: karios-merge-resolve <repo> <conflict-file>
   (consults vault for prior resolutions; refuses to push blacklisted files)
```

**Blacklist** (in `.gitignore` of all 4 repos): `*.hermes`, `**/karios-pipeline/**`, `multi-agent-architecture*.md`, `ARCH-IT-ARCH*`, `**/iteration-tracker/**`, `karios-meta-*`, `karios-vault*`, `obsidian_bridge*`, `.code-review-graph/`, `**/agent-worker`, `session_brief_pre_flush_*`, `flush-policy.yaml`. Pipeline-internal stays internal.

For pipeline-internal commits, push to `https://github.com/hruthik46/agentvic-workflow` (Sai's personal repo) instead of org Gitea.

## Session-flush policy

| Agent | Strategy | Trigger |
|---|---|---|
| architect-blind-tester | `always_fresh` | every task — no `--resume` ever |
| code-blind-tester | `always_fresh` | every task |
| devops | `flush_after_event: deploy_complete` | event |
| tester | `flush_after_event: test_run_complete` | event |
| monitor | `sliding_window 50, hard_flush 4h` | window + time |
| architect / backend / frontend | `flush_on_task_boundary` | task_id change |
| orchestrator | `summarize_and_restart at 50K tokens` | tokens |

Universal triggers: tokens > 50K, tool_calls > 30 without progress, idle > 30 min, wall > 2 h, loop detected, quality plateau Δ<0.05 over 3 cycles.

Before flushing, `karios-flush-decide` is invoked and a pre-flush brief is written to `obsidian_bridge.write_memory(key="session_brief_pre_flush_<ts>", value={...})` so the next fresh session has continuity.

## Known pitfalls (47 patches over 6 meta-loop rounds)

These are already fixed but you may hit echoes of them while debugging:

| Symptom | Root cause | Fix |
|---|---|---|
| 3-hour Telegram silence | env var name `TELEGRAM_TOKEN` vs `TELEGRAM_BOT_TOKEN` | dispatcher line 83 v7.5 fix |
| Markdown messages silently rejected | `parse_mode=Markdown` + `[BRACKETED]` text | `telegram_alert` retry path v7.5 |
| Backend stuck 2.5h on stale RECOVER | `recover_from_checkpoints` didn't check state.json `state=completed` | v7.5 guard added |
| `ENAMETOOLONG` creating dir | gap_id parser absorbed prose tail | `_sanitize_gap_id()` v7.5 |
| Hermes 200-400K prose, zero tool calls | `tool_use_enforcement: auto` doesn't match MiniMax | global `true` v7.5 |
| `[ARCH-REVIEWED]` JSON not parsed | `json.loads(body)` doesn't strip subject prefix or fence | v7.5 extraction |
| 9 agents long-poll Telegram → HTTP 409 | per-agent listener instead of centralized | `KARIOS_HITL_DISABLE_LISTENER=1` |

For the full timeline see [HISTORY.md](https://github.com/hruthik46/agentvic-workflow/blob/main/HISTORY.md).

## Quick reference card

```
# Ship a small change end-to-end
1. Drop /var/lib/karios/coordination/requirements/REQ-X.md
2. xadd stream:orchestrator with [REQUIREMENT] subject
3. Watch journalctl -u karios-orchestrator-sub -f
4. Telegram fires on each phase
5. After [PROD-DEPLOYED] arrives, monitor watches 24h
6. After [MONITORING-COMPLETE], gap is closed in state.json

# Inject a synthetic gate (when blind-tester emits prose without JSON)
xadd stream:orchestrator '*' from architect-blind-tester subject "[ARCH-REVIEWED] gap iter 1" \
  body '{"rating":8,"recommendation":"APPROVE","summary":"..."}' gap_id GAP-X trace_id trace_X

# Force-close a stuck gap
1. Edit /var/lib/karios/orchestrator/state.json: set active_gaps[gap_id].state="completed", phase="completed"
2. Echo a "completed" status to /var/lib/karios/checkpoints/<agent>/<gap>/latest.json
3. systemctl restart karios-orchestrator-sub karios-<stuck-agent>

# Drain stale stream messages
redis-cli -h 192.168.118.202 --user karios_admin --pass <REDACTED> XTRIM stream:<name> MAXLEN 0
```

## What this skill is NOT

- It is not a tutorial on Hermes itself. Read `/root/.hermes/AGENTS.md` for that.
- It is not a replacement for the SOUL.md per agent — those define personality + responsibilities. This skill defines pipeline mechanics.
- It is not version-locked. The pipeline is at v7.6 today; check the repo for the current state.

## Source of truth

This skill ships as part of [github.com/hruthik46/agentvic-workflow](https://github.com/hruthik46/agentvic-workflow). The full pipeline code, knowledge base, RCAs, decisions, learnings, and 47-patch history are all in that repo. If you need detail beyond this SKILL.md, read:

- `README.md` — repo entry point with layout map
- `DISASTER-RECOVERY.md` — fresh-node bootstrap runbook
- `HISTORY.md` — v6 → v7.6 timeline
- `knowledge/PIPELINE-KNOWLEDGE.md` — master narrative with every patch + lesson
- `pipeline/orchestrator/event_dispatcher.py` — the actual code
- `pipeline/bin/agent-worker` — your wrapper
