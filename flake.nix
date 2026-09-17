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

              # ── Node ───────────────────────────────────────────────────
              # TODO(TALOS-hurz): drop both once package.json/yarn.lock are
              # gone. Still load-bearing: Taskfile.dev.yaml shells out to
              # `yarn lint`/`yarn format` and lefthook.yaml runs `npx`.
              nodejs_22
              yarn

              # ── Shell tooling used by scripts/ ─────────────────────────
              jq
              gum # scripts/namespace-dashboard.sh

              # ── Python ─────────────────────────────────────────────────
              # uv is REQUIRED, not optional: scripts/upgrade-talos.py is a
              # PEP-723 script whose shebang is `env -S uv run --quiet`, and
              # `task talos:upgrade` (Taskfile.talos.yaml:251) invokes it.
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
              echo "⚗️  talos-homelab · talosctl $(talosctl version --client 2>/dev/null | awk '/Tag:/{print $2; exit}') · flux $(flux --version 2>/dev/null | awk '{print $3}') · $(python --version 2>&1)"
            '';
          };
        }
      );
    };
}
