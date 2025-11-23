# Contributing Guide

## Development Setup

### Prerequisites

- **macOS/Linux**: Most tools work on both
- **Homebrew**: Install from [brew.sh](https://brew.sh)
- **Yarn**: Will be installed via Homebrew

### Quick Start

```bash
# One-command setup
task dev-setup
```

This installs:

- ✅ Homebrew packages (lefthook, gitleaks, yamllint, shellcheck, etc.)
- ✅ Yarn packages (markdownlint, prettier)
- ✅ Git hooks (automatic linting on commit)

### Manual Setup

```bash
# Install Homebrew dependencies
task install-brew-deps

# Install Yarn dependencies
task install-yarn-deps

# Install git hooks
task hooks-install
```

## Workflow

### Making Changes

```bash
# 1. Create a branch
git checkout -b feat/my-feature

# 2. Make changes
vim infrastructure/base/monitoring/kustomization.yaml

# 3. Test locally (if needed)
task validate

# 4. Commit (hooks run automatically)
git add .
git commit -m "feat(monitoring): add new dashboard"

# 5. Push
git push origin feat/my-feature
```

### Commit Messages

We use **Conventional Commits**:

```
<type>[optional scope]: <description>

Types:
- feat: New feature
- fix: Bug fix
- docs: Documentation
- style: Code style (formatting, etc.)
- refactor: Code refactoring
- perf: Performance improvement
- test: Tests
- build: Build system
- ci: CI/CD
- chore: Maintenance
```

**Examples:**

```
feat: add external secrets operator
fix(monitoring): resolve Prometheus scrape timeout
docs: update README with ESO setup
chore(deps): update Flux to v2.2.0
```

### Git Hooks

Hooks run automatically on:

- **Pre-commit:** Linting, formatting, validation
- **Commit-msg:** Commit message format check
- **Pre-push:** Full secret scan, TODO warnings

**Skip hooks (emergency only):**

```bash
LEFTHOOK=0 git commit -m "emergency fix"
```

## Tools

### Linting

```bash
# Run all linters
task lint

# Individual linters
task lint-yaml      # YAML syntax/style
task lint-shell     # Shell scripts
yarn lint           # Markdown + Prettier
task lint-secrets   # Secret scanning
```

### Formatting

```bash
# Format all code
task format

# Individual formatters
task format-shell   # Shell scripts
yarn format         # Markdown + Prettier
```

### Validation

```bash
# Validate Kubernetes manifests
task validate

# Validate kustomizations
task validate-kustomize

# Validate K8s resources
task validate-k8s
```

## Code Style

### YAML

- 2-space indentation
- 120 character line length
- Document start markers (`---`)
- No trailing whitespace

### Shell Scripts

- 2-space indentation
- Use `[[` instead of `[`
- Quote all variables
- Use `set -euo pipefail`

### Markdown

- ATX heading style (`#`)
- Dash list style (`-`)
- 120 character line length
- Code blocks with language tags

## Testing

### Before Committing

```bash
# Lint everything
task lint

# Format code
task format

# Validate manifests
task validate
```

### Before Pushing

```bash
# Full validation
task lint && task validate

# Test kustomization builds
find infrastructure -name "kustomization.yaml" | \
  while read f; do kustomize build $(dirname $f); done
```

## Troubleshooting

### Hooks Not Running

```bash
# Reinstall hooks
task hooks-install

# Check lefthook installed
lefthook version
```

### Tool Not Found

```bash
# Reinstall dependencies
task install-brew-deps
task install-yarn-deps
```

### Linting Fails

```bash
# See specific errors
task lint-yaml    # Shows YAML errors
task lint-shell   # Shows shell errors
yarn lint         # Shows Markdown/Prettier errors
```

## Getting Help

- **Documentation:** See `docs/` directory
- **Development Tools:** See `docs/03-operations/development-tools.md`
- **Issues:** Open GitHub issue

## Pull Requests

1. Fork the repository
2. Create a feature branch
3. Make changes with tests/docs
4. Run `task lint && task validate`
5. Commit with conventional commits
6. Push and create PR
7. Address review feedback

## Resources

- [Task Documentation](https://taskfile.dev/)
- [Conventional Commits](https://www.conventionalcommits.org/)
- [Lefthook](https://github.com/evilmartians/lefthook)
- [Kubernetes Best Practices](https://kubernetes.io/docs/concepts/configuration/overview/)
