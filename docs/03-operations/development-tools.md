# Development Tools and Git Hooks

**Automated code quality, security scanning, and formatting**

## Overview

This repository uses **lefthook** to manage git hooks with automated:

- ✅ **Secret scanning** (gitleaks)
- ✅ **YAML linting** (yamllint)
- ✅ **Kubernetes validation** (kubectl, kustomize)
- ✅ **Shell script linting** (shellcheck)
- ✅ **Markdown linting** (markdownlint)
- ✅ **Commit message validation** (conventional commits)
- ✅ **Code formatting** (shfmt)

## Quick Start

### One-Command Setup

```bash
# Install all tools and configure git hooks
task dev-setup
```

This installs:

- lefthook (git hooks manager)
- gitleaks (secret scanner)
- yamllint, shellcheck, markdownlint (linters)
- shfmt, prettier (formatters)
- Git hooks configuration

### Manual Setup

```bash
# Install individual components
task install-lefthook
task install-linters
task install-formatters
task hooks-install
```

## Git Hooks

### Pre-Commit Hooks

Run automatically before each commit:

| Hook                    | Tool         | Purpose                       |
| ----------------------- | ------------ | ----------------------------- |
| **gitleaks**            | gitleaks     | Scan staged files for secrets |
| **yamllint**            | yamllint     | Lint YAML syntax and style    |
| **kube-validate**       | kubectl      | Validate K8s manifests        |
| **kustomize-validate**  | kustomize    | Validate kustomizations build |
| **shellcheck**          | shellcheck   | Lint shell scripts            |
| **shfmt**               | shfmt        | Format shell scripts          |
| **markdownlint**        | markdownlint | Lint Markdown files           |
| **trailing-whitespace** | grep         | Check for trailing spaces     |

### Commit-Msg Hook

Validates commit messages follow **Conventional Commits** format:

```
<type>[optional scope]: <description>

Types: feat, fix, docs, style, refactor, perf, test, build, ci, chore, revert
```

**Examples:**

```bash
git commit -m "feat: add external secrets operator"
git commit -m "fix(monitoring): resolve Prometheus scrape timeout"
git commit -m "docs: update README with ESO setup"
git commit -m "chore(deps): update Flux to v2.2.0"
```

### Pre-Push Hooks

Run before pushing to remote:

| Hook                            | Purpose                         |
| ------------------------------- | ------------------------------- |
| **gitleaks-full**               | Full repository secret scan     |
| **check-todos**                 | Warn about TODO/FIXME in code   |
| **validate-all-kustomizations** | Ensure all kustomizations build |

### Skipping Hooks

```bash
# Skip all hooks
LEFTHOOK=0 git commit -m "emergency fix"

# Skip pre-commit only
LEFTHOOK_EXCLUDE=pre-commit git commit -m "docs: update"

# Skip specific hook
git commit -m "feat: add feature" --no-verify
```

## Linters

### YAMLLint

**Config:** `.yamllint.yaml`

Validates YAML syntax and style:

- 2-space indentation
- 120 character line length
- Document start markers (`---`)
- No trailing whitespace
- Consistent key ordering

```bash
# Lint all YAML files
task lint-yaml

# Or directly
yamllint --strict .
```

**Common fixes:**

```bash
# Fix indentation
# Manual - yamllint will guide you

# Remove trailing whitespace
sed -i '' 's/[[:space:]]*$//' file.yaml
```

### Gitleaks

**Config:** `.gitleaks.toml`

Scans for secrets and sensitive data:

- API keys, tokens
- Passwords
- Private keys
- Talos tokens
- Kubernetes tokens
- 1Password tokens

```bash
# Scan repository
task lint-secrets

# Scan and generate report
gitleaks detect --verbose --redact --report-path .output/gitleaks-report.json
```

**Custom rules:**

- Talos API tokens
- Kubernetes service account tokens
- 1Password Connect tokens
- ArgoCD passwords
- Docker registry credentials

**Allowlist:**

```toml
# .gitleaks.toml
[allowlist]
paths = [
    '''.output/.*''',          # Generated files
    '''docs/.*/.*\.example''', # Documentation examples
]
regexes = [
    '''example.*[a-zA-Z0-9+/=]{20,}''',  # Example values
    '''sha256:[a-f0-9]{64}''',            # Docker digests
]
```

### Shellcheck

Lints shell scripts for:

