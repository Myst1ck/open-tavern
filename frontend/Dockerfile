FROM node:22-slim

WORKDIR /app

# Enable pnpm via corepack
RUN corepack enable

# Install dependencies first (cache layer)
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

# Copy source
COPY . .

# Build production bundle
RUN pnpm build

# Drop root: run the server as the image's unprivileged `node` user.
RUN chown -R node:node /app
USER node

EXPOSE 5173

# Serve built assets
CMD ["pnpm", "exec", "vite", "preview", "--host", "0.0.0.0", "--port", "5173"]