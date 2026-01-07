# carrierarr

Fleet management system for EC2/Fargate workers. Provides gRPC-based agent communication, real-time status streaming, and self-registration via RabbitMQ.

## Features

- **WebSocket Control Channel** - Send commands and receive real-time output
- **stdout/stderr Streaming** - Live output from worker scripts
- **EC2 Monitoring** - Track EC2 instance status with configurable tag filters
- **Fargate Monitoring** - Monitor ECS Fargate tasks
- **Multi-client Support** - Multiple frontends can connect simultaneously
- **Script Agnostic** - Works with any shell control script

## Quick Start

### With Mock Worker (Testing)

```bash
cd tools/carrierarr
go run ./cmd/main.go -script=./scripts/mock-worker.sh -addr=:8090
```

Open `examples/test-client.html` in a browser to test.

### With LLM Worker (Production)

```bash
cd tools/carrierarr
go run ./cmd/main.go \
  -script=../../scripts/hybrid-llm/llm-worker.sh \
  -ec2-tags='{"Name":"llm-worker"}' \
  -addr=:8090
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Frontend (Web UI)                       │
└─────────────────────────────────────────────────────────────┘
                              │ WebSocket
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   carrierarr (Go binary)                     │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────┐ │
│  │  WebSocket Hub  │  │ Process Manager │  │ EC2 Monitor │ │
│  └─────────────────┘  └─────────────────┘  └─────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              │ Executes
                              ▼
┌─────────────────────────────────────────────────────────────┐
│              worker.sh (standard control script)             │
└─────────────────────────────────────────────────────────────┘
```

## WebSocket Protocol

### Inbound Messages (Client → Server)

```json
{
  "type": "command",
  "command": "start",
  "target": "worker-1",
  "args": ["--spot"]
}
```

| Type | Description |
|------|-------------|
| `command` | Execute a command on the worker script |
| `subscribe` | Subscribe to updates for a target |
| `ping` | Keep-alive ping |

### Outbound Messages (Server → Client)

```json
{
  "type": "stdout",
  "target": "worker-1",
  "data": "Starting worker...",
  "timestamp": "2024-01-02T15:00:00Z"
}
```

| Type | Description |
|------|-------------|
| `stdout` | Standard output line |
| `stderr` | Standard error line |
| `result` | Command finished (includes `exit_code`) |
| `error` | Error message |
| `status` | Worker status update |
| `pong` | Keep-alive pong |

## HTTP Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /ws` | WebSocket connection |
| `GET /health` | Health check |
| `GET /api/status` | Current worker status |

## Configuration

| Flag | Description | Default |
|------|-------------|---------|
| `-addr` | HTTP server address | `:8090` |
| `-script` | Path to worker control script | (required) |
| `-ec2-tags` | EC2 instance tags to monitor (JSON) | |
| `-ecs-cluster` | ECS cluster to monitor | |
| `-poll` | Status poll interval | `30s` |

## Worker Script Interface

The agent expects the worker script to support these commands:

| Command | Description |
|---------|-------------|
| `start` | Start the worker |
| `stop` | Stop the worker |
| `status` | Get worker status |
| `logs` | View worker logs |
| `provision` | Provision new worker |
| `terminate` | Terminate worker |

See `scripts/mock-worker.sh` for a reference implementation.

## Development

### Run Tests

```bash
# Unit tests
go test ./...

# Integration tests
go test -tags=integration ./...
```

### Build

```bash
go build -o carrierarr ./cmd/main.go
```

## Examples

### EC2 Worker

```bash
./examples/ec2/config.sh
```

### Fargate Tasks

```bash
./examples/fargate/config.sh
```

## Integration with llm-proxy

This agent is designed to work with the llm-proxy's worker management UI. The proxy can connect to carrierarr's WebSocket to:

1. Display real-time worker status
2. Show command output in the UI
3. Control workers (start/stop/status)
4. Monitor EC2 instance metrics

## Sources

- [Go Playground Socket](https://pkg.go.dev/golang.org/x/tools/playground/socket) - Message protocol inspiration
- [Kubernetes wsstream](https://pkg.go.dev/k8s.io/Kubernetes/pkg/util/wsstream) - Channel multiplexing
- [Gorilla WebSocket](https://github.com/gorilla/websocket) - WebSocket implementation
