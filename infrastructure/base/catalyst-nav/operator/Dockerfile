# catalyst-nav-operator.
#
# Build & push (no CI in this repo builds images — verified: no workflow, no Taskfile task and
# no lefthook hook does, so this is manual like the plausible exporter's):
#
#   docker build --platform linux/amd64 \
#     -t registry.talos00/talos00-registry/catalyst-nav-operator:v0.1.0 \
#     infrastructure/base/catalyst-nav/operator
#   docker push registry.talos00/talos00-registry/catalyst-nav-operator:v0.1.0
#
# --platform linux/amd64 IS REQUIRED. Every node in this cluster is amd64; a build on an
# Apple Silicon workstation defaults to arm64 and produces an image that pulls perfectly
# and then dies with `exec /catalyst-nav-operator: exec format error`. That surfaces as
# CrashLoopBackOff AFTER a successful pull, so it reads like an application fault rather
# than a build mistake. Observed 2026-11-06.
#
# Then resolve the pushed digest and pin it in deployment.yaml — a mutable tag on a running
# workload is an upgrade trigger, not a version.
#
# DIVERGENCE FROM THE PLAUSIBLE-EXPORTER PATTERN, stated because that pattern's header makes a
# point of it: the exporter is "stdlib-only on purpose: no go.sum, no module downloads, builds
# fully offline". This cannot be. A kubebuilder operator needs controller-runtime, so there IS
# a go.sum (committed) and there IS a module download step. The exporter's property was worth
# having and is simply not available for this component.
FROM golang:1.27-alpine AS build
WORKDIR /src
# Manifests go in the same directory as the source (the repo's convention), so copy the Go
# tree explicitly rather than `COPY . .` — otherwise every YAML edit busts the build cache.
COPY go.mod go.sum ./
RUN go mod download
COPY cmd/ cmd/
COPY api/ api/
COPY internal/ internal/
RUN CGO_ENABLED=0 GOFLAGS=-trimpath go build -ldflags="-s -w" \
    -o /catalyst-nav-operator ./cmd/catalyst-nav-operator

# distroless static, not scratch: the webhook server speaks TLS to the apiserver and needs
# /etc/ssl/certs plus the nonroot uid 65532 the Deployment's securityContext names. scratch
# would work only by copying both in by hand.
FROM gcr.io/distroless/static:nonroot
COPY --from=build /catalyst-nav-operator /catalyst-nav-operator
USER 65532:65532
EXPOSE 9443 8080 8081
ENTRYPOINT ["/catalyst-nav-operator"]
