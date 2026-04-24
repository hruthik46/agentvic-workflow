#!/bin/bash
# R-4 master fixture runner — runs every gate's fixture suite, aggregates pass/fail.
# Add new gates by putting their test runner in this script.
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
if [ "$FAIL_ANY" = '0' ]; then
  echo '=== ALL GATE FIXTURES PASSED ==='
  exit 0
else
  echo '=== ONE OR MORE GATE FIXTURES FAILED ==='
  exit 1
fi
