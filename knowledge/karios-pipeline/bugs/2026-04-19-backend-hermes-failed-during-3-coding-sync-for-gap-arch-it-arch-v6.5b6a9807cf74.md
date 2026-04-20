---
type: bug
created: 2026-04-19T08:25:14.951008+00:00
agent: backend
severity: HIGH
gap_id: ARCH-IT-ARCH-v6
tags: ["bug", "backend", "high"]
---

# Bug: Hermes failed during 3-coding-sync for gap=ARCH-IT-ARCH-v6

## Severity
HIGH

## Reproduction Steps
1. Subject: [API-SYNC] ARCH-IT-ARCH-v6 — ready for API contract verification
2. From: orchestrator
3. Body excerpt: ## Relevant Knowledge


---

## Task

gap_id=ARCH-IT-ARCH-v6
iteration=1
trace_id=trace_ARCH-IT-ARCH-v6_v6_1776581358

Verify the API contract against the implementation. Report back with [CODING-COMP

## Expected
Hermes produces meaningful output (>20 chars, no error markers)

## Actual
Output (342197 chars): 
╭──────────── Hermes Agent v0.9.0 (2026.4.13) · upstream 175cf7e6 ─────────────╮
│                                   Available Tools                            │
│  ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⡀⠀⣀⣀⠀⢀⣀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀   file: patch, read_file, search_files,      │
│  ⠀⠀⠀⠀⠀⠀⢀⣠⣴⣾⣿⣿⣇⠸⣿⣿⠇⣸⣿⣿⣷⣦⣄⡀⠀⠀⠀⠀⠀⠀   write_file                                 │
│  ⠀⢀⣠⣴⣶⠿⠋⣩⡿⣿⡿⠻⣿⡇⢠⡄⢸⣿⠟⢿⣿⢿⣍⠙⠿⣶⣦⣄⡀⠀   homeassistant: ha_call_service,            │
│  ⠀⠀⠉⠉⠁⠶⠟⠋⠀⠉⠀⢀⣈⣁⡈⢁⣈⣁⡀⠀⠉⠀⠙⠻⠶⠈⠉⠉⠀⠀   ha_get_state, ...                          │
│  ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
