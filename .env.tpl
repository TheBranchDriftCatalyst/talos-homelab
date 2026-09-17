# Secret REFERENCES only — safe to commit. Values live in 1Password.
# Dev-side analog of an ExternalSecret manifest: declare what this repo needs;
# `use_onepassword` (direnv, from home-manager) materializes them as env vars.
#
# NOTE: op inject templates COMMENTS too — never write a literal
# scheme-prefixed example here. Convention (scheme omitted on purpose):
#   catalyst-eso/<repo-name>/<kebab-field>     per-project secret
#   catalyst-eso/<item>/<kebab-field>          shared / pre-existing item
#
# catalyst-eso is THE cluster ESO vault — the same one the ClusterSecretStore
# reads (infrastructure/base/external-secrets/secretstores/onepassword-secretstore.yaml:20),
# so laptop and cluster consume identical items.
# vault ≙ ClusterSecretStore · item ≙ ExternalSecret · field ≙ key
#
# ⚠️ op inject is ALL-OR-NOTHING: one unresolvable reference fails the whole
# render and NOTHING is exported. Verify each line with `op read` before
# committing a change here. .env.local (gitignored) overrides anything below.

# Bootstrap credential for 1Password Connect itself, consumed by
# `task infra:setup-1password` (dev/Taskfile.infra.yaml:63,68-74,90). Chicken-and-egg
# by design: this is the one secret that cannot come from the cluster's own ESO
# store, because it is the credential that store authenticates with.
#
# Addressed by UUID, not title, on purpose. The item is titled
# "catalyst-eso Access Token: external secrets operator" and the colon in that
# title breaks secret-reference parsing — `op read` fails on the title form and
# succeeds on the UUID. Verified byte-identical to the value this repo used
# before the migration (sha256 prefix 6e300120257c0d96).
OP_CONNECT_TOKEN="op://catalyst-eso/xj7nhudu7253e2pionyywuunji/credential"

# No in-repo consumer today — carried over from the pre-flake .envrc so the
# reference survives the migration. Drop these three if the LiteLLM / OpenClaw
# work ends up entirely in-cluster via ExternalSecret.
LITELLM_MASTER_KEY="op://catalyst-eso/litellm/master-key"
LITELLM_SALT_KEY="op://catalyst-eso/litellm/salt-key"
OPENCLAW_GATEWAY_TOKEN="op://catalyst-eso/openclaw/gateway-token"
