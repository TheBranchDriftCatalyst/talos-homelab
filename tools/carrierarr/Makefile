.PHONY: all proto build build-control-plane build-worker-agent clean test lint help

# Go parameters
GOCMD=go
GOBUILD=$(GOCMD) build
GOTEST=$(GOCMD) test
GOMOD=$(GOCMD) mod
BINARY_DIR=bin

# Build info
VERSION ?= $(shell git describe --tags --always --dirty 2>/dev/null || echo "dev")
BUILD_TIME=$(shell date -u '+%Y-%m-%dT%H:%M:%SZ')
LDFLAGS=-ldflags "-X main.Version=$(VERSION) -X main.BuildTime=$(BUILD_TIME)"

all: proto build

# =============================================================================
# Protobuf Generation
# =============================================================================

proto: ## Generate protobuf/gRPC code
	@echo "==> Generating protobuf code..."
	buf generate
	@echo "==> Done. Generated files in pkg/proto/"

proto-lint: ## Lint protobuf files
	buf lint

proto-breaking: ## Check for breaking changes
	buf breaking --against '.git#branch=main'

# =============================================================================
# Build
# =============================================================================

build: build-control-plane build-worker-agent ## Build all binaries

build-control-plane: ## Build control plane server
	@echo "==> Building control-plane..."
	@mkdir -p $(BINARY_DIR)
	CGO_ENABLED=0 $(GOBUILD) $(LDFLAGS) -o $(BINARY_DIR)/control-plane ./cmd/control-plane
	@echo "==> Built: $(BINARY_DIR)/control-plane"

build-worker-agent: ## Build worker agent
	@echo "==> Building worker-agent..."
	@mkdir -p $(BINARY_DIR)
	CGO_ENABLED=0 $(GOBUILD) $(LDFLAGS) -o $(BINARY_DIR)/worker-agent ./cmd/worker-agent
	@echo "==> Built: $(BINARY_DIR)/worker-agent"

build-linux: ## Build for Linux (amd64) - for AMIs
	@echo "==> Building for Linux amd64..."
	@mkdir -p $(BINARY_DIR)/linux-amd64
	GOOS=linux GOARCH=amd64 CGO_ENABLED=0 $(GOBUILD) $(LDFLAGS) -o $(BINARY_DIR)/linux-amd64/control-plane ./cmd/control-plane
	GOOS=linux GOARCH=amd64 CGO_ENABLED=0 $(GOBUILD) $(LDFLAGS) -o $(BINARY_DIR)/linux-amd64/worker-agent ./cmd/worker-agent
	@echo "==> Built Linux binaries in $(BINARY_DIR)/linux-amd64/"

# =============================================================================
# Development
# =============================================================================

run-control-plane: ## Run control plane locally
	$(GOCMD) run ./cmd/control-plane -addr=:8090 -grpc-addr=:8091

run-worker-agent: ## Run worker agent locally (mock mode)
	$(GOCMD) run ./cmd/worker-agent -control-plane=localhost:8091 -mock

test: ## Run tests
	$(GOTEST) -v ./...

test-cover: ## Run tests with coverage
	$(GOTEST) -v -coverprofile=coverage.out ./...
	$(GOCMD) tool cover -html=coverage.out -o coverage.html
	@echo "==> Coverage report: coverage.html"

lint: ## Run linters
	golangci-lint run ./...

tidy: ## Tidy go modules
	$(GOMOD) tidy

# =============================================================================
# AMI Building (Packer)
# =============================================================================

ami-base: build-linux ## Build base AMI
	@echo "==> Building base AMI..."
	cd ami && packer build -only=base.* .

ami-lighthouse: build-linux ## Build lighthouse AMI
	@echo "==> Building lighthouse AMI..."
	cd ami && packer build -only=lighthouse.* .

ami-gpu-worker: build-linux ## Build GPU worker AMI
	@echo "==> Building GPU worker AMI..."
	cd ami && packer build -only=gpu-worker.* .

ami-all: build-linux ## Build all AMIs
	@echo "==> Building all AMIs..."
	cd ami && packer build .

# =============================================================================
# Docker
# =============================================================================

docker-build: ## Build Docker image
	docker build -t ghcr.io/thebranchdriftcatalyst/carrierarr:$(VERSION) .

docker-push: ## Push Docker image
	docker push ghcr.io/thebranchdriftcatalyst/carrierarr:$(VERSION)

# =============================================================================
# Cleanup
# =============================================================================

clean: ## Clean build artifacts
	rm -rf $(BINARY_DIR)
	rm -f coverage.out coverage.html

# =============================================================================
# Help
# =============================================================================

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'
