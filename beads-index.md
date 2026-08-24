# Beads Issue Index

> **Human-readable view of project issues tracked in `.beads/`**
>
> Run `bd list` or `bd ready` for live data. This file is a snapshot.
>
> Last generated: 2025-12-12

---

## Quick Stats

| Metric        | Count |
| ------------- | ----- |
| Total Issues  | 32    |
| Open          | 17    |
| In Progress   | 0     |
| Closed        | 15    |
| Blocked       | 6     |
| Ready to Work | 11    |

---

## Active Epics

### GPU Node Setup (`TALOS-fpp`) - P1

**Set up talos02-gpu worker node with Intel Arc**

Configure ASUS NUC 15 Pro as GPU-enabled worker for Plex/Tdarr transcoding.

| Task                                         | Priority | Status  |
| -------------------------------------------- | -------- | ------- |
| `TALOS-y1c` Boot with custom Talos image     | P1       | ready   |
| `TALOS-dfv` Verify GPU device and NFD labels | P2       | blocked |
| `TALOS-9ku` Configure Plex/Tdarr for GPU     | P2       | blocked |

**Note:** `intel-gpu` Flux kustomization suspended until ready.

---

### macOS Notifications (`TALOS-8uv`) - P2

**Native notifications for cluster events via ntfy.sh**

| Task                                                   | Priority | Status  |
| ------------------------------------------------------ | -------- | ------- |
| `TALOS-26f` Investigate notification sources & classes | P1       | ready   |
| `TALOS-dv3` Deploy ntfy Provider                       | P2       | blocked |
| `TALOS-q4s` Configure Flux Alert CRDs                  | P2       | blocked |
| `TALOS-v3a` Set up ntfy-desktop on Mac                 | P3       | blocked |
| `TALOS-m0x` Create Mac provisioning (Homebrew/Ansible) | P3       | blocked |
| `TALOS-ag3` Alertmanager integration (stretch)         | P3       | ready   |

---

### Media Stack Configuration (`TALOS-a23`) - P3

**Configure deployed \*arr applications**

- Prowlarr indexers
- Sonarr/Radarr connections
- Plex/Jellyfin libraries
- Homepage widgets

---

### MCP Server Integration (`TALOS-7fu`) - P3

**AI-powered cluster management**

Deploy MCP servers for natural language cluster queries:

- Kubernetes MCP Server
- Grafana MCP Server
- Prometheus MCP Server

---

### Hybrid LLM Cluster (`TALOS-aev`) - P4 (Suspended)

**Nebula + Liqo + AWS GPU cluster**

Multi-phase project for distributed LLM inference. Currently suspended.

---

## Standalone Issues

### Infrastructure

| ID          | Title                                   | Type    | Priority | Status |
| ----------- | --------------------------------------- | ------- | -------- | ------ |
| `TALOS-8ey` | Implement backup strategy for etcd/PVCs | feature | P2       | ready  |
| `TALOS-i11` | Add HTTPS/TLS to Traefik                | feature | P3       | ready  |

### Development

| ID          | Title                              | Type | Priority | Status |
| ----------- | ---------------------------------- | ---- | -------- | ------ |
| `TALOS-w1k` | Complete Tilt workflow integration | task | P3       | ready  |

---

## Ready to Work

Issues with no blockers - pick one up!

```
bd ready
```

| ID          | Title                                    | Priority |
| ----------- | ---------------------------------------- | -------- |
| `TALOS-y1c` | Boot talos02-gpu with custom Talos image | P1       |
| `TALOS-26f` | Investigate notification sources         | P1       |
| `TALOS-fpp` | GPU node epic                            | P1       |
| `TALOS-8ey` | Backup strategy                          | P2       |
| `TALOS-8uv` | Notifications epic                       | P2       |
| `TALOS-w1k` | Tilt integration                         | P3       |
| `TALOS-7fu` | MCP servers                              | P3       |
| `TALOS-i11` | HTTPS/TLS                                | P3       |
| `TALOS-a23` | Media stack config                       | P3       |
| `TALOS-ag3` | Alertmanager integration                 | P3       |
| `TALOS-aev` | LLM cluster (suspended)                  | P4       |

---

## Beads Commands Reference

```bash
# Find work
bd ready                    # Show unblocked issues
bd list --status=open       # All open issues
bd list --status=in_progress # Active work
bd blocked                  # Show what's stuck

# Work on issues
bd show <id>                # View details
bd update <id> --status=in_progress  # Claim work
bd close <id>               # Mark complete

# Create issues
bd create --title="..." --type=task
bd dep add <issue> <depends-on>  # Add dependency

# Sync
bd sync                     # Sync with git
bd stats                    # Project health
```

---

## Migration Notes

This file replaces the following distributed TODO files:

- `docs/_archive/TODO.md` (archived)
- `docs/05-projects/hybrid-llm-cluster/TODO.md` (migrated to `TALOS-aev`)
- `IMPLEMENTATION-TRACKER.md` (reference only, mostly complete)
- `docs/06-project-management/enhancement-roadmap.md` (migrated relevant items)

All actionable items have been converted to beads issues.
