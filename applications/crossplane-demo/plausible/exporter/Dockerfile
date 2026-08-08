# plausible-stats-exporter (TALOS-4gg)
# Tiny static Go build -> FROM scratch. No CGO, no shared libs, no shell.
#
# Build & push (registry is mid-migration — do this later, manually):
#   docker build -t registry.talos00/talos00-registry/plausible-stats-exporter:latest \
#     applications/crossplane-demo/plausible/exporter
#   docker push registry.talos00/talos00-registry/plausible-stats-exporter:latest
FROM golang:1.22-alpine AS build
WORKDIR /src
# go.mod first for layer caching; stdlib-only so there is no go.sum / no download.
COPY go.mod ./
COPY main.go ./
RUN CGO_ENABLED=0 GOFLAGS=-trimpath go build -ldflags="-s -w" -o /plausible-stats-exporter .

FROM scratch
# CA certs so an https PLAUSIBLE_BASE_URL would also work (in-cluster is http).
COPY --from=build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY --from=build /plausible-stats-exporter /plausible-stats-exporter
USER 65534:65534
EXPOSE 8080
ENTRYPOINT ["/plausible-stats-exporter"]
