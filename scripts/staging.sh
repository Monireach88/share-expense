#!/usr/bin/env bash
# Staging: a stoppable copy of production that runs the latest develop branch.
#   scripts/staging.sh up       build develop, start, copy production data the first time
#   scripts/staging.sh down     stop everything; the staging database is kept
#   scripts/staging.sh refresh  replace the staging data with a fresh copy of production
#   scripts/staging.sh status | logs
# STAGING_REF=<branch or commit> runs something other than origin/develop, e.g. a feature
# branch before its pull request is merged.
# develop is checked out in its own folder (a git worktree next to this one), so this
# folder stays on main for production deploys (scripts/deploy.sh).
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
TREE="${STAGING_DIR:-$(dirname "$REPO")/share-expense-staging}"
URL="https://share-expense-staging.monireach.com"
REF="${STAGING_REF:-origin/develop}"

staging() { (cd "$TREE" && docker compose --env-file .env.staging -f docker-compose.staging.yml "$@"); }
production() { (cd "$REPO" && docker compose --env-file .env.prod -f docker-compose.prod.yml "$@"); }
psql_staging() { staging exec -T postgres sh -c "psql -tA -v ON_ERROR_STOP=1 -U \"\$POSTGRES_USER\" \"\$POSTGRES_DB\" $*"; }

checkout() {
  git -C "$REPO" fetch --quiet origin
  if [ ! -e "$TREE/.git" ]; then
    git -C "$REPO" worktree add --quiet --detach "$TREE" "$REF"
  else
    git -C "$TREE" checkout --quiet --detach "$REF"
  fi
  # The settings file is private (a link into Drive), so it is linked, never copied.
  ln -sfn "$(readlink "$REPO/.env.staging")" "$TREE/.env.staging"
}

copy_production_data() {
  echo "Copying the production database into staging (production is only read)..."
  staging stop web cloudflared >/dev/null 2>&1 || true
  staging exec -T postgres sh -c 'dropdb -U "$POSTGRES_USER" --if-exists --force "$POSTGRES_DB" && createdb -U "$POSTGRES_USER" "$POSTGRES_DB"'
  production exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" --no-owner --no-privileges "$POSTGRES_DB"' \
    | psql_staging -q >/dev/null
}

tunnel_ready() { ! grep -q '^CLOUDFLARE_TUNNEL_TOKEN=pending' "$TREE/.env.staging"; }

up() {
  checkout
  staging build --quiet web
  staging up -d --wait postgres
  if [ "$(psql_staging -c "\"select to_regclass('public.django_migrations') is not null\"")" != "t" ]; then
    copy_production_data
  fi
  staging up -d --wait web  # scripts/start.sh applies new migrations first
  if tunnel_ready; then staging up -d cloudflared; else echo "No tunnel token yet: not reachable from outside."; fi
  echo "Staging runs $(git -C "$TREE" log --oneline -1) at $URL"
}

case "${1:-}" in
  up) up ;;
  down) [ -e "$TREE/.git" ] && staging down ;;
  refresh)
    checkout
    staging up -d --wait postgres
    copy_production_data
    staging up -d --wait web
    if tunnel_ready; then staging up -d cloudflared; fi
    echo "Staging data replaced with a copy of production."
    ;;
  status) staging ps ;;
  logs) staging logs -f --tail 50 web ;;
  *) echo "usage: scripts/staging.sh up | down | refresh | status | logs" >&2; exit 2 ;;
esac
