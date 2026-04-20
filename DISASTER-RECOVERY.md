# DISASTER RECOVERY — Replicating the KAIROS pipeline on a fresh node

If `192.168.118.106` is gone, this runbook rebuilds the pipeline anywhere with one Linux node + Redis + Hermes.

## Hard prerequisites

- **Linux** with systemd (Debian 12 / Ubuntu 22.04+ tested). Root access.
- **Python 3.11+** with pip (`pip install --break-system-packages` may be needed on PEP 668 distros).
- **Redis 7+** reachable on a stable IP — can be on the same node or remote (currently `192.168.118.202`).
- **Hermes Agent v0.9.0+** installed at `/root/.hermes/hermes-agent/` and `hermes` CLI on PATH (`/root/.local/bin/hermes`).
- **Obsidian vault** mounted at `/opt/obsidian/config/vaults/My-LLM-Wiki/` (or symlinked there). Sync via Relay plugin to a Mac for human visibility — optional.
- **uvx** (`pip install uv`) for code-review-graph MCP server.
- **Telegram bot token + channel ID** (bot must be admin in the channel with "Post Messages" perm).
- **Gitea repo access** (optional, only needed if you want autonomous push from agents).

## Bootstrap order

### 1. Layout
```
/var/lib/karios/
├── orchestrator/
│   ├── event_dispatcher.py       (from this repo: pipeline/orchestrator/)
│   ├── message_schemas.py
│   ├── state.json                (start with {"active_gaps": {}, "completed_gaps": []})
│   └── fan-state.json            (start with {"pending": {}})
├── coordination/requirements/    (drop ARCH-IT-ARCH-vN.md inputs here)
├── iteration-tracker/            (auto-created per gap)
├── checkpoints/<agent>/<gap>/    (auto-created)
├── agent-msg/
│   ├── inbox/orchestrator/       (file-inbox; drop JSON to inject messages)
│   ├── quarantine/               (v7.5 bad-JSON quarantine destination)
│   └── schema-violations/        (v7.6 Pydantic validation quarantine)
├── heartbeat/                    (per-agent .beat files, written every 60s)
└── agent-stream/                 (per-agent SSE progress logs)

/usr/local/bin/                   (chmod +x everything from pipeline/bin/)
/usr/local/lib/karios/            (obsidian_bridge.py + symlink target for karios-vault)

/etc/karios/
├── secrets.env                   (chmod 600; copy from pipeline/etc/secrets.env.example, fill values)
└── flush-policy.yaml             (from pipeline/etc/)

/etc/systemd/system/              (drop everything from pipeline/systemd/, then daemon-reload)

/root/.hermes/
├── config.yaml                   (from pipeline/hermes/config.yaml — tool_use_enforcement: true is critical)
└── profiles/
    ├── architect/{config.yaml, SOUL.md}
    ├── architect-blind-tester/{config.yaml, SOUL.md}
    ├── backend/{config.yaml, SOUL.md}
    ├── code-blind-tester/{config.yaml, SOUL.md}
    ├── devops/{config.yaml, SOUL.md}
    ├── frontend/{config.yaml, SOUL.md}
    ├── monitor/{config.yaml, SOUL.md}
    ├── orchestrator/{config.yaml, SOUL.md}
    └── tester/{config.yaml, SOUL.md}
    (api_key in each config.yaml is REDACTED in this repo — fill in your provider key)

/opt/obsidian/config/vaults/My-LLM-Wiki/raw/karios-pipeline/
├── decisions/    (seed from knowledge/karios-pipeline/decisions/)
├── rca/          (seed from knowledge/karios-pipeline/rca/)
├── critiques/
├── learnings/
├── fixes/
├── bugs/
└── memory/
```

### 2. One-shot install commands

