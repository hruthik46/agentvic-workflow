---
type: learning
created: 2026-04-19T06:44:07.765664+00:00
agent: system
severity: LOW
category: orchestration
title: Vault re-pointed to Relay-synced location
tags: ["learning", "system", "orchestration"]
---

Bridge originally wrote to /var/lib/karios/obsidian-vault. User informed me the Relay-synced vault is at /opt/obsidian/config/vaults/My-LLM-Wiki. Re-pointed via KARIOS_VAULT_ROOT in /etc/karios/secrets.env. All future writes by all 9 agents land in the Relay-synced vault and reflect on Mac.
