---
type: bug
created: 2026-04-19T08:27:07.337411+00:00
agent: frontend
severity: HIGH
gap_id: ARCH-IT-ARCH-v6
tags: ["bug", "frontend", "high"]
---

# Bug: Hermes failed during 3-coding-sync for gap=ARCH-IT-ARCH-v6

## Severity
HIGH

## Reproduction Steps
1. Subject: [API-SYNC] ARCH-IT-ARCH-v6 — confirm API alignment before deploy
2. From: orchestrator
3. Body excerpt: ## Relevant Knowledge


---

## Task

PARALLEL coding complete for ARCH-IT-ARCH-v6.
Before DevOps deploys, you must confirm API contract alignment.
Read: /var/lib/karios/iteration-tracker/ARCH-IT-ARCH

## Expected
Hermes produces meaningful output (>20 chars, no error markers)

## Actual
Output (104429 chars): 
╭──────────── Hermes Agent v0.9.0 (2026.4.13) · upstream 175cf7e6 ─────────────╮
│                                   Available Tools                            │
│  ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⡀⠀⣀⣀⠀⢀⣀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀   file: patch, read_file, search_files,      │
│  ⠀⠀⠀⠀⠀⠀⢀⣠⣴⣾⣿⣿⣇⠸⣿⣿⠇⣸⣿⣿⣷⣦⣄⡀⠀⠀⠀⠀⠀⠀   write_file                                 │
│  ⠀⢀⣠⣴⣶⠿⠋⣩⡿⣿⡿⠻⣿⡇⢠⡄⢸⣿⠟⢿⣿⢿⣍⠙⠿⣶⣦⣄⡀⠀   homeassistant: ha_call_service,            │
│  ⠀⠀⠉⠉⠁⠶⠟⠋⠀⠉⠀⢀⣈⣁⡈⢁⣈⣁⡀⠀⠉⠀⠙⠻⠶⠈⠉⠉⠀⠀   ha_get_state, ...                          │
│  ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
