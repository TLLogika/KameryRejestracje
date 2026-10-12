# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm
ARG APP_UID=1000
ARG APP_GID=1000
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 ALPR_CACHE_DIR=/app/data/model-cache
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid "$APP_GID" app \
    && useradd --uid "$APP_UID" --gid "$APP_GID" --home-dir /app --no-create-home app \
    && mkdir -p /app/data /app/dsecret /app/secret /app/logi \
    && chown app:app /app/data /app/dsecret /app/secret /app/logi
COPY requirements-docker.lock ./requirements-docker.lock
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then \
        PIP_CERT=/run/secrets/proxy_ca pip install -r requirements-docker.lock; \
    else pip install -r requirements-docker.lock; fi
COPY app ./app
COPY scripts/pull_events.py ./scripts/pull_events.py
USER app
EXPOSE 10000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:10000/', timeout=3)"
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "10000", "--timeout-graceful-shutdown", "5"]
