# S5.7 -- Postgres 16 with the pgBackRest binary baked in, so the database
# container can run archive-push itself and the backup sidecar (same image,
# shared socket + repo volumes) can run backup/restore without network hops.
# The stanza config and nightly loop are COPYed (not bind-mounted): Windows
# Docker Desktop bind mounts silently yield missing files for host paths
# with spaces, and config drift between image and host is avoided anyway --
# this file lives in the repo and every change is a rebuild.
#
# Pinned to a digest, not a floating tag (AUD-EF-10 / F-11): "postgres:16"
# moves under us, so two builds from the same commit produced different base
# layers. Digest resolved 2026-10-19 via the registry API
# (`docker buildx imagetools inspect postgres:16`).
#
#   sha256:ca0bd484cb98bf4b24eb1010e73fb3fcbd6714d240fbc1a10eea5b7dbecb641d
#     = postgres:16
#
# To move the base: docker buildx imagetools inspect postgres:16, update the
# digest, then refresh PGBACKREST_VERSION below from
#   docker run --rm --entrypoint sh postgres:16@sha256:<digest> \
#     -c "apt-get update -qq && apt-cache policy pgbackrest"
# and rebuild + re-run the restore drill (scripts/pgbackrest_drill.sh).
# The version pin is only safe because the base is digest-pinned: it is the
# candidate that digest resolves to. Never replace the digest with the tag.
FROM postgres:16@sha256:ca0bd484cb98bf4b24eb1010e73fb3fcbd6714d240fbc1a10eea5b7dbecb641d

# hadolint DL3008: pinned to the candidate version in the digest-pinned base
# (2.59.3-1.pgdg13+1, resolved 2026-10-19). A digest bump must refresh this
# version in the same commit; the build fails loudly if they drift.
ARG PGBACKREST_VERSION=2.59.3-1.pgdg13+1
RUN apt-get update \
    && apt-get install -y --no-install-recommends "pgbackrest=${PGBACKREST_VERSION}" \
    && rm -rf /var/lib/apt/lists/*

COPY pgbackrest.conf /etc/pgbackrest/pgbackrest.conf
COPY pgbackrest_nightly.sh /usr/local/bin/pgbackrest_nightly.sh
RUN chmod 0644 /etc/pgbackrest/pgbackrest.conf \
    && chmod 0755 /usr/local/bin/pgbackrest_nightly.sh
