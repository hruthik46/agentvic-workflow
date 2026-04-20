---
type: fix
created: 2026-04-19T06:58:23.112269+00:00
agent: system
file: /var/lib/karios/orchestrator/event_dispatcher.py
commit: (applied directly to live system, backup at /var/lib/karios/backups/20260419-023433/)
addresses: ["v5.4 RCA introduced this regression while fixing block=None"]
tags: ["fix", "system"]
---

# Fix: /var/lib/karios/orchestrator/event_dispatcher.py

## Description
Replaced block=0 with block=100 in xread_once first peek. block=0 in Redis BLOCK semantics means block-forever (NOT non-blocking).

## Commit
(applied directly to live system, backup at /var/lib/karios/backups/20260419-023433/)

## Addresses
- v5.4 RCA introduced this regression while fixing block=None
