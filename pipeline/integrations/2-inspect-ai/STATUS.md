# 2-inspect-ai — STATUS

## Code completeness: FULL (5 Tasks, 5 REAL scorers — no placeholders)

`kairos_pipeline.py` defines:

| Task | Scorer | What it actually measures |
|---|---|---|
| `vmware_audit_e2e` | `vmware_audit_score` | `git log --grep` for 6 P0/P1 bug refs in commit messages |
| `cbt_implementation_loop` | `cbt_real_test_score` | Runs `go test ./internal/providers/vmware/ -run TestCBT` against checked-out branch |
| `dispatch_orphan_recovery` | `orphan_detect_score` | Injects probe gap, polls journalctl 17 min for `ORPHAN-DETECTED`/`[FAN-OUT]`/`[CODE-REQUEST]` |
| `prose_mode_kill_retry` | `prose_mode_kill_score` | Counts `WATCHDOG SIGKILL`/`SIGTERM` events in `karios-architect-agent` journalctl |
| `blind_tester_evidence_required` | `evidence_field_populated_score` | Reads latest `e2e-results.json` under `iteration-tracker/`; scores 4 evidence fields populated >20 chars and not "placeholder"/"todo" |

## To activate

```bash
pip install --break-system-packages inspect-ai
cat > /usr/local/bin/karios-eval <<'EOF'
#!/bin/bash
exec inspect eval /root/agentic-workflow/pipeline/integrations/2-inspect-ai/kairos_pipeline.py "$@"
EOF
chmod +x /usr/local/bin/karios-eval
karios-eval@dispatch_orphan_recovery     # run a single task
karios-eval --task all                   # run all 5
```

## To schedule (nightly)

```bash
hermes cron add --name "kairos-eval-nightly" \
  --schedule "0 2 * * *" \
  --command "/usr/local/bin/karios-eval @dispatch_orphan_recovery @prose_mode_kill_retry @blind_tester_evidence_required" \
  --notify-channel telegram-hermes \
  --notify-on-failure-only
```

(The two long-running tasks `vmware_audit_e2e` + `cbt_implementation_loop` are weekly, not nightly.)

## Honest caveats

- **Tasks must run from .106**: scorers read journalctl, iteration-tracker, and the karios-migration git repo — these only exist on the dispatcher host.
- **`vmware_audit_e2e` + `cbt_implementation_loop` require pre-dispatched gaps**: the task assumes the REQ is already in the pipeline; it scores the *output*, doesn't dispatch. Wire a `karios-eval-dispatch <gap-id>` helper if you want a single-shot.
- **No Proxmox sandbox yet**: tasks declare `sandbox="docker"`. Per v7.16 research, switching to `sandbox="proxmox"` requires the Inspect AI Proxmox adapter (`pip install inspect-evals[proxmox]`) and PVE9 credentials in `~/.config/inspect/proxmox.yaml`. Documented as next step.
- **Time limits**: `vmware_audit_e2e=3600s`, `cbt_implementation_loop=7200s`, others 600-1200s. Adjust per actual pipeline cycle time.

## Where eval results land

Inspect AI writes to `~/.inspect/logs/` by default. Override:
```bash
INSPECT_LOG_DIR=/var/lib/karios/inspect-evals karios-eval --task all
```
