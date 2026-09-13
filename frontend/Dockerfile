FROM node:20-slim AS build
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
# NEXT_PUBLIC_* vars are baked into the client bundle at BUILD time, so this
# must be passed as a Docker build argument (Render: set it in the service's
# "Build Arguments" / "Docker Build Args" settings), not just a runtime env var.
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build

# --- runtime image ---
# `output: "standalone"` (next.config.mjs) makes Next trace only the deps
# server.js actually needs and copy them into .next/standalone, so the
# runtime image below no longer needs the full node_modules or the
# TypeScript/build toolchain -- much smaller image, faster pull + boot on
# Render's free tier after a cold start.
FROM node:20-slim
WORKDIR /app
ENV NODE_ENV=production
# Next.js standalone's server.js binds to $HOSTNAME if it's set, and Docker
# containers get HOSTNAME set to the container ID by default. That makes the
# server listen only on that specific (often unreachable) interface instead
# of all interfaces, so Render's edge can never reach it -- the container
# logs "Ready" and looks healthy, but every request 502s. Forcing 0.0.0.0
# makes it bind on all interfaces, which is what the platform edge expects.
ENV HOSTNAME=0.0.0.0
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
