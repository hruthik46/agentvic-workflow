# v3.0 SOTA Agentic Workflow Improvements

**Date:** 2026-04-17
**Author:** Hermes Agent
**Context:** Implemented 10 SOTA improvements to the Karios 5-agent CI/CD system based on research into MetaGPT, ChatDev, LangGraph, CrewAI, AutoGen 0.4, and AgentBench.
**Status:** ✅ Live — All 10 improvements deployed and verified

---

## Summary

The Karios agentic workflow was upgraded from v2.1 to v3.0 with 10 state-of-the-art improvements inspired by and aligned with leading multi-agent frameworks (MetaGPT, LangGraph, CrewAI, AutoGen 0.4, AgentBench).

**Key references:**
- MetaGPT (arXiv:2308.00352) — SOPs in prompts, assembly line paradigm
- ChatDev (arXiv:2307.07924, ACL 2024) — chat-chain communication
- LangGraph — durable execution, time travel, streaming
- CrewAI — memory/knowledge, flows with routers, enterprise triggers
- AutoGen 0.4 (Microsoft) — event-driven async architecture
- AgentBench (ICLR 2024) — LLM agent evaluation

---

## All 10 Improvements

### 1. Structured Trace IDs ✅

**What:** Every message, checkpoint, event, and agent operation now carries a structured `trace_id` in format `trace_<gap>_<agent>_<op>_<uuid8>`.

**Example:** `trace_ARCHI001_archi_research_a1b2c3d4`

**Why:** Enables full correlation of operations across all systems — orchestrator logs, Redis messages, checkpoints, event logs, and Telegram alerts all share the same trace_id.

**Implementation:**
- `new_trace_id()` function generates IDs with semantic components
- All `send_to_agent()`, `stream_publish()`, `checkpoint()` calls include trace_id
- Trace log: `/var/lib/karios/orchestrator/traces/`

**SOTA alignment:** LangSmith-style distributed tracing — critical for debugging multi-agent systems.

---

### 2. Redis Streams — True Event-Driven ✅

**What:** Replaced `brpop(timeout=2)` polling loop with `XREADGROUP`. The orchestrator now blocks until a message arrives — no polling, no CPU waste.

**Before (v2.1):**
```python
while True:
    result = brpop("inbox:orchestrator", timeout=2)  # Polling!
    if result:
        _, msg = result
        parse_message(msg)
```

**After (v3.0):**
```python
while True:
    messages = xread_once(timeout_ms=5000)  # Blocks until message arrives
    for msg_id, data in messages:
        parse_message(msg_id, data)
        xack_all([msg_id])  # Acknowledge after processing
```

**Why:** Zero polling overhead. True event-driven. Messages are acknowledged and replayable on crash. 8 consumer groups registered (one per agent).

**Implementation:**
- `stream_publish()` — sends messages via `XADD` to `stream:orchestrator`
- `xread_once()` — reads via `XREADGROUP` with blocking
- `xack_all()` — acknowledges processed messages
- Backwards compatible: legacy `inbox:*` queues still supported for older agents

**SOTA alignment:** AutoGen 0.4 migration from conversation framework to event-driven async.

---

### 3. Persistent Checkpointing ✅

**What:** Every phase boundary saves a durable checkpoint to `/var/lib/karios/checkpoints/<agent>/<gap_id>/`.

**Checkpoint structure:**
```json
{
  "agent": "architect",
  "gap_id": "ARCH-IT-001",
  "phase": "2-arch-loop",
  "iteration": 3,
  "trace_id": "trace_ARCHI001_archi_arch_review_a1b2c3d4",
  "status": "in_progress",
  "timestamp": "2026-04-17T15:30:00Z",
  "metadata": {...}
}
```

**Why:** If an agent crashes mid-task, the orchestrator recovers from the last checkpoint — no work is lost.

**Implementation:**
- `save_checkpoint()` — saves to `checkpoints/<agent>/<gap_id>/latest.json` + `<phase>_<trace_id>.json`
- `load_latest_checkpoint()` — recovers gap state
- `recover_from_checkpoints()` — runs on dispatcher startup, nudges stalled agents
- New CLI: `agent-checkpoint <gap_id> <phase> <iteration> <trace_id>`

**SOTA alignment:** LangGraph's durable execution + time travel.

---

### 4. Real-Time Agent Streaming ✅

**What:** Agents stream progress to the `agent.stream` Redis pub/sub channel every 30s. Monitor subscribes and forwards to Telegram (rate-limited).

**Why:** No more 2+ minute silence while agents work. Real-time visibility into agent progress.

**Implementation:**
- `agent-stream-progress <trace_id> <message>` CLI — streams to `agent.stream`
- `agent-monitor-pubsub.py` subscribes to `agent.stream`
- Rate limiting: max 1 Telegram alert per agent per 30s for routine progress; task start/complete/timeout always sent
- Streaming thread in `agent-worker` runs every 30s independently of message processing

