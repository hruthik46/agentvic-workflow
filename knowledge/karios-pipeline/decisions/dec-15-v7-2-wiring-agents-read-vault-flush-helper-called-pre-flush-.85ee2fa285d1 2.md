---
type: decision
created: 2026-04-19T16:34:27.746924+00:00
agent: architect
decision_id: DEC-15
title: "v7.2 wiring: agents read vault, flush helper called, pre-flush brief written"
tags: ["decision", "adr", "architect"]
---

# DEC-15: v7.2 wiring: agents read vault, flush helper called, pre-flush brief written

## Context
User asked: do agents flush context only when necessary, push everything to vault first, treat vault as source of truth across all 9 agents?

## Decision
Wired three things into agent-worker that previously were just deployed-but-not-called: (1) karios-flush-decide invoked before every Hermes call — exit 0=continue, 1=flush, 2=summarize. (2) Pre-flush vault brief written via obsidian_bridge.write_memory when action!=continue, so next session has continuity. (3) Cross-Agent Vault Context (top 8 relevant entries from karios-vault search) injected into the Hermes prompt body, plus CLI usage instructions in the system prompt.

## Consequences
Every Hermes call now: (a) checks flush policy; (b) if flushing, dumps a session brief to vault first; (c) gets vault snippets from the OTHER 8 agents in its prompt; (d) post-Hermes hook writes critique/bug as before. End-to-end vault-as-truth for all 9 agents. Always-fresh enforced for blind-testers per policy. Verified live: architect logged Pre-flush vault brief written (action=flush) on its first ARCH-IT-ARCH-v8 dispatch.
