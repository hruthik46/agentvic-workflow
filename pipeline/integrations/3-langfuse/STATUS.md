# 3-langfuse — STATUS

## Code completeness: LIVE on 192.168.118.106

- Server: `langfuse/langfuse:2` + `postgres:15` via docker-compose
- URL: http://192.168.118.106:3001 (port 3000 was Grafana)
- Project: kairos-pipeline (auto-created via LANGFUSE_INIT_*)
- Wrapper symlinked into /var/lib/karios/orchestrator/
- Dispatcher import wired (event_dispatcher.py:60)
- All env vars in /etc/karios/secrets.env (LANGFUSE_HOST/PUBLIC_KEY/SECRET_KEY)
- Smoke-tested 2026-04-20 16:05 — 2 traces ingested via API verification

## Critical install constraint: SDK version pinning

Langfuse server is **v2.95.11** (uses Postgres-only, no ClickHouse).
Python SDK MUST be **<3.0** to match — install with:
```
pip install --break-system-packages "langfuse<3"
```
v3+/v4+ SDK uses different schema validation and will fail `auth_check`
against the v2 server with Pydantic field-missing errors.

Migration to v3 server requires deploying ClickHouse + new compose file
(see https://github.com/langfuse/langfuse/blob/main/docker-compose.yml).
Heavyweight; deferred.

## What gets traced (LIVE)

Per langfuse_dispatcher_patch.py:
- Every `send_to_agent` call → `dispatch-{agent}-{subject}` trace,
  `user_id={gap_id}`, `session_id={trace_id}`
- Every `notify_phase_transition` event → `phase-{event}` event with
  from_agent, to_agent, rating, summary

`trace_hermes_call` context manager available but not yet wired into
agent-worker (deferred to next maintenance window — requires editing
`run_hermes_pty()`).

## Operations

- Bootstrap creds: /opt/langfuse/.bootstrap.env (mode 600)
- Web UI: http://192.168.118.106:3001 (login ops@karios.local + bootstrap pwd)
- Setup script: pipeline/integrations/3-langfuse/langfuse_setup.sh

## Honest residuals

- Hermes-side trace_hermes_call NOT yet wired (only dispatcher-side is live)
- Self-hosted, Postgres-only — limited to ~50K traces/day per Langfuse v2
  guidance. Migrate to v3+ClickHouse when scale demands it.
- Bootstrap user has admin role; create real org users via web UI.