**Telegram format:**
```
🚀 architect [ARCH-IT-001] Researching CPU morphing options... trace=trace_arc_001_research_a1b2
✅ backend [ARCH-IT-002] Completed implementation... trace=trace_back_002_coding_a1b2
```

**SOTA alignment:** LangGraph streaming (token-level), CrewAI observability.

---

### 5. Dynamic Routing ✅

**What:** Instead of uniform retry for all sub-10 ratings, routing now depends on quality:

| Rating | Route | Action |
|--------|-------|--------|
| >= 9 (`ROUTING_FAST_TRACK`) | `fast_track` | Proceed with minimal extra iterations |
| 7-8 | `normal` | Standard retry |
| 4-6 | `normal` | Retry with self-diagnosis strategy |
| < 4 (`ROUTING_ESCALATE_NOW`) | `escalate` | Immediate escalation to Sai |

**Implementation:**
```python
def compute_routing(gap_id, phase, iteration, rating):
    if rating >= ROUTING_FAST_TRACK:
        return {"route": "fast_track", "next_action": "proceed", ...}
    elif rating < ROUTING_ESCALATE_NOW:
        return {"route": "escalate", "next_action": "escalate", ...}
    elif rating < ROUTING_MEDIUM:
        return {"route": "normal", "next_action": "retry_with_self_diagnosis", ...}
    else:
        return {"route": "normal", "next_action": "retry", ...}
```

**SOTA alignment:** CrewAI Flows router pattern — conditional branching based on output.

---

### 6. GitHub Webhook Trigger ✅

**What:** `github-webhook-server.py` listens on port 8087. On PR merge, automatically triggers production deploy.

**How it works:**
1. GitHub sends webhook to `http://server:8087/webhook`
2. Server verifies HMAC-SHA256 signature (if secret configured)
3. Extracts gap_id from branch name: `feature/ARCH-IT-001-cpu-morphing` → `ARCH-IT-001`
4. Sends `[GITHUB-PR-MERGED]` to orchestrator via Redis Stream
5. Orchestrator triggers DevOps deploy

**Endpoint:** `POST /webhook`
**Health:** `GET /health` → `{"status": "ok"}`

**Configuration:**
```bash
# Set webhook secret
Environment=GITHUB_WEBHOOK_SECRET=your_secret_here
# Point GitHub webhook to: http://your-server:8087/webhook
```

**SOTA alignment:** CrewAI Enterprise triggers (Gmail, Slack, Salesforce webhooks).

---

### 7. Agent Memory (Cross-Session) ✅

**What:** Every agent stores learnings that persist across sessions. Before each task, orchestrator retrieves relevant learnings and injects them into agent context.

**Learning structure:**
```json
{
  "id": "lrn_a1b2c3d4",
  "agent": "architect",
  "gap_id": "ARCH-IT-001",
  "phase": "2-arch-loop",
  "what_happened": "Architecture iteration 3 scored 8/10",
  "resolution": "Missing edge case for Ceph RBD failover",
  "rating": 8,
  "error_type": "architecture",
  "timestamp": "2026-04-17T15:30:00Z",
  "ttl_days": 90
}
```

**Storage:**
- Global: `/var/lib/karios/coordination/learnings.json` (500 max, 90-day TTL)
- Per-agent: `/var/lib/karios/agent-memory/learnings.json`

**Context injection:**
Before each task, orchestrator fetches relevant learnings:
```
## Relevant Past Learnings
- **[architect-blind-tester@2-arch-loop]** Architecture iteration 2 scored 7/10 → missing rollback plan
- **[code-blind-tester@3-coding]** E2E failed on timeout → increase waitForSelector to 30s
```

**Implementation:**
- `store_learning()` — called on every completion/escalation
- `retrieve_relevant_learnings()` — queried before task dispatch
- `format_learnings_for_context()` — converts to markdown for injection

**SOTA alignment:** CrewAI agents with memory + knowledge bases.

---

### 8. Parallel Gap Pipeline ✅

**What:** Architect can begin Phase 1 (research) on gap N+1 while Orchestrator handles gap N in Phase 2+.

**Flow:**
```
Gap N: Phase 2 (Arch Loop)         Gap N+1: Phase 1 (Research)
         ↓                                  ↓
   Orchestrator                    Architect (parallel)
   handles reviews               starts web search + infra testing
         ↓                                  ↓
   FAN-OUT to coding             [RESEARCH-COMPLETE] N+1
         ↓                                  ↓
   Gap N+1 queued → advances to Phase 2 (N+1 becomes active)
```

**Why:** Architect is never idle. When Gap N enters Phase 2, Architect immediately starts pre-research on N+1.

**Implementation:**
- `start_parallel_research()` — queues next gap for Architect
- `is_architect_free()` — checks if Architect phase is "idle" or "phase-1-done"
- Pipeline state: `/var/lib/karios/orchestrator/parallel-pipeline.json`

