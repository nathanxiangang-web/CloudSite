FROM alpine:3.24.1 AS base
RUN apk add --no-cache nodejs npm

FROM base AS deps
WORKDIR /app
ENV NODE_OPTIONS=--max-old-space-size=256
ENV npm_config_jobs=1
RUN npm install -g pnpm@10.15.1
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --no-frozen-lockfile

FROM base AS build
WORKDIR /app
ENV API_INTERNAL_URL=http://api:8000
ENV NODE_OPTIONS=--max-old-space-size=384
RUN npm install -g pnpm@10.15.1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN pnpm exec next build --webpack

FROM base AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV HOSTNAME=0.0.0.0
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
