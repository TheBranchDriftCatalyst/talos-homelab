# Contributing Guide

## Development Setup

### Prerequisites

- **Nix** with flakes enabled — [nixos.org/download](https://nixos.org/download) or
  [Determinate Nix](https://determinate.systems/nix)
- **direnv** — [direnv.net](https://direnv.net). Optional but strongly recommended; without it
  use `nix develop` instead.
- **macOS/Linux**: the flake builds on both (the Tilt/trust-CA tasks still assume macOS)
- **1Password CLI** with the desktop app's "Integrate with 1Password CLI" toggle on, if you want
  this repo's secrets. Without it the shell still loads, secrets just don't.

There is no Homebrew step and no Node/Yarn step. `flake.nix` declares the entire toolchain and
`flake.lock` pins it.

### Quick Start

```bash
direnv allow   # once, after cloning
```

That builds the dev shell (cached by nix-direnv, instant afterwards), puts the whole toolchain on
PATH, renders this repo's secrets from 1Password, and installs the git hooks. `cd` out and it all
unloads — nothing global changes.

No direnv? `nix develop` gives you the same shell.

Verify what you got:

```bash
task deps:install   # checks every expected tool is on PATH (alias: task setup)
```

### Adding or changing a tool

Edit the `packages` list in `flake.nix`, then `direnv reload`. Do not `brew install` it — a tool
that is not in the flake is not reproducible for anyone else.

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
task dev:lint:markdown  # markdownlint-cli2
task dev:lint:format    # prettier --check
task dev:lint:secrets   # Secret scanning (gitleaks detect)
```

> `.markdownlint-cli2.yaml` deliberately omits globs (lefthook passes staged files), so the `task dev:lint:markdown` step lints
> **0 files** when run standalone. To lint Markdown by hand: `npx markdownlint-cli2 '**/*.md'`.

### Formatting

```bash
# Format all code
task format

# Individual formatters
task dev:format-shell   # Shell scripts (shfmt, scripts/ only)
task dev:format:prettier # prettier --write . (markdownlint --fix matches 0 files standalone, see note above)
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

Enforced by `dev/yamllint.yaml` (`yamllint -c dev/yamllint.yaml --strict`):

- 2-space indentation, sequences indented
- 120 character line length (warning level, not an error)
- No trailing whitespace
- Newline at end of file, unix line endings
- No duplicate keys
- Document start markers (`---`) are **not** required (`document-start` is disabled)

### Shell Scripts

Formatted by `shfmt -w -i 2 -ci -sr`, linted by `shellcheck --rcfile=dev/shellcheckrc -x` (see `dev/shellcheckrc`):

- 2-space indentation, indented `case` branches, simplified redirects
- Use `[[` instead of `[`
- Quote all variables
- Use `set -euo pipefail`

`dev/shellcheckrc` disables SC1091, SC2034, SC2155, SC2016, SC2059, SC2162 and SC2005 as project-wide false positives.

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
# Rebuild the dev shell (you are probably outside it)
direnv reload      # or: nix develop
task deps:install  # lists exactly which tools are missing
```

### Linting Fails

```bash
# See specific errors
task dev:lint:yaml    # Shows YAML errors
task dev:lint:shell   # Shows shell errors
task dev:lint:markdown # Shows Markdown errors
task dev:lint:format   # Shows Prettier errors
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
