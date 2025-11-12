# syntax=docker/dockerfile:1

# Build stage
FROM golang:1.22-alpine AS builder

WORKDIR /workspace

# Install build dependencies
RUN apk add --no-cache git ca-certificates tzdata

# Copy go mod files
COPY go.mod go.sum ./
RUN go mod download

# Copy source code
COPY cmd/ cmd/
COPY internal/ internal/

# Build with version information
ARG VERSION=dev
ARG GIT_COMMIT=unknown
ARG BUILD_DATE=unknown

RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build \
    -ldflags="-w -s \
    -X main.version=${VERSION} \
    -X main.gitCommit=${GIT_COMMIT} \
    -X main.buildDate=${BUILD_DATE}" \
    -o catalyst-dns-sync \
    ./cmd/catalyst-dns-sync

# Final stage - distroless
FROM gcr.io/distroless/static:nonroot

LABEL org.opencontainers.image.title="catalyst-dns-sync"
LABEL org.opencontainers.image.description="Kubernetes DNS sync daemon for Technitium DNS Server"
LABEL org.opencontainers.image.source="https://github.com/yourusername/catalyst-dns-sync"

WORKDIR /

# Copy binary from builder
COPY --from=builder /workspace/catalyst-dns-sync /catalyst-dns-sync

# Copy CA certificates
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/

# Use nonroot user
USER 65532:65532

EXPOSE 9090 8080

ENTRYPOINT ["/catalyst-dns-sync"]
