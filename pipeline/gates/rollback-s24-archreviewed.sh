#!/bin/bash
# Rollback session-24 arch-reviewed envelope-first refactor
set -e
TS=20260425T071141Z
cp /root/agentic-workflow/pipeline/orchestrator/event_dispatcher.py.pre-s24-archreviewed.${TS} /root/agentic-workflow/pipeline/orchestrator/event_dispatcher.py
cp /root/agentic-workflow/pipeline/gates/test_envelope_gap_id.py.pre-s24-archreviewed.${TS} /root/agentic-workflow/pipeline/gates/test_envelope_gap_id.py
cp /root/agentic-workflow/pipeline/orchestrator/event_dispatcher.py /var/lib/karios/orchestrator/event_dispatcher.py
systemctl restart karios-orchestrator-sub
echo 'rollback complete: session-24 arch-reviewed refactor reverted'
