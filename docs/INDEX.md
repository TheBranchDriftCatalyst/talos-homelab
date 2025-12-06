# Documentation Index

**📚 Complete Navigation Guide for Talos Kubernetes Cluster**

This index uses **progressive summarization** - start with Level 1 for overviews, progress to deeper levels as needed.

---

## 🎯 Quick Navigation

| I want to...                  | Go to                                              |
| ----------------------------- | -------------------------------------------------- |
| Get started quickly           | [Getting Started](#-level-1-getting-started)       |
| Understand the architecture   | [Architecture](#-level-2-architecture)             |
| Provision/operate the cluster | [Operations](#-level-3-operations)                 |
| Deploy applications           | [Deployment](#-level-3-deployment)                 |
| Work on specific projects     | [Projects](#-level-4-projects)                     |
| Track implementation progress | [Project Management](#-level-4-project-management) |
| Find technical references     | [Reference](#-level-5-reference)                   |

---

## Documentation Levels

```
Level 1: Entry Points     → Quick overview, essential commands
Level 2: Architecture     → Understanding system design
Level 3: Operations       → Running and deploying
Level 4: Projects         → Specific implementations
Level 5: Reference        → Deep technical details
```

---

## 📖 Level 1: Getting Started

**Target Audience:** New users, quick reference

### Root Level

| Document                          | Description                              | Length    |
| --------------------------------- | ---------------------------------------- | --------- |
| [README.md](../README.md)         | Main repository overview and quick start | Overview  |
| [QUICKSTART.md](../QUICKSTART.md) | Essential commands reference             | Quick Ref |

### Getting Started Guide

| Document                                                 | Description                    | Length    |
| -------------------------------------------------------- | ------------------------------ | --------- |
| [Getting Started Overview](01-getting-started/README.md) | Complete onboarding guide      | Guide     |
| [Quick Start](01-getting-started/quickstart.md)          | Fast-track setup               | Quick     |
| [Local Testing](01-getting-started/local-testing.md)     | Docker Desktop dev environment | Guide     |
| [Glossary](01-getting-started/glossary.md)               | Terms and concepts             | Reference |

**Start here if:** You're new to the cluster or need quick command reference.

---

## 🏗️ Level 2: Architecture

**Target Audience:** Developers, operators understanding the system

| Document                                                                  | Description                               | Length   | Priority |
| ------------------------------------------------------------------------- | ----------------------------------------- | -------- | -------- |
| [Architecture Overview](02-architecture/README.md)                        | System design summary                     | Overview | ⭐       |
| [Infrastructure Diagrams](02-architecture/infrastructure-diagrams.md)     | **NEW** - Mermaid diagrams of full system | Deep     | ⭐⭐⭐   |
| [Dual GitOps Pattern](02-architecture/dual-gitops.md)                     | **CRITICAL** - Core architecture          | Deep     | ⭐⭐⭐   |
| [GitOps Responsibilities](02-architecture/gitops-responsibilities.md)     | Component breakdown                       | Mid      | ⭐⭐     |
| [Networking & Ingress](02-architecture/networking.md)                     | Traefik, IngressRoutes                    | Deep     | ⭐⭐     |
| [Observability Architecture](02-architecture/observability.md)            | Monitoring & logging design               | Deep     | ⭐⭐     |
| [Service Mesh Strategy](02-architecture/service-mesh.md)                  | Linkerd, Istio, hybrid cluster mesh       | Deep     | ⭐       |
| [Auth Implementation Guide](02-architecture/auth-implementation-guide.md) | LDAP, Authelia, Authentik planning        | Deep     | ⭐       |

**Read these if:** You need to understand how the system works before making changes.

**Key Concepts Covered:**

- Infrastructure GitOps vs Application GitOps
- Traefik ingress controller
- Prometheus + Grafana + OpenSearch stack
- Storage architecture
- Nebula VPN + Liqo multi-cluster federation
- Service mesh with Linkerd

---

## ⚙️ Level 3: Operations

**Target Audience:** Cluster operators, DevOps engineers

| Document                                                            | Description                   | Length    | Use Case       |
| ------------------------------------------------------------------- | ----------------------------- | --------- | -------------- |
| [Operations Overview](03-operations/README.md)                      | Day-to-day operations guide   | Overview  | Daily ops      |
| [Cluster Provisioning](03-operations/provisioning.md)               | Complete cluster setup        | Deep      | Initial setup  |
| [Talos Configuration](03-operations/talos-configuration.md)         | Talos config management       | Deep      | Config changes |
| [Kubernetes Operations](03-operations/kubernetes-operations.md)     | K8s operational tasks         | Mid       | Daily ops      |
| [Monitoring Operations](03-operations/monitoring-operations.md)     | Observability management      | Mid       | Ops            |
| [Node Shutdown Procedure](03-operations/node-shutdown-procedure.md) | Safe shutdown/restart         | Mid       | Maintenance    |
| [Local Development ESO](03-operations/local-development-eso.md)     | External Secrets dev workflow | Mid       | Development    |
| [Development Tools](03-operations/development-tools.md)             | Git hooks, linters, formatters| Mid       | Dev setup      |
| [Troubleshooting Guide](03-operations/troubleshooting.md)           | Common issues & solutions     | Reference | When stuck     |

**Use these for:** Provisioning new clusters, managing existing clusters, troubleshooting.

**Operational Tasks Covered:**

- Fresh cluster provisioning
- Talos configuration changes
- Monitoring stack management
- Common troubleshooting scenarios

---

## 🚀 Level 3: Deployment

**Target Audience:** Application developers, DevOps engineers

| Document                                                     | Description                     | Length   | Use Case       |
| ------------------------------------------------------------ | ------------------------------- | -------- | -------------- |
| [Deployment Overview](04-deployment/README.md)               | Deployment patterns             | Overview | Planning       |
| [Infrastructure Deployment](04-deployment/infrastructure.md) | Platform deployment             | Mid      | Infra changes  |
| [Application Deployment](04-deployment/applications.md)      | App deployment patterns         | Mid      | App deployment |
| [ArgoCD Setup](04-deployment/argocd-setup.md)                | ArgoCD bootstrap & config       | Mid      | GitOps setup   |
| [Flux Setup](04-deployment/flux-setup.md)                    | FluxCD bootstrap & config       | Mid      | GitOps alt     |
| [Catalyst UI Example](04-deployment/catalyst-ui-example.md)  | Complete deployment walkthrough | Deep     | Learning       |

**Use these for:** Deploying infrastructure changes, setting up GitOps, deploying applications.

**Deployment Methods:**

- Manual kubectl apply (infrastructure)
- ArgoCD automated sync (applications)
- FluxCD automated sync (alternative)

---

## 🔬 Level 4: Projects

**Target Audience:** Project developers, feature implementers

### Projects Overview

| Document                                 | Description              |
| ---------------------------------------- | ------------------------ |
| [Projects README](05-projects/README.md) | Overview of all projects |

### Catalyst DNS Sync

| Document                                                    | Description           | Length    | Purpose        |
| ----------------------------------------------------------- | --------------------- | --------- | -------------- |
| [Project README](05-projects/catalyst-dns-sync/README.md)   | Quick reference       | Quick     | Daily use      |
| [Full Proposal](05-projects/catalyst-dns-sync/proposal.md)  | Complete design       | Very Deep | Architecture   |
| [MVP Specification](05-projects/catalyst-dns-sync/mvp.md)   | Phase 1 & 2 checklist | Deep      | Implementation |
| [OP Features](05-projects/catalyst-dns-sync/op-features.md) | Future wishlist       | Mid       | Planning       |

### Catalyst UI

| Document                                                        | Description    | Length | Purpose    |
| --------------------------------------------------------------- | -------------- | ------ | ---------- |
| [Deployment Guide](05-projects/catalyst-ui/deployment-guide.md) | Complete setup | Deep   | Deployment |

### Hybrid LLM Cluster

| Document                                                               | Description                    | Length | Purpose       |
| ---------------------------------------------------------------------- | ------------------------------ | ------ | ------------- |
| [Discovery](05-projects/hybrid-llm-cluster/DISCOVERY.md)               | Project discovery & research   | Mid    | Planning      |
| [Project Structure](05-projects/hybrid-llm-cluster/PROJECT-STRUCTURE.md) | Repository & component layout | Mid    | Architecture  |
| [GitOps Patterns](05-projects/hybrid-llm-cluster/GITOPS-PATTERNS.md)   | Multi-cluster GitOps approach  | Mid    | Architecture  |
| [Storage Strategy](05-projects/hybrid-llm-cluster/STORAGE-STRATEGY.md) | S3 + local storage design      | Mid    | Architecture  |
| [AWS EC2 Instance Types](05-projects/hybrid-llm-cluster/AWS-EC2-INSTANCE-TYPES.md) | GPU instance research | Mid | Reference |
| [Next Steps](05-projects/hybrid-llm-cluster/NEXT-STEPS.md)             | Implementation roadmap         | Quick  | Planning      |

**Use these for:** Working on specific features, understanding project scope.

---

## 📊 Level 4: Project Management

**Target Audience:** Project managers, team leads, stakeholders

| Document                                                                  | Description               | Length   | Update Frequency |
| ------------------------------------------------------------------------- | ------------------------- | -------- | ---------------- |
| [PM Overview](06-project-management/README.md)                            | Project tracking intro    | Overview | As needed        |
| [Implementation Tracker](06-project-management/implementation-tracker.md) | 7-phase progress tracker  | Deep     | Weekly           |
| [Progress Summary](06-project-management/progress-summary.md)             | Session-by-session log    | Deep     | Per session      |
| [Enhancement Roadmap](06-project-management/enhancement-roadmap.md)       | MCP server & Tilt roadmap | Mid      | As needed        |

### Migration Assessments

| Document                                                                        | Description                 | Length | Status  |
| ------------------------------------------------------------------------------- | --------------------------- | ------ | ------- |
| [Flux Migration](_archive/flux-migration.md) | FluxCD deployment readiness | Deep   | Pending |

**Use these for:** Tracking project progress, planning, decision logging.

---

## 📚 Level 5: Reference

**Target Audience:** Advanced users, system architects

| Document                                                       | Description               | Length    | Use Case    |
| -------------------------------------------------------------- | ------------------------- | --------- | ----------- |
| [Reference Overview](07-reference/README.md)                   | Technical reference index | Overview  | Navigation  |
| [Taskfile Organization](07-reference/taskfile-organization.md) | Task automation structure | Mid       | Tooling     |
| [Talos Config Spec](07-reference/talos-config-spec.md)         | Machine config deep dive  | Deep      | Config      |
| [Kustomize Patterns](07-reference/kustomize-patterns.md)       | Kustomize examples        | Mid       | Templates   |
| [API References](07-reference/api-references.md)               | API documentation         | Reference | Integration |
| [Reorganization Summary](07-reference/REORGANIZATION-COMPLETE.md) | Doc restructure details | Deep      | Historical  |

### Helm Values

- [ArgoCD Values](07-reference/helm-values/argocd-values.yaml)
- [Traefik Values](07-reference/helm-values/traefik-values.yaml)
- [Prometheus Stack Values](07-reference/helm-values/kube-prometheus-stack-values.yaml)

**Use these for:** Deep technical implementation, troubleshooting, customization.

---

## 🤖 Meta Documentation

| Document                  | Description                 | Audience                      |
| ------------------------- | --------------------------- | ----------------------------- |
| [CLAUDE.md](../CLAUDE.md) | Guidance for Claude Code AI | AI assistants, advanced users |

This file serves as the comprehensive guide for Claude Code instances working in the repository.

---

## 🗺️ Document Relationships

```
README.md (Entry)
    ├──> QUICKSTART.md (Commands)
    ├──> 02-architecture/dual-gitops.md (Core concept)
    ├──> 03-operations/provisioning.md (Setup)
    └──> 04-deployment/ (Deployment)

dual-gitops.md (Architecture)
    ├──> gitops-responsibilities.md (Details)
    ├──> 04-deployment/argocd-setup.md (Implementation)
    └──> 04-deployment/flux-setup.md (Alternative)

provisioning.md (Operations)
    ├──> talos-configuration.md (Config details)
    ├──> 01-getting-started/local-testing.md (Dev setup)
    └──> troubleshooting.md (Issues)

Projects
    ├──> catalyst-dns-sync/ (DNS automation)
    └──> catalyst-ui/ (UI deployment example)
```

---

## 📝 Documentation Standards

### File Naming

- Use lowercase with hyphens: `dual-gitops.md`
- READMEs for directory overviews
- Descriptive names: `flux-migration.md` not `migration.md`

### Document Structure

Each document should include:

1. **Title** - Clear, descriptive
2. **Overview** - 2-3 sentence summary
3. **Table of Contents** - For docs > 100 lines
4. **See Also** - Related documents
5. **Last Updated** - Date stamp

### Cross-Linking

- Use relative paths: `[GitOps](../02-architecture/dual-gitops.md)`
- Add "See Also" sections
- Link to related topics

### Progressive Detail

- **Level 1-2**: Overview, "what" and "why"
- **Level 3**: Practical "how"
- **Level 4**: Specific implementations
- **Level 5**: Deep technical "internals"

---

## 🔄 Maintenance

### When Adding New Documentation

1. Place in appropriate level directory
2. Update this INDEX.md
3. Update CLAUDE.md table of contents
4. Add cross-references in related docs
5. Follow naming conventions

### When Updating Documentation

1. Update "Last Modified" date
2. Check cross-references are still valid
3. Update INDEX.md if scope changes
4. Note changes in Progress Summary

### Regular Reviews

- **Monthly**: Check for outdated information
- **Quarterly**: Validate all cross-links
- **Major Changes**: Update INDEX.md structure

---

## 🎓 Recommended Reading Paths

### Path 1: New User Onboarding

1. README.md
2. QUICKSTART.md
3. 02-architecture/dual-gitops.md
4. 03-operations/provisioning.md
5. 01-getting-started/local-testing.md

### Path 2: Application Developer

1. QUICKSTART.md
2. 02-architecture/dual-gitops.md
3. 04-deployment/applications.md
4. 04-deployment/ArgoCD-setup.md
5. 05-projects/catalyst-ui/deployment-guide.md

### Path 3: Cluster Operator

1. README.md
2. 02-architecture/ (all files)
3. 03-operations/provisioning.md
4. 03-operations/Kubernetes-operations.md
5. 03-operations/troubleshooting.md

### Path 4: Project Contributor

1. 05-projects/catalyst-dns-sync/README.md
2. 05-projects/catalyst-dns-sync/mvp.md
3. 02-architecture/dual-gitops.md
4. 04-deployment/applications.md

---

## 📞 Getting Help

- **Stuck?** → [Troubleshooting Guide](03-operations/troubleshooting.md)
- **New to Talos?** → [Getting Started](01-getting-started/README.md)
- **Architecture questions?** → [Dual GitOps](02-architecture/dual-gitops.md)
- **Deployment issues?** → [Deployment Guides](04-deployment/README.md)

---

**Last Updated:** 2025-11-30
**Maintained By:** Infrastructure Team
**Document Version:** 2.0.0
