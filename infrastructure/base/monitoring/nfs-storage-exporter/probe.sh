#!/bin/sh
# NFS backend free-space exporter — fills a real gap: node-exporter runs ON the
# Talos nodes and therefore CANNOT see the NAS behind the NFS storage classes
# (fatboy-nfs-appdata / synology-nfs / tdarr-nfs). node_filesystem_* covers only
# local node disks.
#
# HOW (no privilege, no hardcoded server): we bind a normal PVC on an NFS storage
# class ($STORAGECLASS) at $PROBE_PATH. `df` on that mount reports the WHOLE
# underlying NAS filesystem (server:/volume1 …) — total/used/avail — because the
# dynamic provisioner just carves a subdir out of the shared export. So one cheap
# probe PVC yields true NAS capacity, and the server/export are DISCOVERED from
# df output (never baked into the manifest).
#
# METRICS: this loop writes Prometheus exposition text to $METRICS_FILE on a
# shared emptyDir; a sibling busybox-httpd sidecar serves it at :9092/metrics and
# the nfs-storage-exporter PodMonitor scrapes it into Mimir via Alloy. Same shape
# as pihole/nebula-sync (no server in THIS container → minimal image). All gauges.
#
# NOTE ON $VARS: embedded into a ConfigMap. The kustomization annotates it
# `kustomize.toolkit.fluxcd.io/substitute: disabled` so Flux envsubst leaves it
# alone; still, we use BARE $VAR (runtime env) and awk `$N` fields freely.
set -u

METRICS_FILE=/metrics/metrics           # shared emptyDir; httpd sidecar docroot=/metrics
PROBE_PATH="${PROBE_PATH:-/nas}"        # where the NFS probe PVC is mounted
STORAGECLASS="${STORAGECLASS:-unknown}" # label only (which class this probe rides)
INTERVAL="${INTERVAL:-60}"

write_metrics() {
  # $1=success(0|1). df -Pk = POSIX one-line rows, 1024-byte blocks. awk turns the
  # $PROBE_PATH row into byte gauges + parses server:/export from the source field.
  {
    printf '# HELP nfs_backend_scrape_success 1 if df of the NFS probe mount succeeded.\n'
    printf '# TYPE nfs_backend_scrape_success gauge\n'
    printf 'nfs_backend_scrape_success{storageclass="%s"} %s\n' "$STORAGECLASS" "$1"
    printf '# HELP nfs_backend_last_scrape_timestamp_seconds Unix time of the last df probe.\n'
    printf '# TYPE nfs_backend_last_scrape_timestamp_seconds gauge\n'
    printf 'nfs_backend_last_scrape_timestamp_seconds{storageclass="%s"} %s\n' "$STORAGECLASS" "$(date +%s)"
    if [ "$1" = 1 ]; then
      df -Pk "$PROBE_PATH" 2> /dev/null | awk -v sc="$STORAGECLASS" -v mp="$PROBE_PATH" '
        $6 == mp {
          src = $1; srv = src; xport = src   # NB: awk reserves "exp" (exponential) — use xport
          i = index(src, ":")
          if (i > 0) { srv = substr(src, 1, i - 1); xport = substr(src, i + 1) }
          size = $2 * 1024; used = $3 * 1024; avail = $4 * 1024
          # IMPORTANT: format byte gauges with %.0f, NOT %d. busybox awk (alpine)
          # converts %d through a 32-bit C int, so any value > 2 GiB saturates to
          # INT32_MIN (-2147483648 = -2 GiB). A multi-TB NAS therefore emitted
          # size/used/avail all = -2 GiB (and %used = 100%) on the dashboard.
          # %.0f prints the double as a full-precision integer with no 32-bit cast
          # (exact for byte counts well past 2^53 / petabytes).
          printf "# HELP nfs_backend_size_bytes Total size of the NAS filesystem backing the NFS storage class.\n"
          printf "# TYPE nfs_backend_size_bytes gauge\n"
          printf "nfs_backend_size_bytes{storageclass=\"%s\",server=\"%s\",export=\"%s\"} %.0f\n", sc, srv, xport, size
          printf "# HELP nfs_backend_used_bytes Used bytes on the NAS filesystem.\n"
          printf "# TYPE nfs_backend_used_bytes gauge\n"
          printf "nfs_backend_used_bytes{storageclass=\"%s\",server=\"%s\",export=\"%s\"} %.0f\n", sc, srv, xport, used
          printf "# HELP nfs_backend_avail_bytes Available bytes on the NAS filesystem.\n"
          printf "# TYPE nfs_backend_avail_bytes gauge\n"
          printf "nfs_backend_avail_bytes{storageclass=\"%s\",server=\"%s\",export=\"%s\"} %.0f\n", sc, srv, xport, avail
        }'
    fi
  } > "$METRICS_FILE.tmp" 2> /dev/null && mv "$METRICS_FILE.tmp" "$METRICS_FILE" 2> /dev/null
}

echo "nfs-storage-exporter starting (probe=$PROBE_PATH class=$STORAGECLASS interval=${INTERVAL}s)"
write_metrics 0 # seed so the endpoint is scrapable before the first df lands
while true; do
  if df -Pk "$PROBE_PATH" > /dev/null 2>&1; then
    write_metrics 1
  else
    echo "df of $PROBE_PATH failed (mount not ready?)"
    write_metrics 0
  fi
  sleep "$INTERVAL"
done
