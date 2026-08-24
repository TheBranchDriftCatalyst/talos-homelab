# Troubleshooting

Post-mortems and hardware/kernel workarounds. Incident docs are dated and kept as written — they
are a historical record, not current-state documentation.

## Quick Navigation

| Document                                                                                                       | Description                                                                                                             | When to Read                                       |
| -------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------- |
| [2026-05-29-six-meltdowns-and-the-real-root-cause.md](2026-05-29-six-meltdowns-and-the-real-root-cause.md)      | 8 episodes of full control-plane unreachability; identifies the real root cause (CiliumIdentity bloat from a label filter) | **Read first** for any cilium-agent restart loop |
| [2026-05-21-cilium-cascading-meltdown.md](2026-05-21-cilium-cascading-meltdown.md)                              | Earlier post-mortem: a Cilium DaemonSet restart broke control-plane networking on all 5 nodes for ~40 min                | Background on the same failure class               |
| [nvidia-ebpf-workaround.md](nvidia-ebpf-workaround.md)                                                          | NVIDIA containers fail on Talos kernel 6.12 (eBPF cgroup device filter bug); documents the working CDI workaround        | Bringing up an NVIDIA GPU node                     |

## Key Points

- For a cilium-agent restart loop, check `kubectl get ciliumidentities | wc -l` first — >1000 indicates the label-filter regression.
- Recovery procedures live in [05-runbooks](../05-runbooks/README.md); these docs explain *why*, not *how to rebuild*.
- Broader audit findings are in [investigations](../investigations/README.md).

---

## Related Issues

<!-- Beads tracking for this section -->
