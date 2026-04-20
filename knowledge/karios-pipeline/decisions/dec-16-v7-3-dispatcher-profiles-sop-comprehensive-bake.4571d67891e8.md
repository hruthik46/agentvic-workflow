---
type: decision
created: 2026-04-19T17:06:56.767372+00:00
agent: system
decision_id: DEC-16
title: v7.3 dispatcher + profiles + SOP comprehensive bake
tags: ["decision", "adr", "system"]
---

# DEC-16: v7.3 dispatcher + profiles + SOP comprehensive bake

## Context
Round 3 surfaced: architect placeholder bug, blind-tester JSON exhaustion, subject-format drift (ARCHITECTURE-COMPLETE etc), need for Telegram phase visibility, SOP precondition wrong, load_gap returning unknown. User asked: review entire arch, fix everything, deploy live, monitor end-to-end, notify Telegram on every blind-test handoff.

## Decision
v7.3 ships: (1) Subject aliases for ARCHITECTURE-COMPLETE/BLIND-E2E-RESULTS/E2E-COMPLETE/DEPLOYED-STAGING/PRODUCTION-DEPLOYED. (2) notify_phase_transition() helper + wired into ARCH-REVIEWED, E2E-RESULTS, STAGING-DEPLOYED, PROD-DEPLOYED handlers — Telegram fires on every score with score+next-handoff. (3) Architect profile HARD PRE-SUBMIT GATE requires all 5 docs >=2KB before [ARCH-COMPLETE]. (4) Both blind-tester profiles STRICT OUTPUT CONTRACT — JSON FIRST in fenced block, total <30K chars to avoid Hermes context exhaustion. (5) sop_engine: required_output_files moved from precondition to postcondition (no more dispatch-blocking on iter 1). (6) load_gap fallback: if metadata.json missing, read state.json. (7) send_to_agent kwargs fix for [PRODUCTION] None bug. (8) Backups at /var/lib/karios/backups/{ts}-pre-v7.3/.

## Consequences
Pipeline should now: have NO blocking SOP failures on first dispatch; advance through Phase 2 gate when blind-tester scores >=8 in JSON; emit Telegram for every gate transition; recognize agent-invented subject formats. Round 4 (ARCH-IT-ARCH-v9) just dispatched to validate.
