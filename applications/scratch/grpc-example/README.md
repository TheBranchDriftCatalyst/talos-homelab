# gRPC Example - Go & Python Polyglot

A demonstration of gRPC communication between a Go service and a Python service, with shared protobuf definitions and Prometheus metrics.

## Architecture

```
┌─────────────────┐         gRPC          ┌──────────────────┐
│   Go Service    │◄─────────────────────►│  Python Service  │
│                 │                        │                  │
│  Port: 50051    │                        │  Port: 50052     │
│  Metrics: 9090  │                        │  Metrics: 9091   │
└─────────────────┘                        └──────────────────┘
         │                                          │
         └──────────────┬───────────────────────────┘
                        ▼
              ┌─────────────────┐
              │   Prometheus    │
              │ ServiceMonitors │
              └─────────────────┘
```

Both services:
- Implement the `EchoService` (unary + streaming)
- Periodically call each other to demonstrate cross-service communication
- Expose Prometheus metrics

## Prerequisites

### For local proto generation:

```bash
# Install protoc
brew install protobuf

# Install Go plugins
go install google.golang.org/protobuf/cmd/protoc-gen-go@latest
go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest

# Install Python tools
pip install grpcio-tools
```

### For testing:

```bash
# Install grpcurl
brew install grpcurl
```

## Usage

### Development with Tilt

```bash
# From repo root
tilt up

# Or just the scratch stack
tilt up -- --only grpc-go --only grpc-python
```

### Manual Deployment

```bash
# Apply namespace first
kubectl apply -k infrastructure/base/namespaces/

# Build and push images (requires local registry)
cd applications/scratch/grpc-example

# Build Go service
docker build -t localhost:5000/grpc-go:latest -f go-service/Dockerfile .
docker push localhost:5000/grpc-go:latest

# Build Python service
docker build -t localhost:5000/grpc-python:latest -f python-service/Dockerfile .
docker push localhost:5000/grpc-python:latest

# Update image refs in k8s manifests, then:
kubectl apply -k k8s/
```

### Generate Proto Files (locally)

```bash
cd proto
make all      # Generate Go + Python
make go       # Go only
make python   # Python only
make clean    # Remove generated files
```

## Testing

### Test with grpcurl

```bash
# Port-forward the Go service
kubectl port-forward -n scratch svc/grpc-go 50051:50051

# List services (uses reflection)
grpcurl -plaintext localhost:50051 list

# Call Echo
grpcurl -plaintext -d '{"message": "Hello", "sender": "grpcurl"}' \
    localhost:50051 echo.EchoService/Echo

# Same for Python service
kubectl port-forward -n scratch svc/grpc-python 50052:50052
grpcurl -plaintext -d '{"message": "Hello", "sender": "grpcurl"}' \
    localhost:50052 echo.EchoService/Echo
```

### View Logs

```bash
# All gRPC example logs
kubectl logs -n scratch -l app.kubernetes.io/part-of=grpc-example -f

# Go service only
kubectl logs -n scratch -l app=grpc-go -f

# Python service only
kubectl logs -n scratch -l app=grpc-python -f
```

### Check Metrics

```bash
# Go metrics
kubectl port-forward -n scratch svc/grpc-go 9090:9090
curl http://localhost:9090/metrics | grep grpc

# Python metrics
kubectl port-forward -n scratch svc/grpc-python 9091:9091
curl http://localhost:9091/metrics | grep grpc
```

## Metrics Exposed

### Go Service (go-grpc-prometheus)

- `grpc_server_started_total` - Total RPCs started
- `grpc_server_handled_total` - Total RPCs completed
- `grpc_server_handling_seconds` - RPC latency histogram
- `grpc_server_msg_received_total` - Messages received
- `grpc_server_msg_sent_total` - Messages sent

### Python Service (custom)

- `grpc_server_requests_total` - Total requests by method
- `grpc_server_latency_seconds` - Request latency histogram
- `grpc_client_requests_total` - Outgoing client requests

## ServiceMonitors

Both services have ServiceMonitors configured for Prometheus scraping:

```yaml
# Verify ServiceMonitors are picked up
kubectl get servicemonitors -n scratch

# Check Prometheus targets
# Navigate to http://prometheus.talos00/targets
# Look for scratch/grpc-go and scratch/grpc-python
```

## Proto Definition

```protobuf
service EchoService {
  rpc Echo(EchoRequest) returns (EchoResponse);
  rpc EchoStream(stream EchoRequest) returns (stream EchoResponse);
}

message EchoRequest {
  string message = 1;
  string sender = 2;
}

message EchoResponse {
  string message = 1;
  string responder = 2;
  int64 timestamp = 3;
}
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVICE_NAME` | go-service / python-service | Service identifier in responses |
| `GRPC_PORT` | 50051 / 50052 | gRPC server port |
| `METRICS_PORT` | 9090 / 9091 | Prometheus metrics port |
| `PEER_ADDRESS` | (empty) | Address of peer service for demo calls |
