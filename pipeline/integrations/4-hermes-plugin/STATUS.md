# 4-hermes-plugin — STATUS

## Code completeness: ASPIRATIONAL (not loadable by Hermes 0.9.0)

`__init__.py` + `plugin.yaml` follow a speculative "generic lifecycle hook" plugin
format with `register_hook("on_session_start"|"on_session_end"|"post_tool_call")`.

**Hermes 0.9.0 does not have a generic lifecycle plugin slot.** Inspecting
`/root/.hermes/hermes-agent/plugins/` shows only two plugin categories:
- `plugins/memory/<name>/` — memory providers (`holographic`, `supermemory`, `honcho`, `openviking`, `hindsight`)
- `plugins/context_engine/<name>/` — context compressors

The on_session_end hook in Hermes 0.9.0 is a method on the **memory provider class**,
not a generic plugin hook. Drop-in registration of a `kairos-obsidian-bridge` plugin
won't be picked up by the loader.

## What IS live (the actual integration)

The standalone `/var/lib/karios/orchestrator/obsidian_bridge.py` is wired into
`/usr/local/bin/agent-worker` at lines 489 (read), 524 (brief), 976-989 (write_critique
on every Hermes session end). This covers the same use case the plugin would handle:
- Read vault context before Hermes invocation
- Write critique to vault after Hermes invocation
- Manual `/vault-search`, `/vault-recent`, `/vault-write` via the `karios-vault` CLI

## Forward path

Two options to migrate the standalone shim into a Hermes-native plugin:

1. **Wait for Hermes generic hooks** — track `hermes-agent` releases for an
   `on_session_end` / `post_tool_call` plugin slot outside the memory category.
   When it ships, the `__init__.py` here is most of the work; just confirm the
   `register_hook` API name + signature.

2. **Subclass the memory provider** — make `kairos-obsidian-bridge` a memory
   provider that delegates storage to `holographic` (or whichever provider is
   selected) AND triggers the obsidian write side-effect on `on_session_end`.
   Awkward — overloads the provider semantics — but loadable today.

We're choosing **option 1**: leave the file as documentation of the desired
interface, and refactor when Hermes ships generic hooks.

## To migrate when ready

```bash
# Once Hermes ships generic lifecycle plugin slots:
mkdir -p /root/.hermes/plugins/lifecycle/kairos-obsidian-bridge
cp __init__.py plugin.yaml /root/.hermes/plugins/lifecycle/kairos-obsidian-bridge/
# Verify the register_hook API matches Hermes' new contract
# Remove the standalone hooks in agent-worker:489/524/976
systemctl restart karios-architect-agent  # ... and the other 7 agents
```

## What's loadable from this dir today

Nothing. This dir is documentation + scaffolding for a future Hermes version.
The live integration is at:
- `/var/lib/karios/orchestrator/obsidian_bridge.py`
- `/usr/local/bin/agent-worker` (lines 489, 524, 976-989)
- `/usr/local/bin/karios-vault` (CLI)
