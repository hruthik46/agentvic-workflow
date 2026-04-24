#!/bin/bash
# R-4 master fixture runner — runs every gate's fixture suite, aggregates pass/fail.
# Add new gates by appending a block to this script.
set -u

FAIL_ANY=0

echo '=== R-6 pre-commit hook fixtures ==='
if /root/agentic-workflow/pipeline/git-hooks/test.sh; then
  echo 'R-6: all fixtures matched expected outcome'
else
  echo 'R-6: FIXTURE FAILURE'
  FAIL_ANY=1
fi

echo
echo '=== v7.50 live-probe / real-env-probe gate fixtures ==='
if python3 /root/agentic-workflow/pipeline/gates/test_v7_50.py; then
  echo 'v7.50: all fixtures matched expected outcome'
else
  echo 'v7.50: FIXTURE FAILURE'
  FAIL_ANY=1
fi

echo
echo '=== SOUL.md inline-Python lint ==='
if python3 /root/agentic-workflow/pipeline/gates/test_soul_md_python.py; then
  echo 'SOUL.md: all inline Python snippets parse cleanly (templates substituted)'
else
  echo 'SOUL.md: one or more snippets failed to parse — ARCH-IT-091 class regression possible'
  FAIL_ANY=1
fi

echo
echo '=== R-3 Theme 1 envelope-first gap_id gate ==='
if python3 /root/agentic-workflow/pipeline/gates/test_envelope_gap_id.py; then
  echo 'envelope-gap-id: all fixtures matched expected outcome'
else
  echo 'envelope-gap-id: FIXTURE FAILURE'
  FAIL_ANY=1
fi

echo
if [ "$FAIL_ANY" = '0' ]; then
  echo '=== ALL GATE FIXTURES PASSED ==='
  exit 0
else
  echo '=== ONE OR MORE GATE FIXTURES FAILED ==='
  exit 1
fi
