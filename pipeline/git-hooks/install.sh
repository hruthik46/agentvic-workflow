#!/bin/bash
# R-6 install script — sets core.hooksPath in each agent-writable pipeline repo.
# Idempotent: running again is safe, reports the current state.
# Reference: kairos-pipeline-structural-audit-2026-04-24 (R-6).

set -uo pipefail

HOOK_DIR=/root/agentic-workflow/pipeline/git-hooks

if [ ! -x "$HOOK_DIR/pre-commit" ]; then
  echo "FATAL: hook not found or not executable at $HOOK_DIR/pre-commit"
  exit 1
fi

REPOS=(
  /root/karios-source-code/karios-migration
  /root/karios-source-code/karios-playwright
  /root/karios-source-code/karios-web
  /root/agentic-workflow
)

for repo in "${REPOS[@]}"; do
  if [ ! -d "$repo/.git" ]; then
    echo "SKIP $repo — not a git repo"
    continue
  fi
  cd "$repo"
  PREV=$(git config core.hooksPath 2>/dev/null || echo "(default)")
  git config core.hooksPath "$HOOK_DIR"
  echo "installed in $repo (was: $PREV)"
done
