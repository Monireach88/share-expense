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

**No ports are published to the host.** HTTP reaches `web` through the shared `nginx-proxy` container on the external `proxy-network`, using `VIRTUAL_HOST` and `VIRTUAL_PORT=8000`. `postgres` stays on the internal `share-expense-net` network only.

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
| `AXES_IPWARE_PROXY_COUNT` | `1` | `1` | Proxies in front of the app, so the real client IP is used |
| `VIRTUAL_HOST` | — | your domain | nginx-proxy route and Let's Encrypt certificate (prod compose) |
| `GUNICORN_WORKERS` | — | `2` | |

`.env.example` lists all of them. Real `.env` files are never committed.

## Migrations

Django migrations live in `apps/*/migrations/`. After a model change: `make migrations`, review the new file, `make migrate`, and commit the file. In production, `scripts/start.sh` runs `migrate` before gunicorn starts.

## Production

Requirements on the server: Docker, the `nginx-proxy` container and its Let's Encrypt companion on `proxy-network`, and a DNS record for your domain.

```bash
cp .env.example .env.prod
# set DJANGO_DEBUG=false, DJANGO_SECRET_KEY, DJANGO_ALLOWED_HOSTS, DJANGO_CSRF_TRUSTED_ORIGINS,
# POSTGRES_PASSWORD (and the same password in DATABASE_URL), VIRTUAL_HOST
make up ENV=prod
make superuser ENV=prod
```

The production image runs as a non-root user, collects static files at build time, and serves them with whitenoise. With `DJANGO_DEBUG=false`, Django redirects HTTP to HTTPS, sets secure cookies and sends HSTS. `/health/` answers on plain HTTP for uptime checks.

Backup: `docker compose --env-file .env.prod -f docker-compose.prod.yml exec postgres pg_dump -U postgres share_expense > backup.sql`.

## Troubleshooting

| Problem | Fix |
|---|---|
| `network proxy-network declared as external, but could not be found` | Start nginx-proxy first, or `docker network create proxy-network` |
| Browser cannot reach `share-expense.local` | Add the `/etc/hosts` line above |
| `CSRF verification failed` in production | `DJANGO_CSRF_TRUSTED_ORIGINS` must contain the full `https://` origin |
| Login says "locked" | 5 failed attempts; wait 1 hour, or `python manage.py axes_reset` in the web container |
