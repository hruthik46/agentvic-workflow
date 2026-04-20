# 3-langfuse — STATUS

## Code completeness: FULL + LIVE-READY

Two files:
- `kairos_langfuse_wrapper.py` — soft-import client, three context managers (`trace_dispatch`, `trace_hermes_call`, `trace_phase_event`), `init_langfuse()`, docker-compose template
- `langfuse_dispatcher_patch.py` — monkey-patches `event_dispatcher.notify_phase_transition` + `send_to_agent` at import time. Soft-fails if env vars missing.

Wire-up is **one import line** at top of `event_dispatcher.py`:
```python
import langfuse_dispatcher_patch  # noqa: F401
```

Without `LANGFUSE_HOST/PUBLIC_KEY/SECRET_KEY` set in env, the patch self-disables and the dispatcher runs unchanged. Safe to import unconditionally.

## To activate

```bash
# 1. Bring up Langfuse server (Postgres + UI)
cat /root/agentic-workflow/pipeline/integrations/3-langfuse/kairos_langfuse_wrapper.py \
    | grep -A 30 "DOCKER_COMPOSE_TEMPLATE" \
    > /opt/langfuse/docker-compose.yml
cd /opt/langfuse
# Replace <set-on-target> placeholders:
#   POSTGRES_PASSWORD via openssl rand -base64 24
#   NEXTAUTH_SECRET   via openssl rand -base64 32
#   SALT              via openssl rand -base64 32
#   ENCRYPTION_KEY    via openssl rand -hex 32
docker compose up -d

# 2. Open http://192.168.118.106:3000 → sign in → create project → copy keys

# 3. Append to /etc/karios/secrets.env:
echo "LANGFUSE_HOST=http://localhost:3000" >> /etc/karios/secrets.env
echo "LANGFUSE_PUBLIC_KEY=pk-lf-..." >> /etc/karios/secrets.env
echo "LANGFUSE_SECRET_KEY=sk-lf-..." >> /etc/karios/secrets.env

# 4. Add the import line + restart
ln -sf /root/agentic-workflow/pipeline/integrations/3-langfuse/langfuse_dispatcher_patch.py \
       /var/lib/karios/orchestrator/langfuse_dispatcher_patch.py
# Edit /var/lib/karios/orchestrator/event_dispatcher.py:
#   add `import langfuse_dispatcher_patch  # noqa: F401` near the top of imports
systemctl restart karios-orchestrator-sub

# 5. Verify
journalctl -u karios-orchestrator-sub --since '1 min ago' | grep langfuse
# Expect: [langfuse] initialized (host=http://localhost:3000)
#         [langfuse-patch] active: notify_phase_transition + send_to_agent wrapped
```

## What gets traced

- **Every `send_to_agent` call** → `dispatch-{agent}-{subject[:30]}` trace, with `gap_id` as `user_id` (groups all dispatches for one gap)
- **Every `notify_phase_transition` event** → `phase-{event}` event with `from_agent`, `to_agent`, `rating`, `summary`
- **Every Hermes generation** (when `trace_hermes_call` is wired into agent-worker — pending) → `hermes-{agent}` generation with model, prompt_chars, status, errors

## Honest caveats

- **Hermes generation traces NOT yet wired** — only dispatcher-side traces are in the v7.17 patch. Adding agent-worker side requires editing `/usr/local/bin/agent-worker run_hermes_pty()`, deferred to next deploy.
- **Self-hosted server burden**: Postgres + Langfuse server eats ~500MB RAM, ~100MB disk per 100K traces. Set up `/etc/cron.d/langfuse-prune` for >30-day trace deletion if running long-term.
- **Trace data is full prompts + responses** — secrets in prompts WILL appear in Langfuse UI. Consider redaction (Langfuse SDK supports `metadata.scrubbing` callback) before exposing to non-admins.
- **Soft-import means typos in env-var names silently disable tracing**. Verify with the journalctl check above after restart.

## Cost / scale

Self-hosted: free. Cloud Langfuse Cloud: ~$50/month at our trace volume (~10K traces/day per agent × 9 agents). Self-host wins for KAIROS.
