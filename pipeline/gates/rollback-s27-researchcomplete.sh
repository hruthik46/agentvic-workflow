#!/bin/bash
# Rollback for session-27: [RESEARCH-COMPLETE] envelope-first refactor
# One-command recovery:
#   bash /root/agentic-workflow/pipeline/gates/rollback-s27-researchcomplete.sh
set -e
BAK=/root/agentic-workflow/pipeline/orchestrator/event_dispatcher.py.bak-s27-20260425-034058
SRC=/root/agentic-workflow/pipeline/orchestrator/event_dispatcher.py
LIVE=/var/lib/karios/orchestrator/event_dispatcher.py
echo 'Rollback s27 researchcomplete: restoring from backup'
cp "${BAK}" "${SRC}"
cp "${SRC}" "${LIVE}"
systemctl restart karios-orchestrator
sleep 2
systemctl is-active karios-orchestrator
md5sum "${SRC}" "${LIVE}"
echo 'Rollback complete. Verify: 41d4523c60b8f0b21321479ec8571179'
