# Build stage
FROM golang:1.22-alpine AS builder

WORKDIR /app

# Install ca-certificates for HTTPS
RUN apk add --no-cache ca-certificates

# Copy go mod files
COPY go.mod go.sum ./
RUN go mod download

# Copy source code
COPY . .

# Build the binary
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build \
    -ldflags="-w -s" \
    -o /catalyst-dns-sync \
    ./cmd/controller

# Final stage
FROM scratch

# Copy CA certificates from builder
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/

# Copy binary from builder
COPY --from=builder /catalyst-dns-sync /catalyst-dns-sync

# Use non-root user
USER 65532:65532

# Expose ports
EXPOSE 8080 8081 8082

# Run the controller
ENTRYPOINT ["/catalyst-dns-sync"]
