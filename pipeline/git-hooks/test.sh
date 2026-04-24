#!/bin/bash
# R-4 fixture runner for the R-6 pre-commit hook.
# For each fixture file: create a throwaway git repo, stage the file, run the
# hook, assert exit code matches the directory (positive=0, negative=non-zero).
# Returns 0 if all fixtures matched their expected outcome; non-zero otherwise.

set -u

HOOK=/root/agentic-workflow/pipeline/git-hooks/pre-commit
FIXTURES=/root/agentic-workflow/pipeline/git-hooks/fixtures

if [ ! -x "$HOOK" ]; then
  echo "FATAL: hook not executable at $HOOK"
  exit 2
fi

FAILS=0
PASSES=0

run_fixture() {
  local fixture_file="$1"
  local expected="$2"   # "pass" or "fail"
  local name=$(basename "$fixture_file")

  local tmp=$(mktemp -d)
  cd "$tmp" || return 1
  git init -q
  git config user.email fixture@test
  git config user.name FixtureTest
  git config core.hooksPath /root/agentic-workflow/pipeline/git-hooks
  cp "$fixture_file" "./staged_$name"
  git add "./staged_$name" 2>/dev/null

  # Capture exit code of commit; we don't care about its stdout.
  git commit -m "fixture test" >/dev/null 2>&1
  local code=$?

  if [ "$expected" = "pass" ]; then
    if [ "$code" = "0" ]; then
      echo "  OK   positive/$name (hook accepted, exit 0)"
      PASSES=$((PASSES+1))
    else
      echo "  FAIL positive/$name (hook rejected but should have accepted, exit $code)"
      FAILS=$((FAILS+1))
    fi
  else
    if [ "$code" != "0" ]; then
      echo "  OK   negative/$name (hook rejected, exit $code)"
      PASSES=$((PASSES+1))
    else
      echo "  FAIL negative/$name (hook accepted but should have rejected)"
      FAILS=$((FAILS+1))
    fi
  fi

  cd / && rm -rf "$tmp"
}

echo "=== positive fixtures (expect PASS) ==="
for f in "$FIXTURES"/positive/*; do
  [ -f "$f" ] && run_fixture "$f" pass
done

echo
echo "=== negative fixtures (expect FAIL) ==="
for f in "$FIXTURES"/negative/*; do
  [ -f "$f" ] && run_fixture "$f" fail
done

echo
echo "=== summary: $PASSES pass, $FAILS fail ==="
if [ "$FAILS" -eq 0 ]; then
  echo "RESULT: ALL FIXTURES MATCHED EXPECTED OUTCOME"
  exit 0
else
  echo "RESULT: $FAILS FIXTURE(S) FAILED"
  exit 1
fi
