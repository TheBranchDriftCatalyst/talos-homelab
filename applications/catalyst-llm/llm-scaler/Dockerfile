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

# Non-root user
RUN adduser -D -u 1000 scaler

# Copy worker script and set permissions for scaler user
COPY --chown=scaler:scaler scripts/llm-worker.sh /app/llm-worker.sh
RUN chmod 755 /app/llm-worker.sh

# Also ensure binary is readable
RUN chown scaler:scaler /app/llm-scaler

USER scaler

EXPOSE 8080 9090

ENTRYPOINT ["/app/llm-scaler"]
