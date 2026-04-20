# 5-holographic-memory — STATUS

## Code completeness: SCRIPT + DOCS READY (not deployed)

`README.md` (in this dir) describes per-agent profile setup using Hermes' built-in
holographic memory provider (already shipped at `/root/.hermes/hermes-agent/plugins/memory/holographic/`).

`setup_per_agent_profiles.sh` is idempotent — re-runs are safe.

## What's required to deploy

1. Run `bash setup_per_agent_profiles.sh` — creates `/root/.hermes/profiles/<agent>/{config.yaml,MEMORY.md,USER.md,plugins/}` for all 9 agents
2. Restart all 8 agent services to pick up new config
3. Add `hermes cron` for weekly VACUUM
4. Add daily backup cron via `/etc/cron.d/karios-memory-backup`

## Why deferred

User constraint: "do not deploy latest yet because there are ongoing tasks in the pipeline."
Per-agent service restart is disruptive (interrupts in-flight Hermes sessions).
Schedule for the next quiet window after IT-018 closes.

## Validation after deploy

```bash
# Each agent has a populated DB
for agent in architect backend frontend devops tester monitor architect-blind-tester code-blind-tester orchestrator; do
    db=/root/.hermes/profiles/$agent/memory.sqlite
    echo "$agent: $(sqlite3 $db 'SELECT COUNT(*) FROM memories' 2>/dev/null || echo no-db)"
done

# Trust scores look reasonable
sqlite3 /root/.hermes/profiles/architect/memory.sqlite \
    'SELECT MIN(trust), MAX(trust), AVG(trust) FROM memories'

# Contradiction detection working
sqlite3 /root/.hermes/profiles/architect/memory.sqlite \
    'SELECT COUNT(*) FROM memories WHERE flags LIKE "%contradiction%"'
```

## ETCSLV impact

| Letter | Before | After |
|---|---|---|
| **C** (Context/memory) | Global Obsidian vault shared by all agents (no per-agent isolation, no trust scoring, no contradiction detection) | Per-agent SQLite DB with FTS5 + HRR algebraic queries + trust scores + auto-contradiction-detection |

The vault remains the **cross-agent shared memory**; per-agent Holographic DBs become the **role-specific private memory** (e.g. backend remembers go.mod patterns, architect remembers KRE-Lab vCenter quirks).
