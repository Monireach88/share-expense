# ── Base: Python + locked production dependencies ─────────────────────────────
FROM python:3.14-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:0.7.13 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ── Development: dev tools, code is mounted by docker-compose.dev.yml ─────────
FROM base AS development
RUN uv sync --frozen --no-install-project
COPY . .
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

# ── Production: non-root, static files collected at build time ────────────────
FROM base AS production
COPY . .
RUN DJANGO_SECRET_KEY=collectstatic-only python manage.py collectstatic --noinput \
    && addgroup --system --gid 1001 app \
    && adduser --system --uid 1001 --ingroup app app
USER app
EXPOSE 8000
CMD ["/app/scripts/start.sh"]
