FROM node:20-slim

WORKDIR /app

# Enable pnpm via corepack
RUN corepack enable

# Install dependencies first (cache layer)
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# Copy source
COPY . .

# Build production bundle
RUN pnpm build

EXPOSE 5173

# Serve built assets
CMD ["pnpm", "preview", "--", "--host", "0.0.0.0", "--port", "5173"]