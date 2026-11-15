#!/usr/bin/env bash
# Build + push the OpenCharts image to Zot. Upstream publishes no container.
#
# The upstream SOURCE IS NOT VENDORED into this repo (third-party source belongs
# in a sister workspace repo, not in the infra repo), so this clones the pinned
# commit into a temp dir and builds our Dockerfile against it.
#
# TWO THINGS THAT WILL BITE YOU:
#  1. Every node is amd64 and your Mac is arm64 -- --platform=linux/amd64 is
#     not optional. A native build pushes an arm64 image that passes every
#     check and then fails at the kubelet with "no match for platform".
#  2. A `docker-container` buildx driver CANNOT push here: it is an isolated
#     BuildKit container with its own trust store and does not have the homelab
#     CA, so --push dies with "certificate signed by unknown authority". The
#     Docker daemon does trust it. Hence --load, then `docker push`.
set -euo pipefail

UPSTREAM=https://github.com/dylanpersonguy/OpenCharts.git
REF=${REF:-399e275} # pinned; bump deliberately
IMAGE=registry.talos00/talos00-registry/opencharts
TAG=${TAG:-0.3.0}
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

src=$(mktemp -d)
trap 'rm -rf "$src"' EXIT
git clone --filter=blob:none "$UPSTREAM" "$src"
git -C "$src" checkout "$REF"
cp "$HERE/Dockerfile" "$HERE/nginx.conf" "$src/"

docker buildx build --platform linux/amd64 \
  -t "$IMAGE:$TAG" -t "$IMAGE:latest" \
  --label org.opencontainers.image.source="$UPSTREAM" \
  --label org.opencontainers.image.revision="$(git -C "$src" rev-parse HEAD)" \
  --load "$src"

docker push "$IMAGE:$TAG"
docker push "$IMAGE:latest"
echo
echo "Now pin the digest in ../deployment.yaml:"
docker inspect --format '{{index .RepoDigests 0}}' "$IMAGE:$TAG"
