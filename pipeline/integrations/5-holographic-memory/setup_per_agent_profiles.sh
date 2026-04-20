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

EOF
        echo "✓ $agent: memory + plugins added"
    else
        echo "  $agent: already configured"
    fi


    # Touch MEMORY.md + USER.md so Hermes finds them
    touch $profile_dir/MEMORY.md $profile_dir/USER.md
done

echo "Done. Restart all 8 agent services to pick up:"
