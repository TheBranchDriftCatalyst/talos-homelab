"""Registry + config for the telemetry test layer.

Audits Grafana dashboards panel-by-panel:
  - offline (structure): EVERY committed dashboard JSON is auto-discovered and checked (valid panels,
    resolvable datasource, non-empty queries). No hand-maintained list — drop a json in the dir and
    it's covered.
  - --live (each panel's query returns data, or is a justified EXPECTED_EMPTY): runs only for the
    curated LIVE_AUDIT set, because a per-panel data audit needs per-dashboard EXPECTED_EMPTY curation.
"""
import json
from collections import namedtuple
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]  # repo root: tests/telemetry/dashboards.py -> ../../
_JSON_DIR = _ROOT / "infrastructure/base/monitoring/grafana-dashboards/json"

# Dashboards are no longer all in one directory: colocating a dashboard with the component it
# visualises puts it at <component>/dashboard[s]/*.json. A single-root glob silently stopped
# covering those the moment colocation started -- and silence is the whole problem, because the
# suite stayed GREEN while covering none of them. honeypot-ops alone had 18 curated
# EXPECTED_EMPTY/LIVE_AUDIT entries in this file that could never execute, which reads as
# "audited" to anyone opening it.
#
# Globs, not a list: a hand-maintained list of auto-discovered things rots exactly like the
# hand-maintained list of links this repo's docs generator exists to kill.
_EXTRA_GLOBS = [
    "infrastructure/base/*/dashboard/*.json",
    "infrastructure/base/*/dashboards/*.json",
    "infrastructure/base/*/*/dashboard/*.json",
    "infrastructure/base/*/*/dashboards/*.json",
]


def _discover():
    """Auto-register every committed dashboard JSON -> (name, repo-relative path, uid). Automated so a
    new dashboard is smoke-tested the moment it lands, with no edit here."""
    out = []
    seen = set()
    paths = list(_JSON_DIR.glob("*.json"))
    for g in _EXTRA_GLOBS:
        paths.extend(_ROOT.glob(g))
    for p in sorted(paths):
        if p in seen:
            continue
        seen.add(p)
        try:
            uid = json.loads(p.read_text()).get("uid") or p.stem
        except Exception:
            uid = p.stem  # malformed JSON is caught by the offline structural test
        out.append((p.stem, str(p.relative_to(_ROOT)), uid))
    return out


# dashboards to audit: (name, repo json path, uid) — AUTO-DISCOVERED from the dashboard json/ dir
DASHBOARDS = _discover()

# Dashboards whose panels must return live DATA under --live (the deep audit). Everything else that's
# auto-discovered gets the offline structural check only: a live per-panel data audit needs curated
# EXPECTED_EMPTY allowlists per dashboard. Add a name here once its expected-empty panels are curated.
LIVE_AUDIT = {"honeypot-ops", "crowdsec-ops", "falco-ops"}

# datasource uid -> how the --live audit reaches it (namespace, service, port, query path, engine).
# INFERRED from the GrafanaDatasource CRs (spec.datasource.{uid,type,url}) so this map maintains itself:
# url http://<svc>.<ns>.svc[...][:port][/prefix] gives ns/service/port/prefix; type gives engine + the
# query path suffix (loki -> LogQL /loki/api/v1/query, prometheus -> PromQL /api/v1/query).
import urllib.parse as _urlparse  # noqa: E402

_DS_CR_DIRS = [
    "infrastructure/base/monitoring/grafana-datasources",
    "infrastructure/base/monitoring/v2-otel/grafana-datasources",
]
# datasource type -> (audit engine, query-path suffix appended to the URL's own path prefix)
_ENGINE_BY_TYPE = {"loki": ("loki", "/loki/api/v1/query"), "prometheus": ("prom", "/api/v1/query")}

# fallback if the CRs can't be parsed (e.g. PyYAML missing) — the audit still runs
_DATASOURCES_FALLBACK = {
    "loki-v2": dict(namespace="monitoring", service="loki", port=3100, path="/loki/api/v1/query", engine="loki"),
    "mimir":   dict(namespace="monitoring", service="mimir-gateway", port=80, path="/prometheus/api/v1/query", engine="prom"),
}


def _parse_ds_url(url):
    u = _urlparse.urlparse(url)
    labels = (u.hostname or "").split(".")
    svc = labels[0] if labels else (u.hostname or "")
    ns = labels[1] if len(labels) > 1 else "monitoring"
    port = u.port or (443 if u.scheme == "https" else 80)
    return ns, svc, port, (u.path or "").rstrip("/")


def _discover_datasources():
    try:
        import yaml
    except Exception:
        return dict(_DATASOURCES_FALLBACK)
    out = {}
    for rel in _DS_CR_DIRS:
        d = _ROOT / rel
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.yaml")):
            try:
                docs = list(yaml.safe_load_all(f.read_text()))
            except Exception:
                continue
            for doc in docs:
                if not doc or doc.get("kind") != "GrafanaDatasource":
                    continue
                ds = (doc.get("spec") or {}).get("datasource") or {}
                typ, url = ds.get("type"), ds.get("url")
                if typ not in _ENGINE_BY_TYPE or not url:
                    continue  # skip tempo/other engines the data-audit can't query
                key = ds.get("uid") or (ds.get("name") or "").lower()
                if not key:
                    continue
                ns, svc, port, prefix = _parse_ds_url(url)
                engine, suffix = _ENGINE_BY_TYPE[typ]
                out[key] = dict(namespace=ns, service=svc, port=port, path=prefix + suffix, engine=engine)
    return out or dict(_DATASOURCES_FALLBACK)


