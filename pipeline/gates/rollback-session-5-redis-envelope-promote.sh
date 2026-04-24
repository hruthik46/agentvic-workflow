#!/usr/bin/env bash
# Rollback for R-3 Theme 1 session #5 — redis-inbox envelope-promote.
# Restores dispatcher (source + live), gate runner, and gate shell wrapper
# from the pre-s5 timestamped backups, then runs the gate suite to confirm
# pre-s5 state. Idempotent: if any backup is missing, aborts before partial
# restore. Does NOT restart karios-orchestrator-sub.service — service was
# untouched in session #5; restart still gated on session #6 advisor approval.
set -euo pipefail

TS=20260424T210344Z

SRC_DISP=/root/agentic-workflow/pipeline/orchestrator/event_dispatcher.py
LIVE_DISP=/var/lib/karios/orchestrator/event_dispatcher.py
GATE_PY=/root/agentic-workflow/pipeline/gates/test_envelope_gap_id.py
GATE_SH=/root/agentic-workflow/pipeline/gates/run-all-gate-tests.sh

for f in "${SRC_DISP}.pre-s5-redis-promote.${TS}" \
         "${LIVE_DISP}.pre-s5-redis-promote.${TS}" \
         "${GATE_PY}.pre-s5-redis-promote.${TS}" \
         "${GATE_SH}.pre-s5-redis-promote.${TS}"; do
  if [[ ! -f "$f" ]]; then
    echo "FATAL: missing backup $f — aborting before partial restore" >&2
    exit 2
  fi
done

cp -p "${SRC_DISP}.pre-s5-redis-promote.${TS}"  "${SRC_DISP}"
cp -p "${LIVE_DISP}.pre-s5-redis-promote.${TS}" "${LIVE_DISP}"
cp -p "${GATE_PY}.pre-s5-redis-promote.${TS}"   "${GATE_PY}"
cp -p "${GATE_SH}.pre-s5-redis-promote.${TS}"   "${GATE_SH}"

# Remove fixtures introduced in session #5 (safe: they only back s5 changes)
FIX_DIR=/root/agentic-workflow/pipeline/gates/envelope_gap_id_fixtures
for f in redisinbox_neg_no_subject_key.json \
         redisinbox_neg_junk_token.json \
         redisinbox_pos_envelope_wins_over_wrong_subject.json \
         redisinbox_pos_subject_promoted_when_envelope_absent.json; do
  [[ -f "$FIX_DIR/$f" ]] && rm -f "$FIX_DIR/$f"
done

md5sum "${SRC_DISP}" "${LIVE_DISP}"
echo
echo "=== gate suite (post-rollback) ==="
bash "${GATE_SH}"
