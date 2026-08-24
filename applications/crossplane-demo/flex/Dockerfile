# syntax=docker/dockerfile:1

# ---- build stage ----------------------------------------------------------
FROM golang:1.23 AS build
WORKDIR /src

# Cache module downloads separately from source.
COPY go.mod go.sum ./
RUN go mod download

# Build a fully static, stripped binary — no libc, so it runs on distroless/static.
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /flex .

# ---- runtime stage --------------------------------------------------------
# distroless/static:nonroot => no shell, no package manager, runs as uid 65532.
# Includes CA certs (needed for the OpenSearch HTTPS check).
FROM gcr.io/distroless/static:nonroot
COPY --from=build /flex /flex
EXPOSE 8080
USER nonroot:nonroot
ENTRYPOINT ["/flex"]
