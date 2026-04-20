# KAIROS Pipeline Integrations

Per the v7.16 harness research (knowledge/HARNESS-AND-HERMES-RESEARCH-2026-04-20.md),
five frameworks were ranked top-ROI for the KAIROS multi-agent pipeline. This
directory holds the integration code for each.

## Status snapshot (2026-04-20)

| # | Integration | Status | What's wired | What requires manual step |
|---|---|---|---|---|
| 1 | DSPy + GEPA | CODE COMPLETE | All trainset extraction + LM config + GEPA.compile() implemented; CLI `karios-evolve` | `pip install dspy-ai gepa`; needs ≥5 sessions per agent before first evolution |
| 2 | Inspect AI | CODE COMPLETE | 5 Tasks with REAL scorers (no placeholders); CLI `karios-eval` | `pip install inspect-ai`; tasks `vmware_audit_e2e` + `cbt_implementation_loop` need their input REQs already dispatched |
| 3 | Langfuse | LIVE-READY | `langfuse_dispatcher_patch.py` monkey-patches `notify_phase_transition` + `send_to_agent`; soft-fails if env vars missing | `docker-compose up` per `kairos_langfuse_wrapper.py:DOCKER_COMPOSE_TEMPLATE`; populate `/etc/karios/secrets.env` with `LANGFUSE_HOST/PUBLIC_KEY/SECRET_KEY`; restart orchestrator |
| 4 | Hermes obsidian-bridge plugin | ASPIRATIONAL FORMAT | `__init__.py` + `plugin.yaml` follow speculative generic-lifecycle-hook format | Hermes 0.9.0 only supports `memory` + `context_engine` plugin slots; the standalone `obsidian_bridge.py` (already wired into `agent-worker:976-989`) is the LIVE integration. Migrate when Hermes ships generic hooks |
| 5 | Holographic memory + per-agent profiles | CONFIG-ONLY | `setup_per_agent_profiles.sh` script + per-profile `config.yaml` blocks | Run script + restart 8 agent services. Hermes already ships the `memory/holographic` provider |

## Layout

```
integrations/
├── README.md                              # this file
├── 1-dspy-gepa/
│   ├── kairos-evolve.py                   # FULL implementation (no TODOs)
│   └── STATUS.md
├── 2-inspect-ai/
│   ├── kairos_pipeline.py                 # 5 Tasks + REAL scorers
│   └── STATUS.md
├── 3-langfuse/
│   ├── kairos_langfuse_wrapper.py         # client + context managers + docker-compose template
│   ├── langfuse_dispatcher_patch.py       # monkey-patch wire-in for event_dispatcher.py
│   └── STATUS.md
├── 4-hermes-plugin/
│   ├── __init__.py                        # aspirational lifecycle-hook format
│   ├── plugin.yaml                        # aspirational manifest
│   └── STATUS.md                          # honest "standalone obsidian_bridge.py is LIVE; this is a future format"
└── 5-holographic-memory/
    ├── README.md                          # setup steps + risks + validation queries
    └── setup_per_agent_profiles.sh        # idempotent setup script
```

## Apply order (when ready to deploy)

1. **Langfuse** — lowest risk; soft-fails. Bring docker-compose up first, populate secrets, then restart `karios-orchestrator-sub`.
2. **Holographic memory + per-agent profiles** — one-time setup; requires restarting all 8 agent services. Do during a quiet window. Provides per-agent isolated memory + trust scoring.
3. **Inspect AI** — install + run nightly via `karios-eval --task all` cron entry. Non-disruptive; tasks self-contained.
4. **DSPy + GEPA** — install + run weekly per agent (`karios-evolve --all --iterations 5`). Reads from `~/.hermes/sessions/`, writes to `/var/lib/karios/orchestrator/profiles_evolved/<agent>.txt`. `prompt_builder.py` mtime-loads on next dispatch.
5. **Hermes plugin** — defer until Hermes 0.10+ ships generic lifecycle-hook plugin slots. Standalone `obsidian_bridge.py` covers the use case today.

## CLIs (installed by setup)

- `/usr/local/bin/karios-eval` — wraps `inspect eval`
- `/usr/local/bin/karios-evolve` — wraps `python kairos-evolve.py`

## Cross-references

- `knowledge/HARNESS-AND-HERMES-RESEARCH-2026-04-20.md` — ranking + ROI rationale
- `pipeline/hermes/V716-PROVIDER-PATCH.md` — Hermes provider adapter patch (already LIVE)
- `/etc/karios/secrets.env` — destination for new env vars (LANGFUSE_*, MINIMAX_API_KEY)
