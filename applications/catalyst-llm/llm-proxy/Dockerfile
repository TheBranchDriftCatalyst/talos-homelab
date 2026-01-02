# Build stage
FROM golang:1.22-alpine AS builder

WORKDIR /build
COPY go.mod go.sum ./
RUN go mod download

COPY *.go ./

RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o llm-proxy .

# Runtime stage
FROM alpine:3.19

RUN apk add --no-cache \
    bash \
    aws-cli \
    openssh-client \
    jq \
    curl

WORKDIR /app

# Copy binary
COPY --from=builder /build/llm-proxy /app/

# Non-root user
RUN adduser -D -u 1000 proxy

# Copy worker script and set permissions
COPY --chown=proxy:proxy scripts/llm-worker.sh /app/llm-worker.sh
RUN chmod 755 /app/llm-worker.sh

# Ensure binary is readable
RUN chown proxy:proxy /app/llm-proxy

USER proxy

EXPOSE 8080 9090

ENTRYPOINT ["/app/llm-proxy"]
