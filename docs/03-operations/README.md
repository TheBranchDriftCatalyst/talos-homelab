# Operations

## Overview

This section covers operational procedures, cluster management, and development workflows for the Talos Kubernetes homelab. These guides help you maintain, troubleshoot, and develop infrastructure safely and efficiently.

## Quick Navigation

| Topic                                                    | Description                                                                | When to Read                                                    |
| -------------------------------------------------------- | -------------------------------------------------------------------------- | --------------------------------------------------------------- |
| [provisioning.md](provisioning.md)                       | Complete step-by-step cluster provisioning guide from bare metal to GitOps | Setting up a fresh cluster or understanding provisioning levels |
| [node-shutdown-procedure.md](node-shutdown-procedure.md) | Safe procedures for node shutdown, restart, and maintenance                | Before any hardware maintenance or planned downtime             |
| [local-development-eso.md](local-development-eso.md)     | Local development workflow for External Secrets Operator                   | Testing secrets management changes locally                      |
| [development-tools.md](development-tools.md)             | Git hooks, linters, formatters, and code quality automation                | Initial development environment setup or CI/CD integration      |

## Key Concepts

- **Provisioning Levels**: Cluster setup follows a structured approach from Level 0 (base Talos) through Level 4 (GitOps)
- **Graceful Shutdown**: Talos nodes require proper shutdown procedures to avoid etcd corruption and ensure clean restarts
- **Development Tools**: Automated code quality via lefthook, gitleaks, yamllint, shellcheck, and markdownlint
- **Local Testing**: External Secrets Operator and other infrastructure components can be tested locally before production deployment
- **Conventional Commits**: All commits follow conventional commit format for automated changelog generation

## Common Tasks

### Cluster Provisioning

- [Fresh cluster setup](provisioning.md#level-0-base-infrastructure) - Bootstrap Talos and Kubernetes
- [Deploy core services](provisioning.md#level-1-core-services) - Namespaces, storage, Traefik
- [Deploy applications](provisioning.md#level-2-applications) - Arr stack deployment
- [Setup monitoring](provisioning.md#level-3-monitoring-stack) - Prometheus, Grafana, observability
- [Bootstrap GitOps](provisioning.md#level-4-gitops) - FluxCD and ArgoCD setup

### Node Management

- [Safe node shutdown](node-shutdown-procedure.md) - Graceful shutdown procedure
- [Node restart](node-shutdown-procedure.md) - Clean restart after maintenance
- [Emergency recovery](node-shutdown-procedure.md) - Troubleshooting boot and etcd issues

### Development Workflow

- [Setup development tools](development-tools.md#quick-start) - One-command dev environment setup
- [Git hooks overview](development-tools.md#git-hooks) - Pre-commit, commit-msg, pre-push hooks
- [Linting and formatting](development-tools.md#linters) - YAML, shell, markdown, secret scanning
- [Kubernetes validation](development-tools.md#kubernetes-validation) - Kustomize and kubectl dry-run

### Local Testing

- [Test ESO changes](local-development-eso.md) - External Secrets Operator local workflow
- [Validate infrastructure](../01-getting-started/local-testing.md) - Docker-based Talos cluster testing

### Troubleshooting

- [Provisioning issues](provisioning.md#notes-and-lessons-learned) - Hostname changes, storage, multi-environment setup
- [Shutdown/startup problems](node-shutdown-procedure.md) - Node not responding, etcd corruption
- [Linter failures](development-tools.md#troubleshooting) - YAML, secrets, kustomize build errors

---

## Related Issues

<!-- Beads tracking for this section -->

- [CILIUM-kkw] - Initial creation of section README
