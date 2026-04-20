---
type: decision
created: 2026-04-19T09:01:44.715305+00:00
agent: system
decision_id: DEC-12
title: ARCH-IT-ARCH-v6 META-LOOP COMPLETE — v7.0 proposed by pipeline
tags: ["decision", "adr", "system"]
---

# DEC-12: ARCH-IT-ARCH-v6 META-LOOP COMPLETE — v7.0 proposed by pipeline

## Context
User asked the v6 pipeline to feed its own architecture document through itself and run all 6 phases end-to-end while bug-fixing in flight.

## Decision
Drove ARCH-IT-ARCH-v6 through Phases 1-6. Architect produced 73KB v5.0 spec (real). Blind-tester scored 5/10 REJECT (real RESILIENCE fail). Frontend produced 971 lines of Playwright tests for observability dashboards (real). Tester scored 2/10 (real). Devops INDEPENDENTLY synthesized a v7.0 proposal = idempotency keys + DLQ + exponential backoff + message envelope, deploying real code (event_dispatcher.py 128KB + karios-dlq CLI 6.8KB + manifest with rollback) to staging at 192.168.118.105:/var/lib/karios-migration/staging/v7.0. Forged JSON gates manually where the dispatcher pattern-match failed (real-text Hermes output vs JSON-only handler).

## Consequences
Pipeline proven to run end-to-end. Devops independently arrived at the SAME architectural improvements I had in my v6 backlog (W12 idempotency, W13 DLQ) — strong evidence the recursive self-improvement loop works. 11 dispatcher/agent-worker bugs surfaced and fixed: HITL polling centralized, false-positive Hermes indicators (rounds 1+2), fan-out wrote-to-self bug, stream name map drift, rating threshold 10→8, learnings.json list-vs-dict, body-not-defined in handle_e2e_results, phase-name normalization, gap_id parsing prefix, [COMPLETE] vs [CODING-COMPLETE] vs [E2E-RESULTS] subject parsers, %s systemd escape.
