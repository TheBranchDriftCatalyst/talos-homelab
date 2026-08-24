# Contributing Guide

## Development Setup

### Prerequisites

- **macOS/Linux**: Most tools work on both (the Brewfile and the Tilt/trust-CA tasks assume macOS)
- **Homebrew**: Install from [brew.sh](https://brew.sh)
- **Node** >= 18 and **Yarn** >= 1.22 (per `package.json` engines) — Yarn is not in the Brewfile; `task deps:install` runs
  `brew install yarn` for you if it is missing

### Quick Start

```bash
# One-command setup (alias: task setup)
task deps:install
```

This installs:

- ✅ Homebrew packages from `Brewfile` (lefthook, gitleaks, yamllint, shellcheck, shfmt, kubectl, kustomize, helm, flux, talosctl, etc.)
- ✅ Yarn packages from `package.json` (markdownlint-cli2, prettier, jest)
- ✅ Tilt (local development)
- ✅ Git hooks (automatic linting on commit)

### Manual Setup

```bash
# Install Homebrew dependencies
task dev:deps:brew

# Install Yarn dependencies
task dev:deps:yarn

# Install git hooks
task dev:hooks:install
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
- revert: Revert a previous commit
```

Enforced by the `commit-msg` hook in `lefthook.yaml` (merge commits are exempt).

**Examples:**

```
feat: add external secrets operator
fix(monitoring): resolve Prometheus scrape timeout
docs: update README with ESO setup
chore(deps): update Flux to v2.2.0
```

### Git Hooks

Hooks run automatically on:

- **Pre-commit:** Secret scan (staged), YAML lint, kubectl/kustomize validation, shellcheck, shfmt, markdownlint, trailing-whitespace, helm lint
- **Commit-msg:** Commit message format check
- **Pre-push:** Full secret scan, TODO warnings, all kustomizations build
- **Post-checkout / post-merge:** Informational reminders only (infrastructure changed, dependencies changed) — never fail

**Skip hooks (emergency only):**

```bash
# Skip all hooks
LEFTHOOK=0 git commit -m "emergency fix"

# Skip a single hook stage or command
LEFTHOOK_EXCLUDE=pre-commit git commit -m "docs: update"
```

## Tools

### Linting

```bash
# Run all linters
task lint

# Individual linters
task dev:lint:yaml      # YAML syntax/style (yamllint --strict)
task dev:lint:shell     # Shell scripts (shellcheck -x, scripts/ only)
yarn lint               # Markdown + Prettier
task dev:lint:secrets   # Secret scanning (gitleaks detect)
```

> `.markdownlint-cli2.yaml` deliberately omits globs (lefthook passes staged files), so the `yarn lint:markdown` step lints
> **0 files** when run standalone. To lint Markdown by hand: `npx markdownlint-cli2 '**/*.md'`.

### Formatting

```bash
# Format all code
task format

# Individual formatters
task dev:format-shell   # Shell scripts (shfmt, scripts/ only)
yarn format             # Prettier --write . (markdownlint --fix matches 0 files standalone, see note above)
```

### Validation

```bash
# Validate Kubernetes manifests
task validate

# Validate kustomizations
task dev:validate:kustomize

# Validate K8s resources
task dev:validate:k8s
```

## Code Style

### YAML

Enforced by `.yamllint.yaml` (`yamllint --strict`):

- 2-space indentation, sequences indented
- 120 character line length (warning level, not an error)
- No trailing whitespace
- Newline at end of file, unix line endings
- No duplicate keys
- Document start markers (`---`) are **not** required (`document-start` is disabled)

### Shell Scripts

Formatted by `shfmt -w -i 2 -ci -sr`, linted by `shellcheck -x` (see `.shellcheckrc`):

- 2-space indentation, indented `case` branches, simplified redirects
- Use `[[` instead of `[`
- Quote all variables
- Use `set -euo pipefail`

`.shellcheckrc` disables SC1091, SC2034, SC2155, SC2016, SC2059, SC2162 and SC2005 as project-wide false positives.

### Markdown

Enforced by `.markdownlint-cli2.yaml` (`markdownlint-cli2`):

- ATX heading style (`#`)
- Dash list style (`-`), 2-space list indent
- Fenced code blocks with backticks; asterisk emphasis/strong
- Proper-name capitalization (Kubernetes, kubectl, ArgoCD, FluxCD, Talos, Prometheus, Grafana, Docker, YAML, JSON)
- Line length is **not** enforced (MD013 disabled); code-block language tags are optional (MD040 disabled)

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

# Test kustomization builds (same set the pre-push hook checks)
find infrastructure applications -name "kustomization.yaml" | \
  while read f; do kustomize build $(dirname $f); done
```

## Troubleshooting

### Hooks Not Running

```bash
# Reinstall hooks
task dev:hooks:install

# Check lefthook installed
lefthook version
```

### Tool Not Found

```bash
# Reinstall dependencies
task dev:deps:brew
task dev:deps:yarn
```

### Linting Fails

```bash
# See specific errors
task dev:lint:yaml    # Shows YAML errors
task dev:lint:shell   # Shows shell errors
yarn lint             # Shows Markdown/Prettier errors
```

## Getting Help

- **Documentation:** See `docs/` directory
- **Development Tools:** See `docs/03-operations/development-tools.md` (note: its task names predate the modular Taskfile split — use the `dev:` prefixed names above)
- **Issues:** This repo tracks work in **beads** (`bd ready`, `bd create --title="..." --type=task`, prefix `TALOS-`). GitHub issues on
  [TheBranchDriftCatalyst/talos-homelab](https://github.com/TheBranchDriftCatalyst/talos-homelab) for outside reports.

## Pull Requests

1. Fork the repository (external contributors; maintainers branch directly)
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
