# Docker Setup — Share Expense

## Table of Contents

1. [Services](#services)
2. [Local development](#local-development)
3. [Makefile reference](#makefile-reference)
4. [Environment variables](#environment-variables)
5. [Migrations](#migrations)
6. [Production](#production)
7. [Troubleshooting](#troubleshooting)

---

## Services

| Service | Image | Purpose |
|---|---|---|
| `web` | `./Dockerfile` (`development` target in dev, `production` in prod) | Django app |
| `postgres` | `postgres:18-alpine` | Database; network alias `share-expense-postgres` |
| `cloudflared` (prod only) | `cloudflare/cloudflared` | Cloudflare Tunnel: carries visitors from Cloudflare to `web` |

**No ports are published to the host.** In dev, HTTP reaches `web` through the shared `nginx-proxy` container on the external `proxy-network`, using `VIRTUAL_HOST` and `VIRTUAL_PORT=8000`. In production, the `cloudflared` service dials out to Cloudflare, so the server needs no open port, no web server and no certificate: Cloudflare serves HTTPS. `postgres` stays on the internal `share-expense-net` network only.

The data volume mounts at `/var/lib/postgresql`, which is what Postgres 18 images expect (not `/var/lib/postgresql/data`).

## Local development

```bash
make up                   # first run copies .env.example to .env; migrates, then runs runserver with auto-reload
make superuser            # first time only
```

Add the host name once: `sudo sh -c 'echo "127.0.0.1 share-expense.local" >> /etc/hosts'`. Then open http://share-expense.local.

The code is mounted into the container, so edits reload at once. After changing dependencies (`uv add ...`), run `make rebuild`.

## Makefile reference

Every target takes `ENV=dev` (default) or `ENV=prod`, which picks `docker-compose.<ENV>.yml` and `.env` / `.env.prod`. Targets marked *dev only* always use the dev stack. Plain `make` is the same as `make up`.

| Command | Description |
|---|---|
| `make up` | Build if needed and start every service |
| `make down` | Stop every service |
| `make restart` | Restart every service |
| `make rebuild` | Rebuild images and recreate containers |
| `make ps` | Service status |
| `make logs` | Follow web logs |
| `make migrate` | Apply migrations |
| `make migrations` | Generate migrations from model changes (dev only) |
| `make superuser` | Create the admin account |
| `make shell` | Bash in the web container |
| `make test` | pytest against the real Postgres (dev only) |
| `make lint` | ruff check + ruff format --check (dev only) |
| `make backup` | Gzipped database dump, keeps the newest 14 |
| `make clean` | Stop and **delete the database volume** (dev only) |

## Environment variables

| Variable | Dev default | Production | Meaning |
|---|---|---|---|
| `DJANGO_DEBUG` | `true` | `false` | Debug pages, plain static files, no HTTPS settings |
| `DJANGO_SECRET_KEY` | empty (dev key used) | **required** | Generate: `python -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `DJANGO_ALLOWED_HOSTS` | `share-expense.local,localhost` | your domain | Comma-separated |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `http://share-expense.local` | `https://<domain>` | Full origins |
| `DJANGO_SECURE_HSTS_SECONDS` | `3600` | `3600`, later `31536000` | How long browsers remember "HTTPS only" |
| `TIME_ZONE` | `Asia/Phnom_Penh` | | |
| `LOG_LEVEL` | `INFO` | | Logs are JSON lines on stdout |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `postgres` / `postgres` / `share_expense` | strong password | Used by the postgres container |
| `DATABASE_URL` | `postgres://postgres:postgres@share-expense-postgres:5432/share_expense` | same, with the real password | Used by Django |
| `AXES_FAILURE_LIMIT` | `5` | | Failed logins before a 1-hour lock |
| `CLIENT_IP_HEADER` | `HTTP_X_FORWARDED_FOR` | `HTTP_CF_CONNECTING_IP` | Header with the real visitor IP, so a login lock hits the attacker and not everyone behind the proxy |
| `CLOUDFLARE_TUNNEL_TOKEN` | — | **required** | `cloudflared tunnel token <tunnel-name>` |
| `GUNICORN_WORKERS` | — | `2` | |

`.env.example` lists all of them. Real `.env` files are never committed.

## Migrations

Django migrations live in `apps/*/migrations/`. After a model change: `make migrations`, review the new file, `make migrate`, and commit the file. In production, `scripts/start.sh` runs `migrate` before gunicorn starts.

## Production

Requirements: a server with Docker and `make`, and a domain on Cloudflare.

1. Create the tunnel and its DNS record (on any machine where `cloudflared tunnel login` was done):
   ```bash
   cloudflared tunnel create share-expense
   cloudflared tunnel route dns share-expense share-expense.example.com
   cloudflared tunnel token share-expense      # goes into CLOUDFLARE_TUNNEL_TOKEN
   ```
   If `~/.cloudflared/config.yml` names another tunnel, it overrides the name above; add `--config <empty file>` and check the `tunnelID` that `route dns` prints.
2. On the server, `cp .env.example .env.prod` and set: `DJANGO_DEBUG=false`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS=<domain>,localhost` (`localhost` is for the container health check), `DJANGO_CSRF_TRUSTED_ORIGINS=https://<domain>`, `POSTGRES_PASSWORD` (and the same password in `DATABASE_URL`), `CLIENT_IP_HEADER=HTTP_CF_CONNECTING_IP` and `CLOUDFLARE_TUNNEL_TOKEN`.
3. Start it and create the admin account:
   ```bash
   make up ENV=prod
   make superuser ENV=prod
   ```

The production image runs as a non-root user, collects static files at build time, and serves them with whitenoise. With `DJANGO_DEBUG=false`, Django redirects HTTP to HTTPS, sets secure cookies and sends HSTS. `/health/` answers on plain HTTP for uptime checks.

### Automatic deploy

Every push to `main` runs CI (`.github/workflows/ci.yml`). When the `test` job passes, the `deploy` job puts that exact commit live:

1. The GitHub runner joins your Tailscale network for the length of the job (the server has no public SSH).
2. It logs in with a deploy key whose `authorized_keys` line forces one command, `scripts/deploy.sh`, so the key cannot open a shell.
3. `scripts/deploy.sh` checks that the commit is on `main`, fast-forwards the server checkout to it, runs `make up ENV=prod`, and waits up to 60 seconds for `/health/`. A failure turns the job red and prints the last 50 web log lines. Every run is appended to `~/logs/share-expense-deploy.log` on the server.

One-time setup:

1. Tailscale admin console, Access controls: own a tag `tag:ci` and allow it to reach only the server on port 22:
   ```json
   "tagOwners": { "tag:ci": ["autogroup:admin"] },
   "grants": [ { "src": ["tag:ci"], "dst": ["<server Tailscale IP>"], "ip": ["tcp:22"] } ]
   ```
2. Tailscale admin console, Settings → OAuth clients: create a client with the `auth_keys` write scope and tag `tag:ci`. Store it in the repo: `gh secret set TS_OAUTH_CLIENT_ID` and `gh secret set TS_OAUTH_SECRET`.
3. Create a deploy key and add its public half to the server user's `~/.ssh/authorized_keys`, with the forced command in front:
   ```
   command="/home/<user>/projects/share-expense/scripts/deploy.sh",from="100.64.0.0/10",restrict ssh-ed25519 AAAA... share-expense-deploy
   ```
   Store the private half with `gh secret set DEPLOY_SSH_KEY < <key file>`, then delete the file.
4. Put the server's Tailscale IP in `SERVER` and its SSH host key in the `known_hosts` line of the `deploy` job.

Deploy by hand (same script): `scripts/deploy.sh $(git rev-parse origin/main)` on the server.

Backup: `make backup ENV=prod` writes a gzipped `pg_dump` to `~/backups/share-expense/` (change with `BACKUP_DIR=...`) and keeps the newest 14. Run it daily from cron:

```
15 3 * * * cd ~/projects/share-expense && make backup ENV=prod >> ~/backups/share-expense/backup.log 2>&1
```

Keep a copy off the server: make `~/backups/share-expense` a symlink to a folder that a cloud sync tool (for example an `rclone bisync` timer to Google Drive) already syncs. The Makefile writes through the link, and the sync copies new dumps out and removes pruned ones. Check that the sync tool's file size limit is larger than your dumps.

Restore: `gunzip -c <file> | docker compose --env-file .env.prod -f docker-compose.prod.yml exec -T postgres psql -U postgres share_expense` (into an empty database).

## Troubleshooting

| Problem | Fix |
|---|---|
| `network proxy-network declared as external, but could not be found` (dev) | Start nginx-proxy first, or `docker network create proxy-network` |
| Production site shows Cloudflare error 1033 | The tunnel is down: `make logs ENV=prod` is web only, so check `docker logs share-expense-prod-cloudflared-1` |
| Browser cannot reach `share-expense.local` | Add the `/etc/hosts` line above |
| `CSRF verification failed` in production | `DJANGO_CSRF_TRUSTED_ORIGINS` must contain the full `https://` origin |
| Login says "locked" | 5 failed attempts; wait 1 hour, or `python manage.py axes_reset` in the web container |
