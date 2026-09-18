{
  description = "talos-homelab — Talos Linux + Flux/ArgoCD cluster toolchain";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs =
    { nixpkgs, ... }:
    let
      # one dev shell per platform, so it works on the mac and on linux CI
      forEachSystem =
        f:
        nixpkgs.lib.genAttrs [
          "aarch64-darwin"
          "x86_64-darwin"
          "x86_64-linux"
          "aarch64-linux"
        ] (system: f nixpkgs.legacyPackages.${system});
    in
    {
      devShells = forEachSystem (
        pkgs:
        let
          # The pytest suites (pytest.ini `testpaths`) import only pytest and
          # yaml; rich is for scripts/upgrade-talos.py when it is run as a
          # plain script rather than through its uv shebang.
          pythonEnv = pkgs.python312.withPackages (ps: [
            ps.pytest
            ps.pyyaml
            ps.rich
          ]);
        in
        {
          default = pkgs.mkShell {
            packages = with pkgs; [
              # ── Talos ──────────────────────────────────────────────────
              # nixpkgs currently ships v1.14.0 against a cluster pinned to
              # v1.13.9 (configs/talconfig.yaml:29) — one minor ahead, and
              # still a tighter match than the v1.13.3 Homebrew had drifted
              # to. talhelper generates configs/ from talconfig.yaml.
              talosctl
              talhelper

              # ── Kubernetes ─────────────────────────────────────────────
              # kubectl is +1 minor ahead of the cluster's v1.36.4, inside
              # the supported skew window.
              kubectl
              kustomize
              kubernetes-helm # lefthook helm-lint
              k9s
              kubectx # ships kubens too

              # ── GitOps / dev loop ──────────────────────────────────────
              fluxcd # `flux`
              go-task # `task` — the entry point for everything
              tilt
              lefthook # git hooks

              # The Go TOOLCHAIN, not just Go-built binaries. dev/docs-generator/
              # is a Go module (`docsgen`), and `task docs:build` compiles it into
              # dev/docs-generator/bin, which the shellHook below puts on PATH.
              # `go` tracks the current nixpkgs default rather than a pinned
              # go_1_xx, so the toolchain moves with the flake lock instead of
              # rotting behind it.
              go

              # Issue tracking. CLAUDE.md mandates bd over TodoWrite, so the
              # repo should carry it. nixpkgs pins 1.2.2 — deliberately the
              # release that refuses the schema-corrupting 1.2.1.
              beads

              # ── Lint / format ──────────────────────────────────────────
              gitleaks
              yamllint
              yamlfmt # lefthook `format-yaml` — brew never installed it
              shellcheck
              shfmt
              prettier
              markdownlint-cli2

              # No nodejs/yarn on purpose (TALOS-hurz): package.json, yarn.lock
              # and node_modules/ are gone, and the two tools they existed for —
              # prettier and markdownlint-cli2 — are nixpkgs packages above that
              # vendor their own node. Nothing in the repo shells out to
              # node/npx/yarn any more.

              # ── Shell tooling used by scripts/ ─────────────────────────
              jq
              gum # scripts/namespace-dashboard.sh

              # ── Python ─────────────────────────────────────────────────
              # uv is REQUIRED, not optional: scripts/upgrade-talos.py is a
              # PEP-723 script whose shebang is `env -S uv run --quiet`, and
              # `task talos:upgrade` (dev/Taskfile.talos.yaml:251) invokes it.
              uv
              pythonEnv
            ];

            # pythonEnv must be PREPENDED, not merely listed. Several of the
            # packages above are themselves Python applications and drag a
            # bare python3 (3.14) into the shell's PATH ahead of our env, so
            # `python` resolved to 3.14 without pyyaml/rich/pytest. Listing
            # order in `packages` does not settle this; an explicit prepend
            # does.
            shellHook = ''
              export PATH="${pythonEnv}/bin:$PATH"

              # Repo-local Go tools built by `task docs:build`. Putting the build
              # output on PATH is what lets `docsgen lint` be typed anywhere in the
              # repo without a path prefix or a `go run` incantation.
              #
              # GOWORK=off is deliberate: a parent go.work in the surrounding
              # workspace otherwise pulls sibling modules into the build and breaks
              # it. This module is self-contained and must stay that way, since the
              # whole point is that dev/docs-generator/ can be copied elsewhere.
              export GOWORK=off
              export PATH="$PWD/dev/docs-generator/bin:$PATH"

              # mise exports a global GOROOT (its own Go install) from the user's
              # profile. Inherited here it makes the flake's `go` drive a DIFFERENT
              # toolchain, which fails as:
              #   compile: version "go1.22.1" does not match go tool version "go1.26.7"
              # The flake's go finds its own GOROOT when the variable is absent, so
              # the fix is to drop the inherited one rather than pin it.
              unset GOROOT

              echo "⚗️  talos-homelab · talosctl $(talosctl version --client 2>/dev/null | awk '/Tag:/{print $2; exit}') · flux $(flux --version 2>/dev/null | awk '{print $3}') · $(python --version 2>&1) · go $(go version 2>/dev/null | awk '{print $3}' | sed 's/go//')"
            '';
          };
        }
      );
    };
}
