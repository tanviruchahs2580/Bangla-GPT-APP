FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Security patching of base-layer packages with available vendor fixes
# (rescanned with trivy; remaining unfixed advisories documented in the
# validation report — no vendor fix published yet, exposure mitigated).
# Full `upgrade` (not just targeted installs): the trivy gate fails on ANY
# fixable HIGH/CRITICAL, and new Debian advisories (sqlite/perl/...) appear
# continuously — targeted installs are whack-a-mole that reds the pipeline.
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends openssl libssl3t64 \
    && rm -rf /var/lib/apt/lists/*

COPY apps/api/pyproject.toml ./apps/api/
COPY apps/api/worker.py ./apps/api/worker.py
COPY apps/api/src ./apps/api/src
COPY apps/api/alembic ./apps/api/alembic
COPY apps/api/alembic.ini ./apps/api/alembic.ini
RUN pip install --no-cache-dir ./apps/api "gunicorn>=23.0" "uvicorn-worker>=0.2"

RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /data /backups && chown -R appuser:appuser /app /data /backups
USER appuser

# Number of Uvicorn worker processes; scale horizontally via this env var.
ENV WEB_CONCURRENCY=2

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status==200 else 1)"]

CMD ["sh", "-c", "exec gunicorn bangla_gpt_api.main:app -k uvicorn_worker.UvicornWorker -w ${WEB_CONCURRENCY} -b 0.0.0.0:8000 --timeout 60 --graceful-timeout 30 --max-requests 1000 --max-requests-jitter 100 --access-logfile -"]
