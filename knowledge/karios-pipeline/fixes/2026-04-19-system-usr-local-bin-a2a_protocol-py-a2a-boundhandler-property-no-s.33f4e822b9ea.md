---
type: fix
created: 2026-04-19T16:42:48.767640+00:00
agent: system
file: /usr/local/bin/a2a_protocol.py
commit: uncommitted
addresses: ["Task L backlog"]
tags: ["fix", "system"]
---

# Fix: /usr/local/bin/a2a_protocol.py

## Description
a2a BoundHandler property-no-setter error was transient state in the long-running process. After systemd restart, all endpoints work: GET /a2a/agents returns agent cards (2 registered), GET /a2a/agents/:id returns specific card, POST /a2a accepts JSON-RPC, 404 for unknown path. No AttributeError on fresh process. Closed as fixed-by-restart. Probable cause: old code snapshot in memory vs patched file on disk.

## Commit
uncommitted

## Addresses
- Task L backlog
