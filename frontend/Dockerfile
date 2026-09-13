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
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
