# Digest-pinned (audit F9). Refresh with scripts/update_image_digests.py.
FROM node:24-alpine@sha256:06d7adf3e0ef61a13f1d28682726366f97a15aa1888c934d3ecec86c33918b53 AS build
WORKDIR /src

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .
ARG VITE_API_BASE=/api
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build

FROM nginx:1.29-alpine
# apk upgrade: the pinned base carries months-old alpine packages
# (brotli/c-ares/curl HIGH/CRITICAL findings blocked the release scan).
RUN apk upgrade --no-cache

COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["wget", "-qO-", "http://127.0.0.1/", "--spider"]

CMD ["nginx", "-g", "daemon off;"]
