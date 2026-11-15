#!/usr/bin/env bash
# Build + push the God's Eye View image to Zot. Upstream publishes no container.
#
# This uses UPSTREAM'S OWN Dockerfile unmodified -- there is no Dockerfile in
# this directory on purpose. The image is self-contained (it COPYs the source
# in); compose only bind-mounts for hot-reload, which we do not want.
#
# TWO THINGS THAT WILL BITE YOU:
#  1. Every node is amd64 and your Mac is arm64 -- --platform=linux/amd64 is
#     not optional. A native build pushes an arm64 image that passes every
#     check and then fails at the kubelet with "no match for platform".
#  2. A `docker-container` buildx driver CANNOT push here: it is an isolated
#     BuildKit container with its own trust store and does not have the homelab
#     CA, so --push dies with "certificate signed by unknown authority". The
#     Docker daemon does trust it. Hence --load, then `docker push`.
#
# It is a big one (~280MB of source + a full npm ci), so expect a slow first
# build under amd64 emulation.
set -euo pipefail

UPSTREAM=https://github.com/bilawalsidhu/gods-eye-view.git
REF=${REF:-574d873} # pinned; bump deliberately
IMAGE=registry.talos00/talos00-registry/godseye
TAG=${TAG:-0.3.0}

src=$(mktemp -d)
trap 'rm -rf "$src"' EXIT
git clone --filter=blob:none "$UPSTREAM" "$src"
git -C "$src" checkout "$REF"

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
