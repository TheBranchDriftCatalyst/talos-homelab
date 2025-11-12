.PHONY: help build test run docker-build docker-push deploy clean logs tidy

# Variables
APP_NAME := catalyst-dns-sync
VERSION ?= $(shell git describe --tags --always --dirty 2>/dev/null || echo "dev")
GIT_COMMIT := $(shell git rev-parse HEAD 2>/dev/null || echo "unknown")
BUILD_DATE := $(shell date -u +"%Y-%m-%dT%H:%M:%SZ")
DOCKER_REGISTRY ?= localhost:5000
IMAGE := $(DOCKER_REGISTRY)/$(APP_NAME):$(VERSION)
IMAGE_LATEST := $(DOCKER_REGISTRY)/$(APP_NAME):latest

# Go variables
GOBASE := $(shell pwd)
GOBIN := $(GOBASE)/bin
LDFLAGS := -ldflags="-w -s \
	-X main.version=$(VERSION) \
	-X main.gitCommit=$(GIT_COMMIT) \
	-X main.buildDate=$(BUILD_DATE)"

# Kubernetes
KUBECONFIG ?= ./.output/kubeconfig
NAMESPACE ?= dns

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

build: ## Build the Go binary locally
	@echo "Building $(APP_NAME) $(VERSION)..."
	@mkdir -p $(GOBIN)
	@go build $(LDFLAGS) -o $(GOBIN)/$(APP_NAME) ./cmd/$(APP_NAME)
	@echo "Built: $(GOBIN)/$(APP_NAME)"

test: ## Run unit tests
	@echo "Running tests..."
	@go test -v -race -cover ./...

run: build ## Run locally (requires kubeconfig)
	@echo "Running $(APP_NAME) locally..."
	@KUBECONFIG=$(KUBECONFIG) \
	 LOG_LEVEL=debug \
	 MODE=watch \
	 TECHNITIUM_URL=http://localhost:5380 \
	 TECHNITIUM_PASSWORD=admin \
	 $(GOBIN)/$(APP_NAME)

docker-build: ## Build Docker image
	@echo "Building Docker image: $(IMAGE)"
	@docker build \
		--build-arg VERSION=$(VERSION) \
		--build-arg GIT_COMMIT=$(GIT_COMMIT) \
		--build-arg BUILD_DATE=$(BUILD_DATE) \
		-t $(IMAGE) \
		-t $(IMAGE_LATEST) \
		.
	@echo "Built: $(IMAGE)"

docker-push: docker-build ## Push Docker image to registry
	@echo "Pushing $(IMAGE)..."
	@docker push $(IMAGE)
	@docker push $(IMAGE_LATEST)
	@echo "Pushed: $(IMAGE)"

deploy: docker-push ## Deploy to Kubernetes
	@echo "Deploying $(APP_NAME) to Kubernetes..."
	@kubectl --kubeconfig=$(KUBECONFIG) apply -k applications/$(APP_NAME)/base/
	@echo "Deployed! Waiting for rollout..."
	@kubectl --kubeconfig=$(KUBECONFIG) -n $(NAMESPACE) rollout status deployment/$(APP_NAME) --timeout=120s

restart: ## Restart the deployment in Kubernetes
	@echo "Restarting $(APP_NAME)..."
	@kubectl --kubeconfig=$(KUBECONFIG) -n $(NAMESPACE) rollout restart deployment/$(APP_NAME)
	@kubectl --kubeconfig=$(KUBECONFIG) -n $(NAMESPACE) rollout status deployment/$(APP_NAME)

logs: ## Tail logs from Kubernetes deployment
	@kubectl --kubeconfig=$(KUBECONFIG) -n $(NAMESPACE) logs -f deployment/$(APP_NAME) --all-containers=true

describe: ## Describe the Kubernetes deployment
	@kubectl --kubeconfig=$(KUBECONFIG) -n $(NAMESPACE) describe deployment/$(APP_NAME)

metrics: ## Port-forward to metrics endpoint
	@echo "Port-forwarding to metrics endpoint..."
	@echo "Metrics available at: http://localhost:9090/metrics"
	@kubectl --kubeconfig=$(KUBECONFIG) -n $(NAMESPACE) port-forward deployment/$(APP_NAME) 9090:9090

clean: ## Clean build artifacts
	@echo "Cleaning..."
	@rm -rf $(GOBIN)
	@go clean
	@echo "Clean complete"

tidy: ## Tidy and verify Go modules
	@echo "Tidying Go modules..."
	@go mod tidy
	@go mod verify

version: ## Show version information
	@echo "Version:    $(VERSION)"
	@echo "Git Commit: $(GIT_COMMIT)"
	@echo "Build Date: $(BUILD_DATE)"
	@echo "Image:      $(IMAGE)"

.DEFAULT_GOAL := help