- Syntax errors
- Common mistakes
- Best practices
- Portability issues

```bash
# Lint all shell scripts
task lint-shell

# Or directly
shellcheck -x scripts/*.sh
```

**Common issues:**

```bash
# SC2086: Quote to prevent word splitting
docker build -t $IMAGE .        # ❌
docker build -t "$IMAGE" .      # ✅

# SC2155: Separate declaration and assignment
local var=$(cmd)                # ❌
local var; var=$(cmd)           # ✅
```

### Markdownlint

**Config:** `.markdownlint.yaml`

Validates Markdown style:

- Heading structure
- List formatting
- Code block language tags
- Line length (120 chars)
- Proper names capitalization

```bash
# Lint all Markdown
task lint-markdown

# Or directly
markdownlint '**/*.md' --ignore node_modules
```

## Formatters

### shfmt

Formats shell scripts with:

- 2-space indentation
- Case indentation
- Simplified redirects

```bash
# Format all shell scripts
task format-shell

# Or directly
shfmt -w -i 2 -ci -sr scripts/*.sh
```

**Before:**

```bash
if [ -f file.txt ]
then
echo "found"
fi
```

**After:**

```bash
if [ -f file.txt ]; then
  echo "found"
fi
```

### Prettier (Optional)

Format YAML, JSON, Markdown:

```bash
# Format YAML files
prettier --write '**/*.yaml'

# Format with specific config
prettier --write --print-width 120 '**/*.md'
```

## Kubernetes Validation

### Kustomize Validation

Validates all `kustomization.yaml` files build successfully:

```bash
# Validate all kustomizations
task validate-kustomize

# Or directly
find infrastructure applications -name "kustomization.yaml" -type f | \
  while read kfile; do
    dir=$(dirname "$kfile")
    kustomize build "$dir" > /dev/null || exit 1
  done
```

### kubectl Validation

Validates Kubernetes manifests with dry-run:

```bash
# Validate all K8s manifests
task validate-k8s

# Or directly
kubectl apply --dry-run=client -f infrastructure/base/monitoring/
```

## Manual Operations

### Run Specific Hook

```bash
# Run pre-commit hook manually
task hooks-run -- pre-commit

# Run on all files (not just staged)
lefthook run pre-commit --all-files
```

### Run All Linters

```bash
# Run all linters
task lint

# Individual linters
task lint-yaml
task lint-shell
task lint-markdown
task lint-secrets
```

### Run All Formatters

```bash
# Format all code
task format

# Individual formatters
task format-shell
```

### Validate Everything

```bash
# Validate all manifests
task validate
```

## Troubleshooting

### Hook Fails on Commit

**Check what failed:**

```bash
# Lefthook shows detailed output
# Look for red ❌ marks

# Run hook manually to debug
lefthook run pre-commit --all-files
```

**Common issues:**

1. **YAML linting fails:**

   ```bash
   # See specific errors
   yamllint --strict infrastructure/

   # Fix indentation, trailing spaces, etc.
   ```

2. **Secret detected:**

   ```bash
   # Review gitleaks output
   gitleaks detect --verbose

   # If false positive, add to .gitleaks.toml allowlist
   ```

3. **Kustomize build fails:**

   ```bash
   # Build manually to see error
   kustomize build infrastructure/base/monitoring/

   # Fix YAML syntax, missing resources, etc.
   ```

### Hook Runs Too Slow

**Disable expensive hooks:**

```bash
# Skip Kubernetes validation on commit
LEFTHOOK_EXCLUDE=kube-validate git commit -m "feat: update"
```

**Or edit `lefthook.yaml`:**

```yaml
pre-commit:
  commands:
    kube-validate:
      skip: true # Temporarily disable
```

### Install Failed

**macOS:**

```bash
# Install with Homebrew
brew install lefthook gitleaks yamllint shellcheck shfmt

# Install markdownlint (requires npm)
npm install -g markdownlint-cli
```

**Linux:**

```bash
# Install via package manager or download binaries
# See Taskfile.yaml install-* tasks for scripts
```

## Configuration Files

| File                 | Purpose                                       |
| -------------------- | --------------------------------------------- |
| `lefthook.yaml`      | Git hooks configuration                       |
| `.gitleaks.toml`     | Secret scanning rules                         |
| `.yamllint.yaml`     | YAML linting rules                            |
| `.markdownlint.yaml` | Markdown linting rules                        |
| `.gitignore`         | Ignore patterns (includes .output/, configs/) |

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Lint and Validate

