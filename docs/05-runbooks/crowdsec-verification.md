# CrowdSec verification and dashboard

The consolidated dashboard is [Security Ops — CrowdSec](http://grafana.talos00/d/crowdsec-ops).
Its header links to [local decisions](https://crowdsec.talos00/decisions),
[local alerts](https://crowdsec.talos00/alerts), and the [CrowdSec Console](https://app.crowdsec.net/).
IP cells link to CrowdSec IP intelligence.

## Interpret the dashboard

- **Local enforced decisions** excludes simulation and community lists. A decision can cover an IP, range, or another scope; this is not a unique-attacker count.
- **Community / imported bans** can be nonzero while local decisions are zero. Shared LAPI database gauges use `max` across replicas before summing, preventing HA double-counting.
- **Scenario triggers** include simulation. An overflow is not proof of a ban or a blocked request.
- **Active local decisions** shows IP/scope, reason, origin, action, ID, expiry and time remaining. These are current snapshots regardless of the dashboard time range.
- **Decision inventory** must say CURRENT before interpreting an empty table as no local decisions. Failed reads discard stale rows and raise a monitoring alert after five minutes.
- The observer polls every 30 seconds; the scrape interval is another 30 seconds. It exports the newest 1,000 local/manual decisions and shows how many rows were omitted. Community IP labels are excluded. Per-IP data is retained under the existing Mimir retention policy.
- **Decision history** records when the observer saw a decision or saw it disappear, not exact issuance or enforcement time. `snapshot` means the decision existed when the observer started. History begins when this observer was deployed; it cannot reconstruct earlier bans.
- **Traefik polling** proves bouncer connectivity. Use the external test below to prove blocking. AppSec blocked-request counts are separate from IP-decision blocks.

The observer uses only the read-only bouncer API, has no Kubernetes API access, and is independent of enforcement. Its endpoint has no public route and ingress is limited to monitoring namespaces. The existing Traefik bouncer key is mounted read-only; Grafana never receives it.

## Unified security posture suite

```sh
# Repository contracts; live checks explicitly report SKIPPED.
python3 scripts/security/test_security_posture.py

# Also assert the running system. Missing evidence fails; it is never a pass.
python3 scripts/security/test_security_posture.py --live
```

Requires Python 3 and PyYAML (`python3 -m pip install PyYAML==6.0.2`). The GitHub
`security posture` workflow runs offline contracts on relevant pull requests and
main-branch pushes without cluster credentials.

The suite explicitly checks that sensitive access-log headers, honeypot/tarpit
API-token projections, unbounded fail-open configuration, single-replica HA,
wrong-host telemetry exceptions and the invalid exporter User-Agent are **not
present**. Positive assertions require preserved CrowdSec log fields, current
inventory data, full agent coverage and successful native AppSec configuration
validation. Boolean host/path regression cases cover the supported expression
subset; native compilation is a separate live assertion.

Live mode sends one registry GET containing **synthetic** cookie/authorization/API
key headers and correlates the retained unique User-Agent with its actual Traefik
access log. It fails if no matching log is found, if secret header fields are
present, or if required parser fields are missing. It reads pod volume projections
and token-mount configuration; this is not an exploit test for arbitrary files
inside a compromised process.

Parser fixtures use separate public test IPs to avoid coupling through the
scenario's blackhole timer. Fixtures run in a temporary copy of engine config and
do not post alerts to LAPI. Live mode does not change login, allowlists, simulation
or production configuration. VPN bans and replica replacement require the separate
`check-crowdsec-vpn.py --ha` command above.

## Repeatable checks

From the repository root, with Python 3, PyYAML and the intended kubectl context:

```sh
python3 scripts/security/check-crowdsec-registration.py
python3 scripts/security/check-crowdsec-parsers.py
python3 scripts/security/test-crowdsec-decision-exporter.py
python3 scripts/security/check-crowdsec-vpn.py --report .output/crowdsec-vpn-test.json
```

The VPN test creates a disposable Gluetun canary from the existing VPN test template. It refuses to use a canary credential already referenced by a running pod and requires manual-decision sharing to be disabled. It verifies an independent public IPv4 exit and a public destination, then tests:

1. The protected registry `/v2/` responds with HTTP 401 (or 200 for a custom endpoint).
2. A uniquely named, five-minute manual CrowdSec ban changes the response to HTTP 403.
3. Removing only that test decision restores the original response.
4. The test deletes its own canary, including on failure or interruption. The decision TTL provides a backstop if cleanup loses cluster access.

Use `--url https://YOUR-OWN-PROTECTED-HOST/path` for another stable owned endpoint. Redirects, VPN exit changes, destination address changes, pre-existing enforced decisions, and private destinations fail the test. Do not point it at a route that triggers an automatic attack scenario: the test is intentionally a manual local decision, not a community attack report. It does not disable simulation, alter allowlists, reconfigure production VPN workloads, or change login settings.

Add `--ha` to use a ten-minute test decision and replace one Ready LAPI replica
while verifying HTTP 403, then one AppSec replica after unban while verifying the
normal response. Each replacement requires two Ready replicas on separate nodes;
the test waits for redundancy to recover. All runs also try forged X-Forwarded-For,
X-Real-IP and CF-Connecting-IP headers while banned.

A passing HTTP test does **not** prove public Cowrie reachability, Cowrie-to-decision creation over WAN, coverage of every ingress node, or enforcement during a complete security-service outage. The HA option samples one-replica replacement; it does not test database promotion or a complete node outage. Cowrie's parser/scenario tests cover event processing separately; public router forwarding is staged in [the Cowrie exposure runbook](cowrie-public-exposure.md).

## Verified on 2026-09-07

The isolated VPN exit `45.128.133.219` reached the public registry origin. Responses were **401 → 403 → 401** across baseline, manual ban, and scoped removal. Blocking was observed roughly 34 seconds after baseline and recovery about 51 seconds after removal, consistent with stream polling. Both test resources were cleaned up.

Earlier audit findings repaired in this session: a node-reboot registration collision stranded an agent; Cowrie's parser whitelist prevented metadata extraction; file-watch settings missed container log rotation. Registration recovery and ten parser fixtures passed after repair. LAPI and AppSec each run two replicas on separate nodes with disruption budgets; the bouncer now has bounded failures and startup blocking. A one-replica replacement test preserved trusted HTTP availability. This is evidence of recovery, not a guarantee against all outages.
