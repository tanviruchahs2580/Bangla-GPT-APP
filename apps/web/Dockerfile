# Pinned to digests, not floating tags (AUD-EF-10 / F-11): "node:24-alpine"
# and "nginxinc/nginx-unprivileged:1.27-alpine" move under us, so two builds
# from the same commit produced different base layers. Digests resolved
# 2026-10-19 via the registry API (`docker buildx imagetools inspect <image>`).
#
#   node:24-alpine
#     sha256:44fce696f38ba8c987c4db89954051000bbd05ffd8d8659ba15ed4a8602e937f
#   nginxinc/nginx-unprivileged:1.27-alpine
#     sha256:65e3e85dbaed8ba248841d9d58a899b6197106c23cb0ff1a132b7bfe0547e4c0
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

# AUD-B-24: the UNPRIVILEGED nginx variant. The stock nginx image starts its
# master as root (to bind :80 and chown its cache), which is the one container
# in the stack that ran as uid 0. This image runs the master AND the workers
# as uid 101 and listens on 8080 (a non-root process cannot bind :80 without
# a capability), so no capability is required at all. The compose service
# keeps rootfs read-only with /tmp on tmpfs (the image's pid/temp paths),
# drops ALL capabilities and never lets a child gain any; Caddy proxies
# `web:8080`. Verified by building and running exactly this image: page
# served 200 as uid 101 (evidence E-R3-ws4-b24-web-nonroot).
FROM nginxinc/nginx-unprivileged:1.27-alpine@sha256:65e3e85dbaed8ba248841d9d58a899b6197106c23cb0ff1a132b7bfe0547e4c0
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/dist /usr/share/nginx/html

USER 101
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["wget", "-qO-", "http://127.0.0.1:8080/", "--spider"]

CMD ["nginx", "-g", "daemon off;"]
