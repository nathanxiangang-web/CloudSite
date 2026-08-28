FROM alpine:3.24.1 AS base
RUN apk add --no-cache nodejs npm

FROM base AS deps
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN npm install -g pnpm@10.15.1 --registry=https://registry.npmmirror.com --no-audit --no-fund \
  && pnpm install --frozen-lockfile --registry=https://registry.npmmirror.com

FROM base AS build
WORKDIR /app
ENV API_INTERNAL_URL=http://api:8000
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM base AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
