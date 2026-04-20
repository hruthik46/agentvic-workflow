# Holographic Memory Provider + Per-Agent Profiles (v8.0 integration)

Per v7.16 research: Hermes ships 8 native memory providers. **Holographic** is the
recommended choice for KAIROS — local SQLite + FTS5 + HRR algebraic queries +
trust scoring + contradiction detection. Free, no external service, matches our
Obsidian-as-vault philosophy.

## Per-agent profile setup

Currently all 9 KAIROS agents share `/root/.hermes/config.yaml` global config.
Migration: each agent gets its own profile dir with isolated `MEMORY.md`,
`USER.md`, plugin set, memory provider config.

### File layout (after this integration)

```
/root/.hermes/
├── config.yaml                           # global defaults
└── profiles/
    ├── architect/
    │   ├── config.yaml                   # per-agent overrides
    │   ├── SOUL.md                       # role doc (already exists)
    │   ├── MEMORY.md                     # NEW — Hermes writes session memory here
    │   ├── USER.md                       # NEW — Hermes writes user model here
    │   └── plugins/
    │       └── kairos-obsidian-bridge/   # symlink to global plugin
    ├── architect-blind-tester/
    │   └── ... (same)
    ├── backend/
    │   └── ... (same)
    ├── ... (frontend, devops, tester, monitor, code-blind-tester, orchestrator)
```

## Per-agent config.yaml additions

Each profile's `config.yaml` (e.g. `/root/.hermes/profiles/architect/config.yaml`)
gets these keys appended:

```yaml
memory:
  provider: holographic
  config:
    db_path: /root/.hermes/profiles/architect/memory.sqlite
    fts5_enabled: true
    contradiction_detection: true
    trust_threshold: 0.7         # auto-resolve contradictions only above this
    auto_extract_on_session_end: true
    max_db_size_mb: 500          # cap; weekly VACUUM via hermes cron

# Per-agent plugin opt-in
plugins:
  enabled:
    - kairos-obsidian-bridge      # writes critique to vault on session-end

# Per-agent reasoning effort tuning (per v7.12 research):
agent:
  reasoning_effort: medium        # backend/frontend/devops/code-blind-tester: medium
  # reasoning_effort: low         # for orchestrator/router roles: low
  max_turns: 60                   # already set globally in v7.12
```

## Apply with this script

```bash
# /root/.hermes/setup_per_agent_profiles.sh
#!/bin/bash
set -e
PROFILES_DIR=/root/.hermes/profiles
AGENTS=(architect architect-blind-tester backend frontend devops tester monitor code-blind-tester orchestrator)

for agent in "${AGENTS[@]}"; do
    profile_dir=$PROFILES_DIR/$agent
    mkdir -p $profile_dir/plugins

    # Append memory + plugins config (idempotent)
    if ! grep -q '^memory:' $profile_dir/config.yaml 2>/dev/null; then
        cat >> $profile_dir/config.yaml << EOF

# v8.0: Holographic memory + plugin opt-in
memory:
  provider: holographic
  config:
    db_path: $profile_dir/memory.sqlite
    fts5_enabled: true
    contradiction_detection: true
    trust_threshold: 0.7
    auto_extract_on_session_end: true
    max_db_size_mb: 500

plugins:
  enabled:
    - kairos-obsidian-bridge
EOF
        echo "✓ $agent: memory + plugins added"
    else
        echo "  $agent: already configured"
    fi

    # Symlink the plugin
    ln -sf /root/.hermes/plugins/kairos-obsidian-bridge $profile_dir/plugins/

    # Touch MEMORY.md + USER.md so Hermes finds them
    touch $profile_dir/MEMORY.md $profile_dir/USER.md
done

echo "Done. Restart all 8 agent services to pick up:"
echo "  for s in karios-architect-agent karios-architect-blind-tester ..."
echo "  do systemctl restart \$s; done"
```

## Hermes cron for weekly VACUUM

Add via `hermes cron` (replaces our bash cron):

```bash
hermes cron add \
    --name "kairos-memory-vacuum" \
    --schedule "0 3 * * 0" \
    --command "for db in /root/.hermes/profiles/*/memory.sqlite; do sqlite3 \$db 'VACUUM; ANALYZE;'; done" \
    --notify-channel telegram-hermes \
    --notify-on-failure-only
```

## Risk: 9 SQLite DBs to back up

Add to `/etc/cron.d/karios-memory-backup`:

```cron
# Daily at 02:00 UTC: snapshot all per-agent memory DBs to /var/backups/karios/memory/
0 2 * * * root /usr/local/bin/karios-memory-backup
```

Where `karios-memory-backup` is a script that does `cp + gzip` per DB with date stamp.

## Validation

After deploy, verify:

```bash
# Each agent has a populated DB
for agent in architect backend frontend ...; do
    db=/root/.hermes/profiles/$agent/memory.sqlite
    echo "$agent: $(sqlite3 $db 'SELECT COUNT(*) FROM memories' 2>/dev/null || echo no-db)"
done

# Trust scores look reasonable (no all-zero, no all-one)
sqlite3 /root/.hermes/profiles/architect/memory.sqlite \
    'SELECT MIN(trust), MAX(trust), AVG(trust) FROM memories'

# Contradictions detected (good — means contradiction_detection is working)
sqlite3 /root/.hermes/profiles/architect/memory.sqlite \
    'SELECT COUNT(*) FROM memories WHERE flags LIKE "%contradiction%"'
```

## ETCSLV impact

| Letter | Before | After |
|---|---|---|
| **C** (Context/memory) | Global Obsidian vault shared by all agents (no per-agent isolation, no trust scoring, no contradiction detection) | Per-agent SQLite DB with FTS5 + HRR algebraic queries + trust scores + auto-contradiction-detection |

Vault at `/opt/obsidian/config/vaults/My-LLM-Wiki/raw/karios-pipeline/` remains the
**cross-agent shared memory**; per-agent Holographic DBs are the **role-specific
private memory** (e.g., backend remembers go.mod patterns, architect remembers
KRE-Lab vCenter quirks).
