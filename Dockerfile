# Production image for Hoteli (used by AWS ECS, docker compose and other container hosts).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    WEB_CONCURRENCY=3

WORKDIR /app
RUN useradd --create-home --uid 10001 hoteli

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=hoteli:hoteli . .
RUN SECRET_KEY=build-only DEBUG=False python manage.py collectstatic --no-input \
    && chmod +x deploy/entrypoint.sh

USER hoteli
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz/' % os.environ.get('PORT', '8000'), timeout=4)"

ENTRYPOINT ["/app/deploy/entrypoint.sh"]
# "web" serves the site; "jobs" runs the background scheduler; anything else is executed as-is.
CMD ["web"]
