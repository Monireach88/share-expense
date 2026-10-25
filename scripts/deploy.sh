#!/usr/bin/env bash
# Deploy one tested commit of main on the production server.
# GitHub Actions runs this over SSH as the deploy key's forced command (see DOCKER_SETUP.md),
# so it is the only thing that key can do. The commit arrives in SSH_ORIGINAL_COMMAND.
# By hand: scripts/deploy.sh <40-character commit of main>
set -euo pipefail

LOG="$HOME/logs/share-expense-deploy.log"
HEALTH_URL="https://share-expense.monireach.com/health/"

main() {
  cd "$(dirname "$0")/.."
  local sha="${SSH_ORIGINAL_COMMAND:-${1:-}}"
  if [[ ! "$sha" =~ ^[0-9a-f]{40}$ ]]; then
    echo "refused: expected a 40-character commit, got '${sha}'"
    return 2
  fi
  echo "$(date -Is) deploying $sha"
  git fetch --quiet origin main
  if ! git merge-base --is-ancestor "$sha" origin/main; then
    echo "refused: $sha is not on main"
    return 3
  fi
  git checkout --quiet main
  git merge --quiet --ff-only "$sha"
  make up ENV=prod >/dev/null
  for _ in $(seq 30); do
    if curl -fsS -o /dev/null "$HEALTH_URL"; then
      echo "$(date -Is) live: $(git log --oneline -1)"
      return 0
    fi
    sleep 2
  done
  echo "$(date -Is) FAILED: $HEALTH_URL did not answer within 60 seconds"
  docker compose --env-file .env.prod -f docker-compose.prod.yml logs --tail 50 web
  return 1
}

# One line on purpose: bash reads a script while it runs, and the git merge above may
# replace this file, so the call and the exit must already be read before it starts.
mkdir -p "$(dirname "$LOG")"; main "$@" 2>&1 | tee -a "$LOG"; exit "${PIPESTATUS[0]}"
