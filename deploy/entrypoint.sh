#!/bin/sh
set -e

case "$1" in
  web)
    if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
      python manage.py migrate --no-input
      python manage.py ensure_admin
    fi
    exec gunicorn hoteli.wsgi \
      --bind "0.0.0.0:${PORT:-8000}" \
      --workers "${WEB_CONCURRENCY:-3}" \
      --timeout 60 \
      --access-logfile - \
      --forwarded-allow-ips "*"
    ;;
  jobs)
    exec python manage.py run_jobs
    ;;
  *)
    exec "$@"
    ;;
esac
