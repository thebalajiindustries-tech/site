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

FROM node:20-slim
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app ./
EXPOSE 3000
CMD ["npm", "start"]
