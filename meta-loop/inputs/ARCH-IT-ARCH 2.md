# Requirement: ARCH-IT-ARCH

## Context
This is a meta-architecture gap. The requirement is to research, design, and implement improvements to the Karios Multi-Agent Architecture itself — upgrade from v3.0 to v4.0.

## Current State (v3.0)
The existing multi-agent architecture v3.0 is documented at:
- /opt/obsidian/config/vaults/My-LLM-Wiki/wiki/agents/orchestrator/multi-agent-architecture.md
- /opt/obsidian/config/vaults/My-LLM-Wiki/wiki/agents/orchestrator/v3-changes.md

## What the Architect Must Do

### Phase 1 — Research (web access REQUIRED)
Research SOTA agentic workflows and multi-agent frameworks. You MUST browse the internet freely for this. Focus areas:
1. **LangGraph** — durable execution, time-travel debugging, checkpointing
2. **CrewAI** — memory/knowledge integration, enterprise triggers, flow routers
3. **AutoGen 0.4** — event-driven async, agent collaboration protocols
4. **MetaGPT** — SOP-driven agent collaboration, role specialization
5. **ChatDev** — chat-chain communication, iterative refinement
6. **AgentBench** — benchmark findings, what separates top agents from mediocre ones
7. **Google ADK** — what our current fan-out/fan-in pattern can learn from it
8. **Microsoft Magma** — any published findings on agentic workflow best practices
9. **Emergent Architectures** — any new patterns published in 2025-2026

Also research:
- Edge cases in multi-agent coordination (deadlocks, livelocks, race conditions)
- Cost optimization strategies for LLM-based agents
- How top systems handle agent failures and graceful degradation
- New tools/techniques for agent observability and debugging

### Phase 2 — Architecture Design
Design v4.0 improvements to the Karios multi-agent architecture. Your design must include:
1. **architecture.md** — full v4.0 architecture specification
2. **edge-cases.md** — how v4.0 handles failure modes
3. **test-cases.md** — how we validate v4.0 improvements
4. **api-contract.md** — if any new APIs are needed
5. **deployment-plan.md** — how to deploy v4.0 without downtime

The v4.0 design must address at minimum:
- Improved fault tolerance (agents can crash without losing state)
- Better observability (real-time tracing of all agent operations)
- Cost optimization (reduce LLM token usage without sacrificing quality)
- Expanded tool access for all agents (web browsing, code execution, etc.)
- Improved human-in-the-loop mechanisms

### Phase 3 — Implementation
Implement the v4.0 changes to the orchestrator and agent-worker code. All code changes go in:
- /var/lib/karios/orchestrator/event_dispatcher.py (orchestrator)
- /usr/local/bin/agent-worker (worker wrapper)
- /usr/local/bin/agent-monitor-pubsub.py (monitor)
- /var/lib/karios/coordination/learnings.json (learnings store)
- New systemd services if needed

## Research Access
You have full web access. Use it freely. Search arXiv, read blog posts, check GitHub repos, watch conference talks on YouTube. No constraint on sources — the more comprehensive the research, the better the architecture.

## Success Criteria
- Phase 1: SOTA research covering at least 5 frameworks with concrete comparisons to current v3.0
- Phase 2: v4.0 architecture document with at least 5 specific improvements over v3.0
- Phase 3: Working v4.0 code deployed and validated through the pipeline's own self-test

## Note
This gap is the architecture eating its own dog food — the multi-agent system is being used to improve itself.
