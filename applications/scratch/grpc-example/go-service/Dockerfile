# Build stage - using Go 1.24 for latest grpc/protobuf support
FROM golang:1.24-alpine AS builder

WORKDIR /app

# Install protoc and plugins
RUN apk add --no-cache protobuf make git

# Copy proto first (from parent context)
COPY proto/ ./proto/

# Copy go mod files for caching
COPY go-service/go.mod go-service/go.sum* ./
RUN go mod download || true

# Copy source
COPY go-service/ ./

# Generate proto files - latest versions
RUN mkdir -p gen/echopb && \
    go install google.golang.org/protobuf/cmd/protoc-gen-go@latest && \
    go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest && \
    protoc --go_out=gen/echopb --go_opt=paths=source_relative \
           --go-grpc_out=gen/echopb --go-grpc_opt=paths=source_relative \
           -I proto proto/echo.proto

# Build - run go mod tidy to generate go.sum with all dependencies
RUN go mod tidy && CGO_ENABLED=0 GOOS=linux go build -o /grpc-server .

# Runtime stage
FROM alpine:3.19

RUN apk add --no-cache ca-certificates

COPY --from=builder /grpc-server /grpc-server

EXPOSE 50051 9090

ENTRYPOINT ["/grpc-server"]