**SOTA alignment:** MetaGPT assembly line — multiple tasks in pipeline with different roles.

---

### 9. Hierarchical Fan-Out ✅

**What:** Large features are auto-decomposed into sub-tasks routed to sub-agents.

**Implementation:**
```python
def decompose_and_fan_out(gap_id, task, agents, parent_trace_id):
    # For 2-agent (backend + frontend): split by domain
    if agents == ["backend", "frontend"]:
        return {
            "parent_gap": gap_id,
            "parent_trace": parent_trace_id,
            "sub_tasks": [
                {"id": f"{gap_id}_backend", "agent": "backend", "scope": "backend_only"},
                {"id": f"{gap_id}_frontend", "agent": "frontend", "scope": "frontend_only"},
            ]
        }
```

**Decomposition saved to:** `phase-3-coding/decomposition.json`

**SOTA alignment:** MetaGPT role-based assembly line — specialized roles handle specialized subtasks.

---

### 10. External Integrations ✅

**What:** Generic webhook server extensible to any external system (GitHub, GitLab, cron, webhooks).

**Current implementation:**
- GitHub webhook on :8087 (PR merged, push, release events)
- Health endpoint for monitoring
- Redis Streams forwarding to orchestrator

**Extensible to:**
- GitLab webhooks
- Cron triggers (scheduled pipeline runs)
- Slack commands
- Jira webhooks
- Any HTTP POST webhook

**SOTA alignment:** CrewAI Enterprise triggers (Gmail, Slack, Salesforce, cron).

---

## Comparison: Before vs After

| Dimension | v2.1 (Before) | v3.0 (After) | SOTA Alignment |
|-----------|---------------|---------------|----------------|
| **Orchestration** | Polling `brpop(2s)` | Event-driven `XREADGROUP` | AutoGen 0.4 event-driven |
| **State Persistence** | File-based, limited | Checkpoints + Streams | LangGraph durable exec |
| **Memory** | Manual markdown | Redis-backed, searchable | CrewAI memory |
| **Tracing** | None | Full trace_id correlation | LangSmith tracing |
| **Streaming** | None | agent.stream pub/sub | LangGraph streaming |
| **Routing** | Static (all < 10 = retry) | Dynamic (3 tiers) | CrewAI routers |
| **External Triggers** | Telegram only | GitHub webhook + extensible | CrewAI triggers |
| **Parallelism** | Single gap pipeline | Multi-gap pipeline | MetaGPT assembly |
| **Crash Recovery** | Partial (fan-state only) | Full (all checkpoints) | LangGraph time-travel |

---

## Files Changed

| File | Change |
|------|--------|
| `/var/lib/karios/orchestrator/event_dispatcher.py` | Full rewrite v3.0 (80KB) |
| `/usr/local/bin/agent-worker` | Streaming + checkpoints + memory (19KB) |
| `/usr/local/bin/agent-monitor-pubsub.py` | Added agent.stream handler (6.9KB) |
| `/usr/local/bin/github-webhook-server.py` | New HTTP webhook server (10KB) |
| `/usr/local/bin/agent-stream-progress` | New CLI for streaming progress |
| `/usr/local/bin/agent-checkpoint` | New CLI for durable checkpoints |
| `/var/lib/karios/coordination/learnings.json` | New: cross-session learnings store |
| `/var/lib/karios/coordination/event-log.jsonl` | Extended with trace_ids |
| `/var/lib/karios/orchestrator/parallel-pipeline.json` | New: parallel gap tracking |
| `/var/lib/karios/orchestrator/traces/` | New: trace ID log directory |
| `/var/lib/karios/checkpoints/` | New: durable checkpoint directory |
| `/etc/systemd/system/karios-orchestrator-sub.service` | Updated env vars |
| `/etc/systemd/system/karios-github-webhook.service` | New service file |

---

## Validation

```bash
# All services running
systemctl status karios-orchestrator-sub karios-architect-agent karios-backend-worker \
  karios-frontend-worker karios-devops-agent karios-tester-agent \
  karios-monitor-worker karios-github-webhook

# Heartbeats
for agent in orchestrator architect backend frontend devops tester monitor; do
    ts=$(cat /var/lib/karios/heartbeat/${agent}.beat)
    age=$(($(date +%s) - ts))
    echo "$agent: ${age}s ago"
done

# Redis Streams
python3 -c "import redis; r = redis.Redis('192.168.118.202', 6379); \
  print('Groups:', len(r.xinfo_groups('stream:orchestrator'))); \
  print('Stream len:', r.xlen('stream:orchestrator'))"

# Webhook
curl http://localhost:8087/health
# → {"status": "ok", "service": "github-webhook-server"}

# Learnings
cat /var/lib/karios/coordination/learnings.json
```

---

## Related

- [[orchestrator/index]] — Orchestrator agent documentation
- [[multi-agent-architecture]] — Full system architecture
- [[learnings]] — Cross-session agent learnings
