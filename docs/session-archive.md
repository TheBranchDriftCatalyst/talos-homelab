# Session Archive — talos-homelab

Sessions rolled out of [`SESSION_STATUS.md`](../SESSION_STATUS.md) once the index exceeds its
retention window (last 10). Newest first. Nothing is deleted here.

Before an entry is archived, any durable lesson it taught is lifted into **Standing gotchas**
in the index — phrased as an invariant rather than as a story. So this file is the episodic
record; the index carries what that record _taught_.

---

## Archived sessions

### 2026-09-17/18 (overnight) — Flake + direnv migration, root cleanup

**Filed:** `TALOS-pmbi`, `TALOS-ewlf`, `TALOS-p4qu`, `TALOS-pmnc`, `TALOS-90pl`
**Closed:** `TALOS-hdw8`, `TALOS-9vtw`

Converted the repo to `use flake` + direnv; consolidated devx; moved Taskfiles under `dev/`;
1Password secret materialisation with biometric caching. Added the cowrie replay-bot
suppression scenario (`homelab/cowrie-replay-drop`), still in simulation.
