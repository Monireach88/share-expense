#!/usr/bin/env sh
# Production start: apply migrations, then hand the process to gunicorn (exec, so SIGTERM reaches it).
set -e
python manage.py migrate --noinput
exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers "${GUNICORN_WORKERS:-2}" --access-logfile - --no-control-socket