DATASOURCES = _discover_datasources()

Empty = namedtuple("Empty", "reason issue")

# Panels legitimately empty until a specific activity occurs. Each needs a reason + a TALOS- id, so
# "this panel shows nothing" is a reviewed decision, not a silent gap. The --live audit SKIPs these
# (rather than failing) but still reports them, so a real regression in a data-bearing panel is caught.
EXPECTED_EMPTY = {
    # cowrie recon-canary panels: fire only on the anti-honeypot fingerprinting pattern (SHELL_BEHAVIOR/
    # filter_output/===DONE===/uname/lspci), which is sporadic — not a broken query.
    # falcoctl auto-follow: legitimately empty, and worth contrasting with the breach panels
    # directly below. falcoctl polls `check every 168h0m0s` (7 days) and only logs "Found new
    # artifact version" / "Artifact correctly installed" when upstream ACTUALLY publishes, so
    # over any audit window the normal state is silence driven by an EXTERNAL, uncontrolled
    # event. Nothing in this cluster guarantees data.
    #
    # The breach panels below look superficially identical -- a security panel that is usually
    # quiet -- but are the opposite case: falco-tripwire-canary GUARANTEES traffic every 6h, so
    # silence there is a failure. "Usually empty" is not the test; "is something committed to
    # producing data" is.
    ("falco-ops", "Upstream ruleset changed (falcoctl auto-follow)"): Empty(
        "falcoctl polls upstream every 168h and logs only on a real publish -- no in-cluster "
        "actor produces this, so absence is the normal state, not a fault", "TALOS-slbn"),

    # claim(enforced) breach-panels-not-allowlisted: the falco breach panels are deliberately
    # absent from EXPECTED_EMPTY, so the live audit FAILS when they are empty
    #   j: test_every_curated_dashboard_is_actually_discovered
    #   f: someone re-adds an Empty() entry for a breach panel, or the canary stops firing and
    #      the audit is then made to tolerate it
    #   scope: path:tests/telemetry/dashboards.py

    # Falco honeypot-breach tripwires.
    #
    # EMPTY IS THE ALARM HERE, NOT HEALTH -- the opposite of what these entries used to say.
    # falco/falco-tripwire-canary (schedule `41 */6 * * *`) deliberately execs `getent passwd
    # root` into the cowrie container every 6h precisely BECAUSE getent is absent from
    # honeypot_expected_procs, so a working tripwire MUST fire ~4x/day. Measured 2026-09-19:
    # 13 Critical events in 24h (7 `6 init`, 6 `getent`), all at :41:01, all from the canary.
    #
    # So these panels going quiet means the CANARY died, i.e. the tripwire is no longer being
    # verified -- which is the exact condition the canary exists to detect. An allowlist saying
    # "empty = healthy" cannot express that, because Empty() is one-directional: it tolerates
    # emptiness and says nothing when data appears.
    #
    # Left OUT of EXPECTED_EMPTY on purpose: these panels should carry canary traffic, so the
    # live audit failing when they are empty is the correct behaviour. Do not "fix" a failure
    # here by re-adding an Empty() entry -- check whether the canary CronJob is still running.
    #
    # Corollary for whoever tunes the Falco rule: do NOT widen the startup exemption to cover
    # `getent` or `proc.pname = containerd-shim`. That suppresses the canary itself, and the
    # dashboard would then look healthy precisely because the verification stopped.
    # beelzebub is the 10% haproxy tier + freshly deployed, so its content panels are legitimately sparse
    # until it accumulates sessions. The attacker-IP panels are re-sourced to the haproxy beelzebub backend.
    ("honeypot-ops", "Sessions Over Time"): Empty(
        "0 in a quiet window — external cowrie sessions are sporadic", "TALOS-qish"),
    ("honeypot-ops", "Honeypot-Detection Attempts (24h)"): Empty(
        "0 until an anti-honeypot recon canary hits cowrie (SHELL_BEHAVIOR/filter_output) — sporadic", "TALOS-qish"),
    ("honeypot-ops", "Recon / Detection Commands (live)"): Empty(
        "0 until a recon command (uname/lspci/SHELL_BEHAVIOR) hits cowrie — sporadic", "TALOS-qish"),
    ("honeypot-ops", "[beelzebub] Captured Commands (live)"): Empty(
        "beelzebub is the 10% tier — content panels are sparse until it accumulates sessions", "TALOS-qish"),
    ("honeypot-ops", "[beelzebub] Login Attempts (success vs failed)"): Empty(
        "beelzebub is the 10% tier — content panels are sparse until it accumulates sessions", "TALOS-qish"),
    ("honeypot-ops", "[beelzebub] Sessions Over Time"): Empty(
        "beelzebub is the 10% tier — content panels are sparse until it accumulates sessions", "TALOS-qish"),
    ("honeypot-ops", "[beelzebub] Top Commands"): Empty(
        "beelzebub is the 10% tier — content panels are sparse until it accumulates sessions", "TALOS-qish"),
    ("honeypot-ops", "[beelzebub] Captured Credentials"): Empty(
        "beelzebub is the 10% tier — content panels are sparse until it accumulates sessions", "TALOS-qish"),
    ("honeypot-ops", "[beelzebub] Honeypot-Detection Attempts (24h)"): Empty(
        "beelzebub is the 10% tier — content panels are sparse until it accumulates sessions", "TALOS-qish"),
    ("honeypot-ops", "[beelzebub] Recon / Detection Commands (live)"): Empty(
        "beelzebub is the 10% tier — content panels are sparse until it accumulates sessions", "TALOS-qish"),
    ("honeypot-ops", "[beelzebub] Commands Captured"): Empty(
        "beelzebub is the 10% tier — content panels are sparse until it accumulates sessions", "TALOS-qish"),
    ("honeypot-ops", "[beelzebub] Login Attempts"): Empty(
        "beelzebub is the 10% tier — content panels are sparse until it accumulates sessions", "TALOS-qish"),
    ("honeypot-ops", "[beelzebub] Failed Logins"): Empty(
        "beelzebub is the 10% tier — content panels are sparse until it accumulates sessions", "TALOS-qish"),
    ("crowdsec-ops", "Local enforced decisions"): Empty(
        "0 when there are no active LOCAL (cscli/manual) decisions — scenario/CAPI bans surface in the other panels", "TALOS-pbn"),
    ("crowdsec-ops", "Active local decisions · expires at"): Empty(
        "0 when there are no active LOCAL (cscli/manual) decisions — scenario/CAPI bans surface in the other panels", "TALOS-pbn"),
    ("crowdsec-ops", "Time remaining · local decisions"): Empty(
        "0 when there are no active LOCAL (cscli/manual) decisions — scenario/CAPI bans surface in the other panels", "TALOS-pbn"),
    ("crowdsec-ops", "Inventory age"): Empty(
        "0 when there are no active LOCAL (cscli/manual) decisions — scenario/CAPI bans surface in the other panels", "TALOS-pbn"),
    ("crowdsec-ops", "Rows omitted by limit"): Empty(
        "0 when there are no active LOCAL (cscli/manual) decisions — scenario/CAPI bans surface in the other panels", "TALOS-pbn"),
    ("honeypot-ops", "Beelzebub hits (10%)"): Empty(
        "beelzebub is the 10% tier — 0 hits in a short window is normal", "TALOS-qish"),
    ("honeypot-ops", "[beelzebub] Distinct Recon Source IPs (24h)"): Empty(
        "beelzebub is the 10% tier — sparse in any window", "TALOS-qish"),
    ("crowdsec-ops", "AbuseIPDB Report Failures (24h)"): Empty(
        "0 = healthy (no report failures)", "TALOS-pbn"),
    ("crowdsec-ops", "CrowdSec warning / error logs"): Empty(
        "0 = healthy (no warn/error logs)", "TALOS-pbn"),
    ("crowdsec-ops", "AbuseIPDB Reporter Log"): Empty(
        "reporter is a daily CronJob — log panel is empty between runs", "TALOS-pbn"),
    ("crowdsec-ops", "IPs Reported to AbuseIPDB (24h)"): Empty(
        "reporter is a daily CronJob — populates on its run (fix just landed)", "TALOS-pbn"),
    ("honeypot-ops", "Failed Logins"): Empty(
        "cowrie accepts most creds, so failed logins are sporadic", "TALOS-qish"),
    # Same inversion as the falco-ops breach panels above: the canary makes this fire ~4x/day,
    # so empty means the canary stopped, not that the honeypot is safe. The panel TITLE ("should
    # ALWAYS be empty") is also wrong and is tracked separately.
}

# grafana dashboard-variable macros -> concrete values for a standalone query
MACROS = {
    "$__range": "1h", "[$__range]": "[1h]", "$__interval": "5m", "$__rate_interval": "5m",
    "$__auto": "5m",
}

# Panels whose $__range must be WIDER than the 1h default for the audit to mean anything.
#
# The breach panels are driven by falco-tripwire-canary on `41 */6 * * *`. Evaluated over 1h,
# a working canary is invisible 5 times out of 6, so "this panel has data" would fail
# constantly and the failure would be ignored -- the alert-fatigue outcome the canary exists to
# prevent, reproduced inside its own test. 24h spans four canary runs, so absence is real.
#
# Widen the WINDOW; never relax the expectation.
LIVE_RANGE_OVERRIDE = {
    ("falco-ops", "HONEYPOT BREACHES"): "24h",
    ("falco-ops", "HONEYPOT BREACH events (any = someone escaped the emulation)"): "24h",
    ("honeypot-ops",
     "HONEYPOT BREACH (Falco) — UNEXPLAINED execs (canary filtered out)"): "24h",
}
