#!/bin/bash
# Session-12 rollback: restore event_dispatcher.py before v7.73 retirement
set -e
BACKUP=/root/agentic-workflow/pipeline/orchestrator/event_dispatcher.py.bak-session12-20260425004158
SOURCE=/root/agentic-workflow/pipeline/orchestrator/event_dispatcher.py
LIVE=/var/lib/karios/orchestrator/event_dispatcher.py
echo [rollback] Restoring from backup
cp "$BACKUP" "$SOURCE"
cp "$BACKUP" "$LIVE"
systemctl restart karios-orchestrator
sleep 2
systemctl is-active karios-orchestrator
md5sum "$SOURCE" "$LIVE"
echo [rollback] Done
