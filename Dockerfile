# Pinned to a digest, not a floating tag: "3.12-slim" moves under us, so two
# builds from the same commit produced different base layers and a rebuild
# could silently change what ships (AUD-0029).
#
#   sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
#     = python:3.12-slim, resolved 2026-10-10 via the registry API.
#
# To move the base: docker pull python:3.12-slim, read the digest from
# `docker image inspect --format '{{index .RepoDigests 0}}'`, update this line,
# and re-run the trivy scan. Never replace the digest with the tag.
FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1 AS runtime

# Single stage, deliberately (DOCK-01/F-089). Every Python artifact is a
# prebuilt wheel pinned by hash in constraints.txt, and this image installs no
# compiler toolchain, so there is nothing to build in a separate stage: a
# builder stage would pull the same base again and copy the same site-packages
# with no size or cache gain. The single stage is also the stage trivy scans,
# so what is scanned is exactly what runs.

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# OCI provenance labels (F-153): the pipeline attests the pushed digest, but
# nothing inside the image let an inspector map a running container back to a
# commit. build-push-action feeds the ARGs in release.yml and the CI docker
# job; the defaults keep a plain `docker build .` working.
ARG APP_VERSION=dev
ARG APP_REVISION=unknown
LABEL org.opencontainers.image.title="bangla-gpt-api" \
      org.opencontainers.image.description="Bangla GPT APP API - NCTB-grounded tutor service" \
      org.opencontainers.image.source="https://github.com/tanviruchahs2580/Bangla-GPT-APP" \
      org.opencontainers.image.revision="${APP_REVISION}" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.licenses="MIT"

# Security patching of base-layer packages with available vendor fixes
# (rescanned with trivy; remaining unfixed advisories documented in the
# validation report — no vendor fix published yet, exposure mitigated).
# Full `upgrade` (not just targeted installs): the trivy gate fails on ANY
# fixable HIGH/CRITICAL, and new Debian advisories (sqlite/perl/...) appear
# continuously — targeted installs are whack-a-mole that reds the pipeline.
#
# The two explicitly installed packages are version-pinned (hadolint DL3008).
# Pinning them is safe only because the base image is digest-pinned: the
# candidate version below is the one that digest resolves to, so the pin is
# deterministic. `apt-get upgrade` still floats every OTHER package, which is
# the deliberate trade-off documented above — it is why two builds of this
# image are content-identical but not byte-identical.
#
# To refresh: re-resolve the candidate in the pinned base
#   docker run --rm --entrypoint sh python:3.12-slim@sha256:<digest> \
#     -c "apt-get update -qq && apt-cache policy openssl libssl3t64"
# and update both the digest and the versions here together.
ARG OPENSSL_VERSION=3.5.7-1~deb13u3
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
        "openssl=${OPENSSL_VERSION}" \
        "libssl3t64=${OPENSSL_VERSION}" \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*
# postgresql-client above ships pg_dump. Without it scripts/backup_loop.py
# raised FileNotFoundError every cycle on this image and swallowed it - the
# documented `--profile backup` service could never produce a Postgres
# dump (audit F3). Debian's version is unpinned on purpose: pg_dump only
# talks to the server over the wire and tolerates newer servers.

COPY apps/api/constraints.txt ./apps/api/constraints.txt

# Dependency layer FIRST, source LAST: the hash-verified install below is the
# most expensive layer in the image, and it used to sit AFTER `COPY src`, so
# every source change invalidated it and rebuilt the whole dependency tree.
# constraints.txt alone now defines this layer's cache key.
RUN pip install --no-cache-dir --require-hashes -r ./apps/api/constraints.txt

COPY apps/api/pyproject.toml ./apps/api/
COPY apps/api/worker.py ./apps/api/worker.py
COPY apps/api/src ./apps/api/src
COPY apps/api/alembic ./apps/api/alembic
COPY apps/api/alembic.ini ./apps/api/alembic.ini

# Two steps, deliberately. constraints.txt pins exact versions AND carries
# hashes, which switches pip into hash-checking mode; a local directory has no
# single artifact to hash, so the project itself is installed --no-deps after
# every third-party package has been verified against its hash (AUD-0010).
# gunicorn and uvicorn-worker come from the lock too, so nothing in this image
# is resolved at build time.
RUN pip install --no-cache-dir --no-deps ./apps/api

# Fixed numeric uid/gid (hadolint DL3066): a named user resolves to a
# different id on different base images, which silently breaks bind-mounted
# volume ownership. 10001 is inside the unprivileged range on Debian.
ARG APP_UID=10001
ARG APP_GID=10001
RUN groupadd --gid "${APP_GID}" appuser \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /data /backups && chown -R "${APP_UID}:${APP_GID}" /app /data /backups
USER ${APP_UID}:${APP_GID}

# Number of Uvicorn worker processes; scale horizontally via this env var.
ENV WEB_CONCURRENCY=2

EXPOSE 8000

# /ready, not /health: /health is the constant {"status":"ok"} and stayed
# green while the database, cache or provider were down -- the compose
# healthcheck and the release gate already read /ready, and the deploy
# contract (apps/api/eval/parked_specs/test_deploy_contracts.py) pins the
# image to the same probe.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3).status==200 else 1)"]

CMD ["sh", "-c", "exec gunicorn bangla_gpt_api.main:app -k uvicorn_worker.UvicornWorker -w ${WEB_CONCURRENCY} -b 0.0.0.0:8000 --timeout 60 --graceful-timeout 30 --max-requests 1000 --max-requests-jitter 100 --access-logfile -"]
