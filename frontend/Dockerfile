FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Set at Cloud Build / Cloud Run deploy (build-time). Use your backend Cloud Run URL, no trailing slash.
# NEXT_PUBLIC_* → browser calls API directly (needs backend CORS). If unset, browser uses /api/v1 rewrites via BACKEND_URL.
ARG NEXT_PUBLIC_API_BASE_URL
ARG BACKEND_URL
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
ENV BACKEND_URL=$BACKEND_URL
ENV NEXT_TELEMETRY_DISABLED=1

RUN npm run build

FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV HOSTNAME=0.0.0.0

COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force

COPY --from=builder /app/.next ./.next

CMD ["sh", "-c", "exec npm run start -- -p ${PORT:-8080}"]
