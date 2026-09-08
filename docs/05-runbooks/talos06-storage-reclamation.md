# talos06 storage reclamation

Measured September 7, 2026, before tuning: 743.6 GiB used of 928.9 GiB,
185.3 GiB available, DiskPressure false. Kubelet reports 568.9 GiB of runtime
image/snapshot usage on the same filesystem. This is the main consumer:
907 unique cached image digests, including old media-ingest and stash-tagger builds.
Running container writable layers total about 1.8 GiB and logs about 0.85 GiB.

Persistent data also includes a Windows gameserver disk (150 GiB logical),
Zot registry (~22 GB), Windows ISO (~10 GB), and LiteLLM PostgreSQL (~9.6 GB).
These are logical sizes, potentially sparse, and must not be added directly to
physical filesystem usage. PVC data is not an image garbage-collection target.

## Policy

`configs/patches/talos06-image-gc.yaml`, included only by talos06 in
`configs/talconfig.yaml`, lowers image GC's disk trigger from 85% to **80%**
and its target from 80% to **70%**. Other nodes retain their existing policy.
The shared **336-hour (14-day)** unused-image age remains enabled.
Kubelet chooses unused images for removal; images used by running containers
are protected. A later workload may need to pull a removed image again.
Reaching 70% depends on how much eligible, unshared image data can be reclaimed.

Image age tracking resets when kubelet restarts. The previous August 31 restart
therefore postponed age eligibility until September 14; applying this configuration
restarts that clock again. The lower disk threshold provides earlier cleanup
independently of age. See the [Kubernetes garbage-collection documentation](https://kubernetes.io/docs/concepts/architecture/garbage-collection/).

Container logs rotate at 10 MiB per file, five files per container. Zot has
deduplication and garbage collection enabled with a two-hour delay, but retains
tagged images without an automatic tag-retention policy. Database and VM volumes
do not age-prune.

## Apply and verify

Generate with `task talos:gen-config`. Review the generated talos06 config using
`talosctl --talosconfig configs/talosconfig -n 192.168.1.19 apply-config --dry-run --mode=no-reboot --file configs/clusterconfig/catalyst-cluster-talos06.yaml`.
The September 7 dry run contained only the two image-GC threshold additions.
Apply that same reviewed file with `--mode=no-reboot` and without `--dry-run`.

Check effective settings after kubelet reloads:

```sh
kubectl get --raw /api/v1/nodes/talos06/proxy/configz |
  jq '.kubeletconfig | {imageGCHighThresholdPercent, imageGCLowThresholdPercent, imageMaximumGCAge}'
kubectl get --raw /api/v1/nodes/talos06/proxy/stats/summary |
  jq '.node | {fs, imageFs: .runtime.imageFs}'
kubectl get node talos06
```

Image GC runs periodically; do not mistake the first response during kubelet
reload for the final effective policy. Monitor free space and node health rather
than assuming the target was reached merely because configuration applied.
