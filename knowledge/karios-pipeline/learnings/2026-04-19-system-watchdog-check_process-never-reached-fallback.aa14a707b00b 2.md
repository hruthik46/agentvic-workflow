---
type: learning
created: 2026-04-19T06:43:33.403777+00:00
agent: system
severity: HIGH
category: orchestration
title: Watchdog check_process never reached fallback
tags: ["learning", "system", "orchestration"]
---

agent-watchdog.py check_process(agent) returned at line 96 from the first pgrep call. The fallback patterns at lines 99+ were unreachable in normal operation, so any agent whose process name was not literally its short name was reported DOWN.
