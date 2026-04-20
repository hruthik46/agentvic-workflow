---
type: bug
created: 2026-04-19T08:45:39.172371+00:00
agent: devops
severity: HIGH
gap_id: ARCH-IT-ARCH-v6 — confirmed alignment
tags: ["bug", "devops", "high"]
---

# Bug: Hermes failed during idle for gap=ARCH-IT-ARCH-v6 — confirmed alignment

## Severity
HIGH

## Reproduction Steps
1. Subject: [DEPLOY] ARCH-IT-ARCH-v6 — confirmed alignment — API-SYNC complete, deploy to staging
2. From: orchestrator
3. Body excerpt: ## Relevant Knowledge


---

## Task

Both agents confirmed API alignment for ARCH-IT-ARCH-v6 — confirmed alignment.
Deploy to staging and notify: [STAGING-DEPLOYED] ARCH-IT-ARCH-v6 — confirmed alignm

## Expected
Hermes produces meaningful output (>20 chars, no error markers)

## Actual
Output (311929 chars): 
╭──────────── Hermes Agent v0.9.0 (2026.4.13) · upstream c94d26c6 ─────────────╮
│                                   Available Tools                            │
│  ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⡀⠀⣀⣀⠀⢀⣀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀   file: patch, read_file, search_files,      │
│  ⠀⠀⠀⠀⠀⠀⢀⣠⣴⣾⣿⣿⣇⠸⣿⣿⠇⣸⣿⣿⣷⣦⣄⡀⠀⠀⠀⠀⠀⠀   write_file                                 │
│  ⠀⢀⣠⣴⣶⠿⠋⣩⡿⣿⡿⠻⣿⡇⢠⡄⢸⣿⠟⢿⣿⢿⣍⠙⠿⣶⣦⣄⡀⠀   homeassistant: ha_call_service,            │
│  ⠀⠀⠉⠉⠁⠶⠟⠋⠀⠉⠀⢀⣈⣁⡈⢁⣈⣁⡀⠀⠉⠀⠙⠻⠶⠈⠉⠉⠀⠀   ha_get_state, ...                          │
│  ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
