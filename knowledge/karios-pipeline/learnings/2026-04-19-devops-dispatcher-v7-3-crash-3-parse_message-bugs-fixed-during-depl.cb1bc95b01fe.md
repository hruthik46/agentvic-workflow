---
type: learning
created: 2026-04-19T18:03:36.472530+00:00
agent: devops
severity: high
category: bug
title: "Dispatcher v7.3 crash: 3 parse_message bugs fixed during deploy"
tags: ["learning", "devops", "bug"]
---

Fixed 3 bugs in event_dispatcher.py parse_message() while deploying ARCH-IT-ARCH-v9:

1. IndexError: tokens[0] when [E2E-RESULTS] message subject has no gap_id after ]
2. TypeError: len(int) when critical_issues field is int (6) not list
3. ValueError: int('1:') when iteration token has trailing colon

Fix: Added guard 'if not tokens: return', isinstance() check for critical_issues, and rstrip(':') on iteration token.

Root cause: Malformed E2E-RESULTS messages from code-blind-tester lacking proper subject formatting.

Impact: Orchestrator was crashing on every message, causing 87 restart cycles.
