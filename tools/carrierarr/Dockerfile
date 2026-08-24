# carrierarr Dockerfile
# Multi-stage build for minimal runtime image

# Build stage
FROM golang:1.22-alpine AS builder

WORKDIR /app

# Install build dependencies
RUN apk add --no-cache git

# Copy go mod files
COPY go.mod go.sum ./
RUN go mod download

# Copy source
COPY . .

# Build binary
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o carrierarr ./cmd/main.go

# Runtime stage
FROM alpine:3.19

WORKDIR /app

# Install runtime dependencies
RUN apk add --no-cache \
    bash \
    curl \
    jq \
    aws-cli \
    openssh-client

# Copy binary
COPY --from=builder /app/carrierarr /app/carrierarr

# Copy scripts
COPY scripts/ /app/scripts/

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8090/health || exit 1

# Default port
EXPOSE 8090

# Run
ENTRYPOINT ["/app/carrierarr"]
CMD ["-addr=:8090"]
