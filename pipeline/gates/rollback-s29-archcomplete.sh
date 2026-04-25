#!/bin/bash
# Rollback script for session-29: [ARCH-COMPLETE] envelope-first refactor
# One-command recovery: restores dispatcher and harness to pre-s29 state
set -euo pipefail
TIMESTAMP=20260425T080411Z
DISP_SRC=/root/agentic-workflow/pipeline/orchestrator/event_dispatcher.py
DISP_BAK=/root/agentic-workflow/pipeline/orchestrator/event_dispatcher.py.bak.s29.
HARNESS_SRC=/root/agentic-workflow/pipeline/gates/test_envelope_gap_id.py
HARNESS_BAK=/root/agentic-workflow/pipeline/gates/test_envelope_gap_id.py.pre-s29.

echo '[rollback-s29] restoring dispatcher from backup...'
cp ${DISP_BAK} ${DISP_SRC}
echo '[rollback-s29] restoring harness from backup...'
cp ${HARNESS_BAK} ${HARNESS_SRC}
echo '[rollback-s29] copying restored dispatcher to live...'
cp ${DISP_SRC} /var/lib/karios/orchestrator/event_dispatcher.py
echo '[rollback-s29] restarting service...'
systemctl restart karios-orchestrator
echo '[rollback-s29] done. Verify: md5sum ${DISP_SRC} ${DISP_BAK}'
