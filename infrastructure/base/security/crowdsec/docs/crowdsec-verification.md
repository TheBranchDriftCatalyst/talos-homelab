---
type: runbook
status: current
covers:
  - crowdsec
freshness: tracks-code
tickets:
  - TALOS-y5sx
blurb: How to prove CrowdSec is actually blocking, and how to read its dashboards without fooling yourself into thinking it is.
---

# CrowdSec verification and dashboards

Most of what a CrowdSec dashboard shows is not evidence of enforcement. Simulated overflows
look like triggers, community blocklists look like local decisions, and a bouncer polling
happily proves connectivity rather than blocking. This runbook separates the readings that
mean something from the ones that do not, and gives the end-to-end test that settles it.

## TL;DR

- **A scenario trigger is not a ban.** Trigger panels include simulated overflows.
- **A decision is not enforcement.** Simulated decisions are skipped by both bouncers.
- **Bouncer polling is not blocking.** It proves connectivity; only a request from outside
  proves a block.
- The only conclusive check is the VPN test below: it bans a throwaway exit address, watches
  a protected endpoint change response, and unbans.
- The decision observer is **independent of enforcement** by design. If it is down, the
  tables are unknown — not empty.

## Reading the dashboard

The consolidated dashboard is [Security Ops — CrowdSec](http://grafana.talos00/d/crowdsec-ops).
Its header links to [local decisions](https://crowdsec.talos00/decisions),
[local alerts](https://crowdsec.talos00/alerts) and the
[CrowdSec Console](https://app.crowdsec.net/); IP cells link to CrowdSec's IP intelligence.

- **Local enforced decisions** excludes simulation and community lists. A decision can cover
  an address, a range or another scope, so this is not a count of unique attackers.
- **Community / imported bans** can be non-zero while local decisions are zero. Shared
  database gauges take a `max` across replicas before summing, which is what stops a
  highly-available LAPI from double-counting itself.
- **Scenario triggers** include simulation. An overflow is not proof of a ban or of a blocked
  request.
- **Active local decisions** shows scope, reason, origin, action, ID and expiry. These are
  current snapshots regardless of the dashboard's time range.
- **Decision inventory** must say `CURRENT` before you read an empty table as "no local
  decisions". A failed read discards stale rows and raises a monitoring alert rather than
  showing you something plausible and wrong.
- **Decision history** records when the observer _saw_ a decision appear or disappear, not
  when it was issued or enforced. `snapshot` means the decision already existed when the
  observer started, and history cannot reconstruct anything from before the observer was
  deployed.
- **Traefik polling** proves bouncer connectivity only. AppSec blocked-request counts are a
  separate thing from IP-decision blocks.

The observer polls on a short interval and the scrape adds another, so expect the tables to
lag reality by under a minute. It exports the newest local and manual decisions up to a cap
and reports how many rows it omitted; community-list entries are excluded deliberately,
because they are bulk and historical and belong in the metrics store rather than in a table.

**The observer is not part of enforcement.** It holds a read-only bouncer credential of its
own, has no Kubernetes API access, and has no public route — see
[README.md](../README.md#observability-is-deliberately-not-enforcement) for why that separation
matters.

## The posture suite

Run inside the dev shell, which provides Python and PyYAML.

```sh
task test:security                          # every co-located security-posture suite
python3 tests/security-posture/test_security_posture.py          # contracts only
python3 tests/security-posture/test_security_posture.py --live   # also assert the running system
```

Offline mode checks repository contracts and reports live checks as **SKIPPED** — never as
passes. The GitHub `security posture` workflow runs the offline half on relevant pull requests
and main-branch pushes, without cluster credentials.

The suite is built around negative assertions as much as positive ones: it checks that
sensitive access-log headers, honeypot and tarpit API-token projections, unbounded fail-open
configuration, single-replica high availability and wrong-host telemetry exceptions are **not
present**. Positive assertions cover preserved CrowdSec log fields, current inventory data,
full agent coverage, and successful native AppSec configuration validation.

Live mode sends a single request carrying **synthetic** credential-shaped headers and then
correlates its unique user agent against the actual Traefik access log. It fails if no
matching log line is found, if secret header fields survived into the log, or if required
parser fields are missing. It reads pod volume projections and token-mount configuration; it
is not an exploit test for arbitrary file access inside a compromised process. Parser fixtures
use separate public test addresses so they do not couple through a scenario's blackhole timer,
and they run against a temporary copy of the engine config so they never post alerts to the
LAPI. Live mode changes no login, allowlist, simulation or production configuration.

## Repeatable checks

From the repository root, with the intended kubectl context:

```sh
python3 tests/security-posture/check-crowdsec-registration.py
python3 tests/security-posture/check-crowdsec-parsers.py
python3 tests/security-posture/test-crowdsec-decision-exporter.py
python3 tests/security-posture/check-crowdsec-vpn.py --report .output/crowdsec-vpn-test.json
```

## The end-to-end enforcement test

This is the one that proves blocking. It creates a disposable VPN canary from the existing
VPN test template, refuses to use a canary credential already referenced by a running pod, and
requires manual-decision sharing to be disabled — a test ban must never be reported to the
community feed. It verifies it has an independent public exit and a public destination, then:

1. The protected endpoint responds normally.
2. A uniquely named, short-lived manual ban changes that response to a blocked one.
3. Removing **only that decision** restores the original response.
4. The canary deletes itself, including on failure or interruption. The decision's own expiry
   is the backstop if cleanup loses cluster access.

Use `--url https://YOUR-OWN-PROTECTED-HOST/path` for another stable endpoint you own.
Redirects, VPN exit changes, unexpected destination addresses, pre-existing enforced decisions
and private destinations all fail the test. After the first successful resolution it pins the
destination addresses with `curl --resolve` while keeping certificate validation, which
isolates the enforcement check from intermittent VPN DNS failures — it does not test DNS
availability.

**Do not point it at a route that trips an automatic attack scenario.** The test is
deliberately a manual local decision, not a community attack report.

Add `--ha` to use a slightly longer test decision and replace one ready LAPI replica while
verifying the blocked response, then one AppSec replica after unbanning while verifying the
normal response. Each replacement requires two ready replicas on separate nodes, and the test
waits for redundancy to recover. All runs also attempt forged forwarded-for headers while
banned.

### What a pass does not prove

A passing HTTP test does **not** prove public honeypot reachability, honeypot-to-decision
creation over the WAN, coverage of every ingress node, or enforcement during a complete
security-service outage. The `--ha` option samples one-replica replacement; it does not test
database promotion or a whole-node outage. Honeypot event processing is covered separately by
its own parser and scenario tests, and public forwarding is staged in
[the honeypot exposure runbook](../../honeypots/docs/cowrie-public-exposure.md).

## Reference run

The full end-to-end test was run against an isolated VPN exit on 2026-09-07. Responses moved
normal → blocked → normal across baseline, manual ban and scoped removal. Blocking was
observed roughly 34 seconds after baseline and recovery about 51 seconds after removal, which
is consistent with the bouncer's stream polling interval — **that timing is what "working"
looks like**, so a run that blocks instantly or takes several minutes is worth investigating
rather than accepting. Both test resources were cleaned up.

The audit that produced that run, including the defects it found and repaired, was written up
as `docs/_archive/05-runbooks/crowdsec-audit-2026-09-07.md`; that file has since been removed
from the tree and now exists only in git history. It was evidence of recovery from specific
faults, not a guarantee against all outages.

## Related Issues

- TALOS-y5sx — decision-observer scope and the inventory table's failure semantics
