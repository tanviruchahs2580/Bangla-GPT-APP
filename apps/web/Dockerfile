# Pinned to digests, not floating tags (AUD-EF-10 / F-11): "node:24-alpine"
# and "nginx:1.27-alpine" move under us, so two builds from the same commit
# produced different base layers. Digests resolved 2026-10-19 via the
# registry API (`docker buildx imagetools inspect <image>`).
#
#   node:24-alpine    sha256:44fce696f38ba8c987c4db89954051000bbd05ffd8d8659ba15ed4a8602e937f
#   nginx:1.27-alpine sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10
#
# To move a base: resolve the new digest and update the line; Dependabot's
# docker ecosystem raises the PR and keeps the comment in step.
FROM node:24-alpine@sha256:44fce696f38ba8c987c4db89954051000bbd05ffd8d8659ba15ed4a8602e937f AS build
WORKDIR /src

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .
ARG VITE_API_BASE=/api
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build

FROM nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/dist /usr/share/nginx/html

# Non-root (F-11): the stock nginx image starts its master as root to bind
# :80 and drop its workers to the `nginx` user. The deployed posture is
# enforced in docker-compose.yml instead: rootfs read-only, /var/cache/nginx
# and /run on tmpfs, ALL capabilities dropped except CHOWN/SETGID/SETUID/
# NET_BIND_SERVICE, and no-new-privileges (verified: page served 200 with
# exactly that set). Switching to nginxinc/nginx-unprivileged would move the
# listener to :8080 and break the compose/`Caddy -> web:80` contract, so the
# cap-dropped master is the accepted trade-off. Never run this image without
# the compose service's hardening.
EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["wget", "-qO-", "http://127.0.0.1/", "--spider"]

CMD ["nginx", "-g", "daemon off;"]
