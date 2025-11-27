# Stack Dashboard

A reusable Kubernetes stack dashboard built with [Textual](https://textual.textualize.io/) - a modern TUI framework for Python.

## Features

- **Live-updating dashboard** - Auto-refreshes service status, pod health, and PVC info
- **Click-to-copy credentials** - Click on any credential to copy to clipboard
- **Keyboard shortcuts** - Press 1-9 to quickly copy credentials
- **Configurable via YAML** - Define your stack once, reuse the dashboard
- **Volume status** - See PVC binding status with visual indicators
- **Credential extraction** - Auto-extract API keys from:
  - Kubernetes Secrets
  - \*arr config.xml files
  - JSON config files
  - Plex Preferences.xml

## Installation

```bash
cd tools/stack-dashboard

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e .

# Or with uv (faster)
uv pip install -e .
```

## Usage

### Run with a config file

```bash
# ARR Stack dashboard
stack-dashboard -c configs/arr-stack.yaml

# Or run directly with Python
python -m stack_dashboard.cli -c configs/arr-stack.yaml
```

### Run with defaults

```bash
# Uses media-prod namespace with default domain
stack-dashboard

# Custom namespace/domain
stack-dashboard -n monitoring -d mycluster.local
```

## Keyboard Shortcuts

| Key   | Action                    |
| ----- | ------------------------- |
| `q`   | Quit                      |
| `r`   | Refresh data              |
| `1-9` | Copy credential by number |
| Click | Copy clicked credential   |

## Configuration

Stack configurations are YAML files that define:

- **Stack metadata** - name, namespace, domain
- **Service groups** - logical groupings of services
- **Services** - individual services with credential extraction
- **Global credentials** - credentials not tied to specific services

### Example Configuration

```yaml
name: my-stack
display_name: My Stack
namespace: my-namespace
domain: mydomain.local
refresh_interval: 10.0

groups:
  - name: apps
    display_name: Applications
    services:
      - name: myapp
        display_name: My App
        credential:
          name: myapp
          type: api_key
          source: config_xml
          config_path: /config/config.xml
          xml_tag: ApiKey

global_credentials:
  - name: database
    display_name: Database
    type: userpass
    source: secret
    secret_name: db-secret
    static_username: admin
    password_key: password
```

### Credential Sources

| Source            | Description                       | Config Fields                  |
| ----------------- | --------------------------------- | ------------------------------ |
| `secret`          | Kubernetes Secret                 | `secret_name`, `secret_key`    |
| `config_xml`      | XML config file (like \*arr apps) | `config_path`, `xml_tag`       |
| `config_json`     | JSON config file                  | `config_path`, `json_path`     |
| `preferences_xml` | Plex-style preferences            | `config_path`, `xml_attribute` |

### Credential Types

| Type       | Description       | Display Format |
| ---------- | ----------------- | -------------- |
| `api_key`  | API key/token     | `apikey:VALUE` |
| `userpass` | Username/password | `USER:PASS`    |
| `token`    | Bearer token      | `apikey:VALUE` |

## Creating a New Stack Config

1. Copy an existing config as a template:

   ```bash
   cp configs/arr-stack.yaml configs/my-stack.yaml
   ```

2. Edit the config with your services

3. Run the dashboard:
   ```bash
   stack-dashboard -c configs/my-stack.yaml
   ```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run in dev mode with hot reload
textual run --dev -c stack_dashboard.app:StackDashboardApp

# Run console for debugging
textual console
```

## Architecture

```
src/stack_dashboard/
├── __init__.py      # Package init
├── app.py           # Main Textual application
├── cli.py           # CLI entry point
├── credentials.py   # Credential extraction logic
├── k8s.py           # Kubernetes client & data fetching
├── models.py        # Data models (StackConfig, ServiceConfig, etc.)
└── widgets.py       # Custom Textual widgets
```

## Adding to Other Stacks

The dashboard is designed to be reusable. To add monitoring for another stack:

1. Create a new config file in `configs/`
2. Define your services and credentials
3. Add a shell wrapper script if desired

Example infrastructure stack config:

```yaml
name: infrastructure
display_name: Infrastructure Stack
namespace: monitoring

groups:
  - name: monitoring
    display_name: Monitoring
    services:
      - name: prometheus
        display_name: Prometheus
      - name: grafana
        display_name: Grafana
        credential:
          type: userpass
          source: secret
          secret_name: grafana-secret
          username_key: admin-user
          password_key: admin-password
```
