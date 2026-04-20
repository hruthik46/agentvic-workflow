---
type: decision
created: 2026-04-19T15:33:27.254794+00:00
agent: architect
decision_id: DEC-13
title: Session-flush policy for 9 Hermes agents
tags: ["decision", "adr", "architect"]
---

# DEC-13: Session-flush policy for 9 Hermes agents

## Context
Long-running Hermes agent sessions accumulate context (tool calls, prior failures) that may help OR harm. Need policy for when to start fresh vs continue. Research grounded in Anthropic Building Effective Agents, Cognition Devin compression pattern, MemGPT, Reflexion, Lost-in-the-Middle, NoLiMa benchmark.

## Decision
Per-agent flush policy: blind-testers ALWAYS fresh, devops flush after deploy, tester flush after run, monitor sliding window, architect/backend/frontend flush on task boundary, orchestrator summarize-and-restart at 50K tokens. Universal triggers: tokens >50K, tool_calls >30, idle >30min, wall >2h, loop detected, quality plateau. Config: /etc/karios/flush-policy.yaml. Helper: /usr/local/bin/karios-flush-decide. Validation: track quality before/after flush in /var/lib/karios/sessions/{agent}.json.

## Consequences
Eliminates context bloat, restores blind-tester independence, cuts ~30% tokens per task per LangChain benchmark. Validation harness compares quality scores; rollback by raising thresholds. Anthropic prompt cache 5min TTL means flushes >5min apart are cost-free.
