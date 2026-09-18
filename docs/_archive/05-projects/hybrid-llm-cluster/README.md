# Hybrid LLM Cluster

Design and research docs for running on-demand GPU compute on AWS EC2, joined to the homelab over
a Nebula mesh with Liqo / Cilium ClusterMesh federation.

> **Status: dormant.** The grounding pass found the hybrid link inactive — `clustermesh-apiserver`
> is scaled to 0/0, there is no `nebula` namespace, the forwarder manifests are not referenced by
> any kustomization, and the `aws-lighthouse` context is unreachable. See
> [clusters/aws-k3s/README.md](../../../clusters/aws-k3s/README.md).
>
> These docs were **not** part of the 2026-08-22 grounding pass — treat details as unverified.
> Project tracking moved to beads (`TALOS-aev`).

## Quick Navigation

| Document                                                     | Description                                                             |
| ------------------------------------------------------------ | ----------------------------------------------------------------------- |
| [DISCOVERY.md](DISCOVERY.md)                                 | Original discovery/planning: Ollama on EC2 + Nebula + Liqo              |
| [PROJECT-STRUCTURE.md](PROJECT-STRUCTURE.md)                 | Directory layout and component split across the two clusters            |
| [GITOPS-PATTERNS.md](GITOPS-PATTERNS.md)                     | Managing two clusters with different lifecycles from one repo           |
| [PROVISIONING-RECIPE.md](PROVISIONING-RECIPE.md)             | Full provisioning workflow for the mesh + GPU compute + federation      |
| [SCALE-TO-ZERO.md](SCALE-TO-ZERO.md)                         | Scale-to-zero GPU worker architecture (no cost when idle)               |
| [STORAGE-STRATEGY.md](STORAGE-STRATEGY.md)                   | Model storage cost strategy (S3 + local cache)                          |
| [DUAL-INGRESS.md](DUAL-INGRESS.md)                           | Second entry point via AWS Traefik, bypassing the mesh                  |
| [AWS-EC2-INSTANCE-TYPES.md](AWS-EC2-INSTANCE-TYPES.md)       | GPU/compute instance research and the spot quota request                |
| [LIQO-REPEERING-TEST.md](LIQO-REPEERING-TEST.md)             | 2025-12-04 teardown/re-peer validation log — ON HOLD                    |
| [NEXT-STEPS.md](NEXT-STEPS.md)                               | Manual prerequisites checklist before deployment                        |
| [TODO.md](TODO.md)                                           | Superseded — work migrated to beads (`TALOS-aev`)                       |

## Related

- [docs/HYBRID-CLOUD-PLAYBOOK.md](../../HYBRID-CLOUD-PLAYBOOK.md) — the executable playbook version
- [clusters/aws-k3s/README.md](../../../clusters/aws-k3s/README.md) — the AWS side, with live status
- [infrastructure/base/hybrid-llm/nebula/README.md](../../../infrastructure/base/hybrid-llm/nebula/README.md) — Nebula manifests (unwired)
- [docs/07-reference/gpu-instance-guide.md](../../07-reference/gpu-instance-guide.md) — cloud GPU sizing reference

---

## Related Issues

<!-- Beads tracking for this section -->

- `TALOS-aev` — Hybrid LLM Cluster project
