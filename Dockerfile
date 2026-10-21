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
    && rm -rf /var/lib/apt/lists/*

COPY apps/api/constraints.txt ./apps/api/constraints.txt
COPY apps/api/pyproject.toml ./apps/api/
COPY apps/api/worker.py ./apps/api/worker.py
COPY apps/api/src ./apps/api/src
COPY apps/api/alembic ./apps/api/alembic
COPY apps/api/alembic.ini ./apps/api/alembic.ini

# A5-02 prompt registry: the versioned prompt files live at apps/api/prompts,
# OUTSIDE the import package, so the wheel cannot carry them as package-data
# (setuptools package-data is relative to the package directory) and a plain
# wheel install resolves the loader's checkout-relative default to
# site-packages' parent, where no prompts exist. The image therefore ships the
# directory at its checkout path and points the loader at it explicitly; the
# prompt-registry manifest makes a missing registry a loud boot failure, so
# this COPY + ENV pair is what keeps the container bootable.
COPY apps/api/prompts ./apps/api/prompts
ENV BANGLA_GPT_PROMPTS_DIR=/app/apps/api/prompts

# Two steps, deliberately. constraints.txt pins exact versions AND carries
# hashes, which switches pip into hash-checking mode; a local directory has no
# single artifact to hash, so the project itself is installed --no-deps after
# every third-party package has been verified against its hash (AUD-0010).
# gunicorn and uvicorn-worker come from the lock too, so nothing in this image
# is resolved at build time.
RUN pip install --no-cache-dir --require-hashes -r ./apps/api/constraints.txt \
    && pip install --no-cache-dir --no-deps ./apps/api

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

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status==200 else 1)"]

CMD ["sh", "-c", "exec gunicorn bangla_gpt_api.main:app -k uvicorn_worker.UvicornWorker -w ${WEB_CONCURRENCY} -b 0.0.0.0:8000 --timeout 60 --graceful-timeout 30 --max-requests 1000 --max-requests-jitter 100 --access-logfile -"]
