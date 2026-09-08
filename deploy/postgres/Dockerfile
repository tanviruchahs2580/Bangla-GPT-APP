# S5.7 -- Postgres 16 with the pgBackRest binary baked in, so the database
# container can run archive-push itself and the backup sidecar (same image,
# shared socket + repo volumes) can run backup/restore without network hops.
# The stanza config and nightly loop are COPYed (not bind-mounted): Windows
# Docker Desktop bind mounts silently yield missing files for host paths
# with spaces, and config drift between image and host is avoided anyway --
# this file lives in the repo and every change is a rebuild.
FROM postgres:16

RUN apt-get update \
    && apt-get install -y --no-install-recommends pgbackrest \
    && rm -rf /var/lib/apt/lists/*

COPY pgbackrest.conf /etc/pgbackrest/pgbackrest.conf
COPY pgbackrest_nightly.sh /usr/local/bin/pgbackrest_nightly.sh
RUN chmod 0644 /etc/pgbackrest/pgbackrest.conf \
    && chmod 0755 /usr/local/bin/pgbackrest_nightly.sh
