---
type: bug
created: 2026-04-19T08:34:32.566362+00:00
agent: code-blind-tester
severity: HIGH
gap_id: ARCH-IT-ARCH-v6
tags: ["bug", "code-blind-tester", "high"]
---

# Bug: Hermes failed during 3-coding-testing for gap=ARCH-IT-ARCH-v6

## Severity
HIGH

## Reproduction Steps
1. Subject: [E2E-TEST] ARCH-IT-ARCH-v6 iteration 1 — Phase 4 testing
2. From: orchestrator
3. Body excerpt: Run E2E tests against the v5.0 observability implementation. Architecture docs: /var/lib/karios/iteration-tracker/ARCH-IT-ARCH-v6/phase-2-architecture/iteration-1/. Frontend test files: /root/karios-s

## Expected
Hermes produces meaningful output (>20 chars, no error markers)

## Actual
Output (482030 chars): 
╭──────────── Hermes Agent v0.9.0 (2026.4.13) · upstream c94d26c6 ─────────────╮
│                                   Available Tools                            │
│  ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⡀⠀⣀⣀⠀⢀⣀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀   file: patch, read_file, search_files,      │
│  ⠀⠀⠀⠀⠀⠀⢀⣠⣴⣾⣿⣿⣇⠸⣿⣿⠇⣸⣿⣿⣷⣦⣄⡀⠀⠀⠀⠀⠀⠀   write_file                                 │
│  ⠀⢀⣠⣴⣶⠿⠋⣩⡿⣿⡿⠻⣿⡇⢠⡄⢸⣿⠟⢿⣿⢿⣍⠙⠿⣶⣦⣄⡀⠀   homeassistant: ha_call_service,            │
│  ⠀⠀⠉⠉⠁⠶⠟⠋⠀⠉⠀⢀⣈⣁⡈⢁⣈⣁⡀⠀⠉⠀⠙⠻⠶⠈⠉⠉⠀⠀   ha_get_state, ...                          │
│  ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
