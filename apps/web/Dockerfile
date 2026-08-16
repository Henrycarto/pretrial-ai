# syntax=docker/dockerfile:1

# Build context is the repository root, not apps/web. The app imports two
# workspace packages as TypeScript source, so the whole workspace has to be
# present for the install and the build to resolve them.

FROM node:22-alpine AS deps
WORKDIR /repo
COPY package.json package-lock.json* turbo.json ./
COPY apps/web/package.json ./apps/web/
COPY packages/shared-types/package.json ./packages/shared-types/
COPY packages/fhir-client/package.json ./packages/fhir-client/
RUN npm ci --no-audit --no-fund

FROM node:22-alpine AS builder
WORKDIR /repo
COPY --from=deps /repo/node_modules ./node_modules
COPY . .

# These are inlined into the client bundle by Next at build time, so they
# have to be present here rather than injected into the runtime container.
# Changing a service URL means rebuilding this image.
ARG NEXT_PUBLIC_SYNTHECORE_URL=http://localhost:8001
ARG NEXT_PUBLIC_FIDELITYCHECK_URL=http://localhost:8002
ARG NEXT_PUBLIC_FHIRLINK_URL=http://localhost:8003
ENV NEXT_PUBLIC_SYNTHECORE_URL=$NEXT_PUBLIC_SYNTHECORE_URL \
    NEXT_PUBLIC_FIDELITYCHECK_URL=$NEXT_PUBLIC_FIDELITYCHECK_URL \
    NEXT_PUBLIC_FHIRLINK_URL=$NEXT_PUBLIC_FHIRLINK_URL \
    NEXT_TELEMETRY_DISABLED=1

RUN npm run build --workspace=@pretrial/web

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000

RUN addgroup -g 10001 -S nextjs && adduser -S -u 10001 -G nextjs nextjs

# Next's standalone output is not enabled, so the runner needs the built
# .next directory alongside the workspace's node_modules.
COPY --from=builder --chown=nextjs:nextjs /repo/apps/web/.next ./.next
COPY --from=builder --chown=nextjs:nextjs /repo/apps/web/package.json ./package.json
COPY --from=builder --chown=nextjs:nextjs /repo/apps/web/public ./public
COPY --from=builder --chown=nextjs:nextjs /repo/node_modules ./node_modules

USER nextjs
EXPOSE 3000

CMD ["npx", "next", "start", "-p", "3000"]
