# Build stage
FROM golang:1.22-alpine AS builder

WORKDIR /build
COPY go.mod go.sum ./
RUN go mod download

COPY *.go ./

RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w" -o llm-scaler .

# TODO: we want ot use catalyst-images:hacker probably for this right now with go
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
COPY --from=builder /build/llm-scaler /app/

# Copy worker script (will be mounted via ConfigMap in K8s)
# For local testing, you can mount the script
COPY scripts/llm-worker.sh /app/llm-worker.sh
RUN chmod +x /app/llm-worker.sh

# Non-root user
RUN adduser -D -u 1000 scaler
USER scaler

EXPOSE 8080 9090

ENTRYPOINT ["/app/llm-scaler"]
