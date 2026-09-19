---
type: architecture
status: current
covers:
  - falco
freshness: tracks-code
tickets:
  - TALOS-slbn
  - TALOS-vy8s
  - TALOS-cscw
blurb: Syscall-level runtime detection. Why the driver, the container engine and the alert routing are configured the way they are, and why a canary exercises the honeypot rules.
---

# Falco — runtime detection

Falco watches syscalls on every node. It is the only thing in this cluster that can see a
process execute; Hubble sees packets, and the CrowdSec agent sees logs. Its most important
job is the honeypot breach tripwire — proving that nobody has escaped the emulated shells
described in [../honeypots/README.md](../honeypots/README.md).

## TL;DR

- Modern eBPF driver, because Talos is immutable and cannot build kernel modules.
- Falco can run **fully healthy while detecting nothing**. Three settings here have that
  failure mode, and each is annotated in `helmrelease.yaml`.
- Our rules are in git. The **upstream base ruleset is not** — that is deliberate, and made
  attributable rather than silent.
- Discord carries **CRITICAL only**, on purpose. A noisy channel gets muted, and a muted
  channel is not an alerting path.
- The breach rules are exercised every few hours by a canary, because a rule nobody triggers
  is a belief rather than a control.

## The failure mode to design against

Every hard-won setting in `helmrelease.yaml` protects against the same shape: **Falco keeps
running, the pod stays Ready, events keep flowing, and the rules you care about cannot
match.** Pod health and event counts cannot detect any of it.

| Setting                                   | What goes wrong                                                                       | How to check                                                                |
| ----------------------------------------- | ------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| Capability set (in place of `privileged`) | A missing capability makes the probe fail to load                                     | Event counts **per hostname**, not pod readiness                            |
| `cri` collector enabled                   | Kubernetes metadata stops resolving, so every namespace-scoped rule stops matching    | Sample `output_fields`; confirm **both** `k8s.ns.name` and `container.name` |
| Native `containerd` collector disabled    | Two engines race for the container cache; the winner differs per node and per restart | Check **per node**, preferring the node the honeypot runs on                |

`container.name` resolving to a hex container ID is the broken state for the last two. It is
not null, so a null check passes straight over it — verify the value, not its presence.

If detection stops after a change to the security context, revert that change first.

## Rule provenance

Detections come from two places and only one of them is version-controlled:

- **Our rules** — the honeypot breach rules and the upstream-rule exceptions — live in
  `customRules` in the HelmRelease. They are in git, reviewed, and revertible.
- **The upstream base ruleset** is fetched and followed by the chart's falcoctl sidecar at
  runtime. It is not pinned here and we configure nothing about it.

That is a deliberate trade, not an oversight: rules are threat detection, and pinning them
means detections go stale until a human remembers to bump. The cost is that detection
behaviour can change underneath you — and since CRITICAL routes to Discord, that includes
what wakes you up.

So the change is made **attributable** instead of invisible. The `falco-ops` dashboard
carries a rule-provenance row built from the falcoctl container's own log stream, showing
when the upstream ruleset actually moved. If Falco suddenly starts paging with a new false
positive, or a detection you relied on goes quiet, look there first. Empty is the normal
state.

There is no _alert_ on that panel, only the panel. Alerting on it needs a log-based rule,
and every working alert in this cluster is `PrometheusRule → Mimir → Alertmanager`, which
cannot query logs.

## Why CRITICAL only reaches a human

Routing everything at `notice` to Discord would put a large, continuous false-positive stream
into the channel that carries "something escaped the honeypot". A channel that noisy gets
muted within a day, and then the tripwire might as well not exist. Loki keeps the
full-fidelity record for investigation; Discord carries only the breaches.

The same reasoning drives the two upstream-rule exceptions in `customRules`. Both are matched
on **identity** — an exact executable path, a specific CronJob — rather than on something
broad like an entire namespace, so they suppress the two known-benign sources without
widening the rule. Use `override: {condition: append}` and never the deprecated bare
`append:` key; a deprecated key on a security rule is exactly the thing that stops working on
a chart bump and takes the exception with it silently.

## The honeypot breach rules

Cowrie and Beelzebub emulate a shell _in-process_, so an ordinary attacker session executes
nothing. A real process exec inside one of those containers therefore means someone left the
emulation and reached the actual container.

Two design choices in `customRules` are load-bearing:

- **Allowlist the emulator containers rather than blocklist the infrastructure ones.** The
  honeypot namespace also runs a proxy, a log sidecar, a backup job and an init container,
  all of which legitimately exec. Blocklisting them is whack-a-mole; naming the two emulators
  is closed.
- **Exempt only the container's own PID 1 at startup.** Without that clause the rule fires
  CRITICAL on every pod restart, because a container's init is spawned by runc and is not in
  the expected-process list. The exemption is scoped to PID 1 specifically, because
  `kubectl exec` into an emulator is parented by runc too — and that _is_ worth alerting on.

## The canary

`tripwire-canary.yaml` executes a deliberately non-allowlisted binary inside the live cowrie
container on a schedule, and `../honeypots/tripwire-alert.yaml` alerts when that stops
producing events. It exercises the whole path — kernel probe, rule match, falcosidekick,
metric — so a break in any hop surfaces as a firing alert rather than as silence.

It exists because these rules went blind three times in a single day while the configuration
looked correct and every pod stayed Ready. The only thing that caught it was a human running
a command by hand and noticing nothing fired.

**The canary's ServiceAccount and CronJob live in this namespace, not in `honeypot`.** The
honeypot namespace is under a strict egress quarantine and cannot reach the apiserver — the
first version of this job died proving it. Widening that quarantine to make a test convenient
would weaken containment on the namespace most likely to be compromised. Only the Role and
RoleBinding live in `../honeypots/`, which is what keeps the exec permission scoped to that
namespace; a RoleBinding grants solely within its own namespace regardless of where the
subject lives.

The split across two directories is also forced: each kustomization sets `namespace:`, and
that transformer silently rewrites any namespace set in a manifest, so a CronJob placed in
the honeypot directory renders into the wrong namespace with no error at all.

## The two network policies are the access control

- `core-network-policy.yaml` — the falcosidekick event intake has **no authentication**.
  Without this policy, any pod could POST arbitrary "Falco events": enough forged noise to
  get the Discord channel muted, or to bury a real breach. The same port also serves
  `/metrics`, so the policy must admit both the agents and the metrics scraper — admitting
  only one silently breaks the other, and a scrape target that quietly reads zero on a
  security dashboard is indistinguishable from "nothing is happening".
- `webui-network-policy.yaml` — the UI's own credential prompt is switched off so that SSO is
  one login rather than two. That makes this policy **the only in-cluster control** on the UI.
  Deleting it, or letting its selector drift off the UI pods, opens the UI to every pod in the
  cluster with nothing behind it.

The UI credential secret is kept wired even though the app currently ignores it. The app
falls back to a well-known default credential whenever that variable is _absent_, so removing
it would make a future re-enable land on the default instead of on the real secret.

The UI's event store is redis-stack rather than a drop-in replacement, because the UI writes
through a deprecated RediSearch API that the alternative never implemented: the schema
commands all succeeded and every write returned an error, so the index existed and the UI
stayed empty. Test the write path, not the schema.

## Related Issues

- TALOS-slbn — deploy Falco for syscall-level runtime detection
- TALOS-vy8s — route CRITICAL Falco alerts to a human
- TALOS-cscw — least-privilege pass: capabilities in place of `privileged`, collector pruning
