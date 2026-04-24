#!/bin/bash
# R-6 rollback — remove core.hooksPath setting from pipeline repos.
# Returns each repo to default git hook behavior (no hooks).

set -uo pipefail

REPOS=(
  /root/karios-source-code/karios-migration
  /root/karios-source-code/karios-playwright
  /root/karios-source-code/karios-web
  /root/agentic-workflow
)

for repo in "${REPOS[@]}"; do
  if [ ! -d "$repo/.git" ]; then
    continue
  fi
  cd "$repo"
  PREV=$(git config core.hooksPath 2>/dev/null || echo "(default)")
  git config --unset core.hooksPath 2>/dev/null || true
  POST=$(git config core.hooksPath 2>/dev/null || echo "(default)")
  echo "rolled back $repo: $PREV -> $POST"
done
