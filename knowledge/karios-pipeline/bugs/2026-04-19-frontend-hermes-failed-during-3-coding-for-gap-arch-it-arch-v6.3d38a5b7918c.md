---
type: bug
created: 2026-04-19T07:54:11.917573+00:00
agent: frontend
severity: HIGH
gap_id: ARCH-IT-ARCH-v6
tags: ["bug", "frontend", "high"]
---

# Bug: Hermes failed during 3-coding for gap=ARCH-IT-ARCH-v6

## Severity
HIGH

## Reproduction Steps
1. Subject: [FAN-OUT] [CODE-REQUEST] ARCH-IT-ARCH-v6 ARCH-IT-ARCH-v6
2. From: orchestrator
3. Body excerpt: ## Relevant Knowledge


---

## Task

Architecture approved (rating=10/10). Implement your part in parallel.


Architecture docs: /var/lib/karios/iteration-tracker/ARCH-IT-ARCH-v6/phase-2-arch-loop/it

## Expected
Hermes produces meaningful output (>20 chars, no error markers)

## Actual
Output (254506 chars): 
╭──────────── Hermes Agent v0.9.0 (2026.4.13) · upstream 175cf7e6 ─────────────╮
│                                   Available Tools                            │
│  ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⡀⠀⣀⣀⠀⢀⣀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀   file: patch, read_file, search_files,      │
│  ⠀⠀⠀⠀⠀⠀⢀⣠⣴⣾⣿⣿⣇⠸⣿⣿⠇⣸⣿⣿⣷⣦⣄⡀⠀⠀⠀⠀⠀⠀   write_file                                 │
│  ⠀⢀⣠⣴⣶⠿⠋⣩⡿⣿⡿⠻⣿⡇⢠⡄⢸⣿⠟⢿⣿⢿⣍⠙⠿⣶⣦⣄⡀⠀   homeassistant: ha_call_service,            │
│  ⠀⠀⠉⠉⠁⠶⠟⠋⠀⠉⠀⢀⣈⣁⡈⢁⣈⣁⡀⠀⠉⠀⠙⠻⠶⠈⠉⠉⠀⠀   ha_get_state, ...                          │
│  ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
