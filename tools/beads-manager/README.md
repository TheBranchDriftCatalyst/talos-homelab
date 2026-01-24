# Beads Manager

Visual issue management UI for [Beads](https://github.com/TheBranchDriftCatalyst/beads) - a local-first issue tracker with dependency graphs.

![Beads Manager](https://img.shields.io/badge/beads-manager-cyan?style=for-the-badge)
![Docker](https://img.shields.io/badge/Docker-ready-blue?style=for-the-badge&logo=docker)
![Multi-arch](https://img.shields.io/badge/Multi--arch-amd64%20%7C%20arm64-green?style=for-the-badge)

## Features

- **Dependency Graph Visualization** - See how your issues relate to each other
- **Real-time Updates** - Changes sync instantly via WebSocket
- **Filtering & Search** - Filter by status, type, priority, labels, or epic
- **Issue Management** - Create, update, close, and reopen issues
- **Epic View** - Group and filter issues by epic

## Quick Start

### Using Docker (Recommended)

Run from any directory with a `.beads` folder:

```bash
# One-liner
docker run --rm -it -p 3333:3333 -v "$(pwd):/workspace:ro" \
  ghcr.io/thebranchdriftcatalyst/beads-manager:latest

# Then open http://localhost:3333
```

### Using the Helper Script

Install the `beads-ui` script for easier usage:

```bash
# Install
curl -fsSL https://raw.githubusercontent.com/TheBranchDriftCatalyst/talos-homelab/main/tools/beads-manager/scripts/beads-ui \
  -o ~/.local/bin/beads-ui
chmod +x ~/.local/bin/beads-ui

# Run from any beads project
cd /path/to/your/project
beads-ui
```

The script will:
1. Find the nearest `.beads` directory
2. Start the Docker container
3. Open your browser

### Using docker-compose

Create a `docker-compose.yml` in your project:

```yaml
services:
  beads-ui:
    image: ghcr.io/thebranchdriftcatalyst/beads-manager:latest
    ports:
      - "3333:3333"
    volumes:
      - .:/workspace:ro
```

Then run:

```bash
docker compose up
```

## Options

### Helper Script Options

```bash
beads-ui                     # Run in current directory
beads-ui /path/to/project    # Run for specific project
beads-ui -p 8080             # Run on custom port
beads-ui -d                  # Run in background (detached)
beads-ui --pull              # Force pull latest image
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BEADS_PORT` | `3333` | Port to run the UI on |
| `BEADS_WORKSPACE` | `.` | Path to the workspace root |

## Development

### Prerequisites

- Node.js 20+
- Yarn
- Docker (for building images)

### Local Development

```bash
# Install dependencies
yarn install

# Start development server (client + server)
yarn dev

# Client only (Vite dev server)
yarn dev:client

# Server only
yarn dev:server
```

### Building

```bash
# Build everything
yarn build

# Build Docker image locally
yarn docker:build

# Or use docker directly
docker build -t beads-manager .
```

### Testing Locally with Docker

```bash
# Build and run
docker build -t beads-manager .
docker run --rm -it -p 3333:3333 -v "$(pwd)/../..:/workspace:ro" beads-manager
```

## Architecture

```
beads-manager/
├── src/
│   ├── client/           # React frontend (Vite)
│   │   ├── components/   # UI components
│   │   ├── hooks/        # React hooks
│   │   └── lib/          # Types and utilities
│   ├── server/           # Express backend
│   │   └── index.ts      # API server + WebSocket
│   └── cli.ts            # CLI entry point
├── Dockerfile            # Multi-stage build
├── docker-compose.yml    # Easy local usage
└── scripts/
    └── beads-ui          # Helper script
```

### How It Works

1. **Server** reads `.beads/issues.jsonl` directly and runs `bd` commands
2. **WebSocket** watches the JSONL file for changes and broadcasts updates
3. **Client** connects to the server for REST API + WebSocket real-time updates
4. **Docker** mounts your project directory as read-only at `/workspace`

## Multi-Architecture Support

The Docker image supports:
- `linux/amd64` - Intel/AMD 64-bit (most servers, Intel Macs via Rosetta)
- `linux/arm64` - ARM 64-bit (Apple Silicon M1/M2/M3, AWS Graviton, Raspberry Pi 4)

## License

MIT