on: [push, pull_request]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Install tools
        run: |
          curl -1sLf 'https://dl.cloudsmith.io/public/evilmartians/lefthook/setup.sh' | sudo -E bash
          sudo apt-get update && sudo apt-get install -y \
            lefthook gitleaks yamllint shellcheck

      - name: Run linters
        run: lefthook run pre-commit --all-files

      - name: Validate Kubernetes
        run: |
          find infrastructure -name "kustomization.yaml" | \
            xargs -I {} dirname {} | \
            xargs -I {} kustomize build {}
```

### Pre-commit CI Alternative

Use lefthook's built-in `skip_on_ci` feature:

```yaml
# lefthook.yaml
skip_on_ci: false # Run hooks in CI

# Or skip expensive hooks in CI
pre-commit:
  commands:
    kube-validate:
      skip:
        - env: CI # Skip in CI environment
```

## Best Practices

### 1. Always Run Hooks

Don't use `--no-verify` unless absolutely necessary. Hooks prevent:

- Committing secrets
- Breaking Kubernetes manifests
- Inconsistent code style

### 2. Fix Linter Issues Immediately

Don't accumulate linting errors:

```bash
# Check before committing
task lint

# Fix formatting
task format

# Validate manifests
task validate
```

### 3. Keep Configuration Updated

Review and update configs periodically:

- Add new file patterns to `.gitleaks.toml` allowlist
- Update YAMLLint rules for project needs
- Add custom shellcheck rules

### 4. Use Conventional Commits

Enables automated:

- Changelog generation
- Semantic versioning
- Release notes

### 5. Test Hooks Locally

Before pushing:

```bash
# Run all pre-push hooks
lefthook run pre-push

# Validate everything
task lint && task validate
```

## Advanced Usage

### Custom Hooks

Add custom hooks to `lefthook.yaml`:

```yaml
pre-commit:
  commands:
    custom-check:
      run: ./scripts/custom-validation.sh {staged_files}
      glob: '*.yaml'
```

### Parallel Execution

Hooks run in parallel by default:

```yaml
pre-commit:
  parallel: true # Run all commands concurrently
```

### File-Specific Hooks

Target specific files:

```yaml
pre-commit:
  commands:
    helm-lint:
      run: helm lint {staged_files}
      glob: '**/Chart.yaml' # Only run on Helm charts
```

### Skip Patterns

Skip hooks for certain commits:

```yaml
pre-commit:
  commands:
    yamllint:
      skip:
        - merge # Skip on merge commits
        - rebase # Skip during rebase
```

## Reference

### Task Commands

```bash
# Setup
task dev-setup              # Install everything
task hooks-install          # Install git hooks
task hooks-uninstall        # Remove git hooks

# Linting
task lint                   # Run all linters
task lint-yaml              # Lint YAML
task lint-shell             # Lint shell scripts
task lint-markdown          # Lint Markdown
task lint-secrets           # Scan for secrets

# Formatting
task format                 # Format all code
task format-shell           # Format shell scripts

# Validation
task validate               # Validate all manifests
task validate-kustomize     # Validate kustomizations
task validate-k8s           # Validate K8s manifests

# Hooks
task hooks-run -- pre-commit    # Run specific hook
```

### Lefthook Commands

```bash
lefthook install            # Install hooks
lefthook uninstall          # Remove hooks
lefthook run pre-commit     # Run hook manually
lefthook run --all-files    # Run on all files
lefthook version            # Show version
```

## Documentation

- [Lefthook](https://github.com/evilmartians/lefthook)
- [Gitleaks](https://github.com/gitleaks/gitleaks)
- [YAMLLint](https://yamllint.readthedocs.io/)
- [Shellcheck](https://www.shellcheck.net/)
- [Markdownlint](https://github.com/DavidAnson/markdownlint)
- [Conventional Commits](https://www.conventionalcommits.org/)

---

**Quick Reference:**

```bash
# Setup (first time)
task dev-setup

# Before committing
task lint && task format

# Commit (hooks run automatically)
git add .
git commit -m "feat: add new feature"

# If hooks fail, fix issues and retry
task lint  # Find issues
task format  # Auto-fix formatting
git add .
git commit -m "feat: add new feature"
```
