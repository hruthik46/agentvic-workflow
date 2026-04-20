---
type: bug
created: 2026-04-19T07:02:18.594350+00:00
agent: architect
severity: HIGH
gap_id: ARCH-IT-ARCH-v6
tags: ["bug", "architect", "high"]
---

# Bug: Hermes failed during idle for gap=ARCH-IT-ARCH-v6

## Severity
HIGH

## Reproduction Steps
1. Subject: [ARCH-DESIGN] ARCH-IT-ARCH-v6 — Phase 2: Architecture Design
2. From: orchestrator
3. Body excerpt: ## Relevant Knowledge


---

## Task

Resume Phase 2 architecture design for ARCH-IT-ARCH-v6 (iteration 1).
trace_id: trace_ARCH-IT-ARCH-v6_v6_1776581358
Requirement context:
# META-LOOP TASK

You are

## Expected
Hermes produces meaningful output (>20 chars, no error markers)

## Actual
Output (307813 chars): 
╭──────────── Hermes Agent v0.9.0 (2026.4.13) · upstream 3a635145 ─────────────╮
│                                   Available Tools                            │
│  ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⣀⡀⠀⣀⣀⠀⢀⣀⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀   file: patch, read_file, search_files,      │
│  ⠀⠀⠀⠀⠀⠀⢀⣠⣴⣾⣿⣿⣇⠸⣿⣿⠇⣸⣿⣿⣷⣦⣄⡀⠀⠀⠀⠀⠀⠀   write_file                                 │
│  ⠀⢀⣠⣴⣶⠿⠋⣩⡿⣿⡿⠻⣿⡇⢠⡄⢸⣿⠟⢿⣿⢿⣍⠙⠿⣶⣦⣄⡀⠀   homeassistant: ha_call_service,            │
│  ⠀⠀⠉⠉⠁⠶⠟⠋⠀⠉⠀⢀⣈⣁⡈⢁⣈⣁⡀⠀⠉⠀⠙⠻⠶⠈⠉⠉⠀⠀   ha_get_state, ...                          │
│  ⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
