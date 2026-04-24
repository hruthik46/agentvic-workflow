#!/bin/bash
# Rollback for R-3 Theme 1 session #4: envelope-promotion in _file_inbox_fallback.
# Restores the pre-session-4 dispatcher state from timestamped backups.
# Backup timestamp: 20260424T202651Z (md5 af168290d51dd87118ffc94d37f565be).
set -eu

TS=20260424T202651Z
SRC_BAK=/root/agentic-workflow/pipeline/orchestrator/event_dispatcher.py.pre-s4-envelope-promote.${TS}
LIVE_BAK=/var/lib/karios/orchestrator/event_dispatcher.py.pre-s4-envelope-promote.${TS}
SRC=/root/agentic-workflow/pipeline/orchestrator/event_dispatcher.py
LIVE=/var/lib/karios/orchestrator/event_dispatcher.py
GATE_BAK=/root/agentic-workflow/pipeline/gates/test_envelope_gap_id.py.pre-s4.${TS}
GATE=/root/agentic-workflow/pipeline/gates/test_envelope_gap_id.py

for f in "$SRC_BAK" "$LIVE_BAK" "$GATE_BAK"; do
  [ -f "$f" ] || { echo "FATAL: backup missing: $f"; exit 2; }
done

EXPECTED=af168290d51dd87118ffc94d37f565be
for f in "$SRC_BAK" "$LIVE_BAK"; do
  got=$(md5sum "$f" | cut -d" " -f1)
  [ "$got" = "$EXPECTED" ] || { echo "FATAL: backup md5 mismatch on $f: got $got expected $EXPECTED"; exit 2; }
done

cp -p "$SRC_BAK"  "$SRC"
cp -p "$LIVE_BAK" "$LIVE"
cp -p "$GATE_BAK" "$GATE"

echo "Rollback OK. Live + source + gate restored to md5 ${EXPECTED}."
echo "NOTE: If commits were landed, also run: git -C /root/agentic-workflow revert <session-4-sha>"
echo "NOTE: Service restart not required unless activation was attempted."