```bash
# 1. Clone this repo
git clone https://github.com/hruthik46/agentvic-workflow.git /tmp/aw
cd /tmp/aw

# 2. Install Python deps (pydantic for v7.6)
pip install --break-system-packages pydantic redis

# 3. Install code-review-graph (per-repo prerequisite for v7.4 token-saving rubric)
pip install --break-system-packages uv
# Run `uvx code-review-graph build` once in each source repo to populate .code-review-graph/graph.db

# 4. Layout
mkdir -p /var/lib/karios/{orchestrator,coordination/requirements,iteration-tracker,checkpoints,agent-msg/{inbox/orchestrator,quarantine,schema-violations},heartbeat,agent-stream}
mkdir -p /etc/karios /usr/local/lib/karios
mkdir -p /opt/obsidian/config/vaults/My-LLM-Wiki/raw/karios-pipeline/{decisions,rca,critiques,learnings,fixes,bugs,memory}

# 5. Copy code
cp pipeline/orchestrator/* /var/lib/karios/orchestrator/
cp pipeline/bin/* /usr/local/bin/
cp pipeline/bin/obsidian_bridge.py /usr/local/lib/karios/
ln -sf /usr/local/lib/karios/obsidian_bridge.py /usr/local/bin/karios-vault
chmod +x /usr/local/bin/{agent-worker,karios-*,sop_engine.py,obsidian_bridge.py,a2a_protocol.py,agent-watchdog.py,agent-heartbeat.py,agent-checkpoint,agent-stream-progress}

# 6. Hermes
mkdir -p /root/.hermes/profiles
cp pipeline/hermes/config.yaml /root/.hermes/
cp -r pipeline/hermes/profiles/* /root/.hermes/profiles/
# CRITICAL: fill in api_key for each profile (search for <REDACTED-MINIMAX-API-KEY>)

# 7. Secrets
cp pipeline/etc/secrets.env.example /etc/karios/secrets.env
chmod 600 /etc/karios/secrets.env
# Fill in REDIS_PASSWORD, TELEGRAM_BOT_TOKEN, etc.
cp pipeline/etc/flush-policy.yaml /etc/karios/

# 8. Systemd
cp pipeline/systemd/karios-*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable karios-orchestrator-sub karios-architect-agent karios-architect-blind-tester \
  karios-backend-worker karios-frontend-worker karios-devops-agent karios-tester-agent \
  karios-monitor-worker karios-code-blind-tester karios-hitl-listener karios-a2a karios-watchdog \
  karios-contract-test
systemctl start karios-orchestrator-sub karios-architect-agent karios-architect-blind-tester \
  karios-backend-worker karios-frontend-worker karios-devops-agent karios-tester-agent \
  karios-monitor-worker karios-code-blind-tester karios-hitl-listener karios-a2a karios-watchdog

# 9. Seed knowledge (optional but recommended — gives agents context from prior rounds)
cp -r knowledge/karios-pipeline/* /opt/obsidian/config/vaults/My-LLM-Wiki/raw/karios-pipeline/

# 10. Smoke test
systemctl list-units 'karios-*' --no-pager | grep running | wc -l   # should be ≥ 12
karios-vault recent --limit 5
journalctl -u karios-orchestrator-sub -n 20 --no-pager
```

### 3. First dispatch (sanity test)

Drop a requirement file and the orchestrator picks it up:

```bash
cat > /var/lib/karios/coordination/requirements/REQ-SMOKE-001.md << 'EOF'
# REQ-SMOKE-001 — Health-check requirement

Verify the pipeline is alive end-to-end. Architect should produce 5 docs ≥2KB each.
Backend implements a no-op /healthz endpoint. Frontend wires a status badge.
Tester confirms 200 OK. DevOps deploys to staging. Monitor watches 5 minutes.
EOF

# Inject as a [REQUIREMENT] message
python3 -c "
import json, redis
r = redis.Redis(host='192.168.118.202', port=6379, username='karios_admin', password='<your-pass>', decode_responses=True)
r.xadd('stream:orchestrator', {
    'from': 'human',
    'to': 'orchestrator',
    'subject': '[REQUIREMENT] REQ-SMOKE-001 — Pipeline health check',
    'body': open('/var/lib/karios/coordination/requirements/REQ-SMOKE-001.md').read(),
    'gap_id': 'REQ-SMOKE-001',
    'trace_id': 'trace_smoke_001',
})
print('injected')
"

# Watch
journalctl -u karios-orchestrator-sub -f
```

You should see Telegram notifications fire on every phase boundary.

## Common bootstrap pitfalls

These are the bugs we hit during 6 meta-loops. They're already fixed in the code — but if you hit them on a fresh node, here's what they look like and where to look:

| Symptom | Root cause | File |
|---|---|---|
| 3-hour Telegram silence | env var name mismatch (`TELEGRAM_TOKEN` vs `TELEGRAM_BOT_TOKEN`) | `event_dispatcher.py` line 83 |
| Markdown messages silently rejected | `parse_mode=Markdown` + `[BRACKETED]` text | `telegram_alert()` retry path |
| Orchestrator deadlock at startup | `block=0` in `xread_once` (Redis blocks forever) | `event_dispatcher.py` `xread_once` |
| 9 agents long-poll Telegram → HTTP 409 | per-agent listener instead of centralized | `KARIOS_HITL_DISABLE_LISTENER=1` env var |
| Agent stuck on stale RECOVER message | `recover_from_checkpoints` doesn't check state.json `state=completed` | dispatcher line ~2540 |
| Backend never gets messages | dispatcher writes `stream:backend` but agent reads `stream:backend-worker` | `DISPATCH_STREAM_MAP` |
| ENAMETOOLONG creating dir | gap_id parser absorbs prose tail | `_sanitize_gap_id()` |
| Hermes produces 200-400K of prose, no tool calls | `tool_use_enforcement: auto` doesn't match MiniMax model | `/root/.hermes/config.yaml` set `true` |
| `[ARCH-REVIEWED]` JSON not parsed | `json.loads(body)` doesn't strip subject prefix or ```json fence | v7.5 patch in `handle_arch_review` |

## Personal repo for agentic-workflow files

The org Gitea repos (`karios-migration`, `karios-web`, `karios-core`, `karios-bootstrap`) have a `.gitignore` blacklist preventing pipeline-internal files from leaking. This personal repo (`agentvic-workflow`) is where they live instead. When agents auto-push, they push product code to org Gitea, and pipeline files stay here.
