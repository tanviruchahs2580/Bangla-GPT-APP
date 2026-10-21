# Pinned to digests, not floating tags (AUD-EF-10 / F-11): "node:24-bookworm-slim"
# and "nginxinc/nginx-unprivileged:1.27-alpine" move under us, so two builds
# from the same commit produced different base layers. Digests resolved via the
# registry API (`docker buildx imagetools inspect <image>`); node resolved
# 2026-10-21, nginx 2026-10-19.
#
#   node:24-bookworm-slim
#     sha256:a5f4366e834695d5f363b920c104953a535d3a9864d1bdf74566a0ebe01daee5
#   nginxinc/nginx-unprivileged:1.27-alpine
#     sha256:65e3e85dbaed8ba248841d9d58a899b6197106c23cb0ff1a132b7bfe0547e4c0
#
# The build stage was `node:24-alpine` until AUD-G-15. `npm run build` now ends
# in `scripts/prerender.mjs`, which drives the built app in Chromium and writes
# `dist/<route>/index.html` for the seven public routes; Playwright ships no
# musl build of Chromium, so on Alpine that step degraded to a loud skip and the
# image shipped the un-prerendered SPA -- the exact LCP/CLS problem it exists to
# fix. Debian slim is glibc, so `playwright install --with-deps` works there.
#
# To move a base: resolve the new digest and update the line; Dependabot's
# docker ecosystem raises the PR and keeps the comment in step.
FROM node:24-bookworm-slim@sha256:a5f4366e834695d5f363b920c104953a535d3a9864d1bdf74566a0ebe01daee5 AS build
WORKDIR /src

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# AUD-G-15: the Chromium the prerender step drives. `--with-deps` pulls the
# shared libraries Chromium needs (libnss3, libatk, fonts) that the slim image
# does not carry; they stay in this stage, never in the runtime image.
RUN npx playwright install --with-deps chromium

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
