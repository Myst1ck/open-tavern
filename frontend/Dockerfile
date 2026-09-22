# syntax=docker/dockerfile:1

# ── Builder: install deps and produce the production bundle ──────────────────
FROM node:22-slim AS builder

WORKDIR /app

# Enable pnpm via corepack
RUN corepack enable

# Install dependencies first (cache layer)
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

# Copy source
COPY . .

# Base path baked into the bundle at build time; defaults to root for the
# container. Override with --build-arg VITE_BASE=/tavern/ for subpath deploys.
ARG VITE_BASE=/
ENV VITE_BASE=$VITE_BASE

# PWA display name baked into the manifest at build time; container ships the
# product name rather than the dev default.
ARG VITE_PWA_NAME="Open Tavern"
ENV VITE_PWA_NAME=$VITE_PWA_NAME

# Build production bundle
RUN pnpm build

# ── Runtime: built assets + preview server only ──────────────────────────────
FROM node:22-slim AS runtime

WORKDIR /app

# Backend proxy target used by `vite preview` at runtime (docker network name).
ENV OPEN_TAVERN_PROXY_TARGET=http://backend:8000 \
    NODE_ENV=production

# `vite preview` is a devDependency, so its node_modules must ship; only the
# built assets and the preview config are copied from the builder.
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/vite.config.ts ./vite.config.ts

# Drop root: run the server as the image's unprivileged `node` user.
RUN chown -R node:node /app
USER node

EXPOSE 5173

# Serve built assets
CMD ["node_modules/.bin/vite", "preview", "--host", "0.0.0.0", "--port", "5173"]