---
type: decision
created: 2026-04-19T23:18:52.546132+00:00
agent: architect
decision_id: DEC-17-v7.6
title: v7.6 production gates
tags: ["decision", "adr", "architect"]
---

# DEC-17-v7.6: v7.6 production gates

## Context
ARCH-IT-ARCH-v11 — drive KAIROS from 8.5/10 to 10/10

## Decision
6 items: A=Pydantic schema(log-only iter1), B=BG-stub-no-op self-test+CLI, C=code-review-graph rubric gate, D=Gitea push verification gate, E=watchdog PTY kill-on-no-tool-call, F=deferred (tool_choice passthrough)

## Consequences
All v7.5 features preserved (11 items verified). Self-test enables pipeline health verification. Gitea gate prevents unpushed deployments. Watchdog prevents token flood attacks on Hermes. Schema validation catches malformed messages.
