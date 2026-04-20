---
type: decision
created: 2026-04-19T23:08:16.788675+00:00
agent: architect
decision_id: DEC-17-v7.6
title: v7.6 production gates
tags: ["decision", "adr", "architect"]
---

# DEC-17-v7.6: v7.6 production gates

## Context
ARCH-IT-013: 6 hardening items to push KAIROS pipeline from 8.5/10 to 10/10. Items A-E feasible. Item F INFEASIBLE (MiniMax OpenAI-compat doesn't support Anthropic tool_choice:any). Pydantic schemas log-only this iteration. BG-stub-no-op provides self-test. Code-review-graph gate enforces best practice. Gitea push gate prevents incomplete deploys. Watchdog kill-on-no-tool-call is belt-and-suspenders.

## Decision
v7.6 implements: (A) Pydantic message schemas in message_schemas.py, log-only for v11; (B) BG-stub-no-op requirement + karios-self-test CLI; (C) code-review-graph rubric gate in agent-worker post-Hermes hook + dispatcher gate; (D) Gitea push verification in handle_production_deployed; (E) Watchdog kill-on-no-tool-call via PTY streaming with subprocess.run fallback; (F) INFEASIBLE — tool_choice:any is Anthropic-specific, MiniMax OpenAI-compat can't support it.

## Consequences
Pipeline should reach 10/10: all phase transitions verified, Telegram fires on every boundary, schema violations quarantined, code tasks use get_minimal_context, deploys only on fully-pushed repos, agents that output prose without tools are killed and retried. Self-test (BG-stub-no-op + karios-self-test) provides ongoing pipeline health verification.
