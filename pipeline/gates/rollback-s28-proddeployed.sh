#!/usr/bin/env bash
# Rollback for session-28: [PROD-DEPLOYED] envelope-first refactor
# Restores event_dispatcher.py and test_envelope_gap_id.py to pre-s28 state
set -euo pipefail

BACKUP_DISP=/root/agentic-workflow/pipeline/orchestrator/event_dispatcher.py.bak.s28.20260425T035255Z
BACKUP_GATE=/root/agentic-workflow/pipeline/gates/test_envelope_gap_id.py.pre-s28-proddeployed.20260425T035255Z
LIVE_DISP=/var/lib/karios/orchestrator/event_dispatcher.py
SOURCE_DISP=/root/agentic-workflow/pipeline/orchestrator/event_dispatcher.py
SOURCE_GATE=/root/agentic-workflow/pipeline/gates/test_envelope_gap_id.py

echo '[rollback-s28] Restoring dispatcher source from backup...'
cp "$BACKUP_DISP" "$SOURCE_DISP"
echo '[rollback-s28] Syncing live from source...'
cp "$SOURCE_DISP" "$LIVE_DISP"
echo '[rollback-s28] Restoring gate harness from backup...'
cp "$BACKUP_GATE" "$SOURCE_GATE"
echo '[rollback-s28] Restarting karios-orchestrator...'
systemctl restart karios-orchestrator
sleep 2
systemctl is-active karios-orchestrator
echo '[rollback-s28] Done. Verify: md5sum $SOURCE_DISP $LIVE_DISP'
