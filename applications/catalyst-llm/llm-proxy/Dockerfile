# ============================================
# Stage 1: Build React UI
# ============================================
FROM node:22-alpine AS ui-builder

WORKDIR /build/ui

# Copy package files
COPY ui/package.json ui/yarn.lock* ./

# Install dependencies
RUN yarn install --frozen-lockfile 2>/dev/null || yarn install

# Copy source and build
COPY ui/ ./
RUN yarn build

# ============================================
# Stage 2: Build Go binary
# ============================================
FROM golang:1.22-alpine AS go-builder

WORKDIR /build

# Download dependencies first (cached layer)
COPY go.mod go.sum ./
RUN go mod download

# Copy source and build
COPY *.go ./
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o llm-proxy .

# ============================================
# Stage 3: Runtime
# ============================================
FROM alpine:3.19

RUN apk add --no-cache \
    bash \
    aws-cli \
    openssh-client \
    jq \
    curl

WORKDIR /app

# Copy Go binary
COPY --from=go-builder /build/llm-proxy /app/

# Copy React UI static files
COPY --from=ui-builder /build/ui/dist /app/ui/dist

# Non-root user
RUN adduser -D -u 1000 proxy

# Copy worker script and set permissions
COPY --chown=proxy:proxy scripts/llm-worker.sh /app/llm-worker.sh
RUN chmod 755 /app/llm-worker.sh

# Ensure files are readable
RUN chown -R proxy:proxy /app

USER proxy

# HTTP API + Prometheus metrics
EXPOSE 8080 9090

# Set UI directory for Go to serve static files
ENV UI_DIR=/app/ui/dist

ENTRYPOINT ["/app/llm-proxy"]
