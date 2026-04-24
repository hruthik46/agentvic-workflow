#!/bin/bash
# Rollback for R-3 Theme 1 session #3: [CODING-COMPLETE]/[FAN-IN] envelope-first guard + handler-path gate fixture
# Created 2026-04-24 18:58 UTC, baseline md5 705c36ea024b41873e8e2cfb92a0e36a
set -euo pipefail
TS=20260424T185803Z
echo "Restoring dispatcher (live + source) and gate files from TS=$TS"
cp -v /var/lib/karios/orchestrator/event_dispatcher.py.pre-coding-complete-guard.$TS /var/lib/karios/orchestrator/event_dispatcher.py
cp -v /root/agentic-workflow/pipeline/orchestrator/event_dispatcher.py.pre-coding-complete-guard.$TS /root/agentic-workflow/pipeline/orchestrator/event_dispatcher.py
cp -v /root/agentic-workflow/pipeline/gates/test_envelope_gap_id.py.pre-handler-fixture.$TS /root/agentic-workflow/pipeline/gates/test_envelope_gap_id.py
cp -v /root/agentic-workflow/pipeline/gates/run-all-gate-tests.sh.pre-handler-fixture.$TS /root/agentic-workflow/pipeline/gates/run-all-gate-tests.sh
echo "---md5 verification (must equal 705c36ea024b41873e8e2cfb92a0e36a):"
md5sum /var/lib/karios/orchestrator/event_dispatcher.py /root/agentic-workflow/pipeline/orchestrator/event_dispatcher.py
echo "---revert handler-path fixture if any added:"
rm -fv /root/agentic-workflow/pipeline/gates/envelope_gap_id_fixtures/handler_*.json
echo "Rollback complete. Service NOT restarted (was not restarted by forward change either)."
