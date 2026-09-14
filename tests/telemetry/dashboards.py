"""Registry + config for the telemetry test layer.

Audits Grafana dashboards panel-by-panel: offline (structure) + --live (each panel's query returns
data, or is a justified EXPECTED_EMPTY). Add a dashboard by dropping its json path here.
"""
from collections import namedtuple

# dashboards to audit: (name, repo json path, uid)
# TODO: have this also run into automatic mode, i bet we can just inquire with the cluster
# and get all of thesee dashboards automatically. any crd
DASHBOARDS = [
    ("honeypot-ops", "infrastructure/base/monitoring/grafana-dashboards/json/honeypot-ops.json", "honeypot-ops"),
    ("crowdsec-ops", "infrastructure/base/monitoring/grafana-dashboards/json/crowdsec-ops.json", "crowdsec-ops"),
    ("falco-ops", "infrastructure/base/monitoring/grafana-dashboards/json/falco-ops.json", "falco-ops"),
]

# datasource uid -> how the --live audit reaches it (svc, port, query path, engine)
# loki uses the LogQL query endpoint; prometheus/mimir use the promql query endpoint.
DATASOURCES = {
    "loki-v2": dict(namespace="monitoring", service="loki", port=3100,
                    path="/loki/api/v1/query", engine="loki"),
    "loki":    dict(namespace="monitoring", service="loki", port=3100,
                    path="/loki/api/v1/query", engine="loki"),
    "mimir":   dict(namespace="monitoring", service="mimir-gateway", port=80,
                    path="/prometheus/api/v1/query", engine="prom"),
}

Empty = namedtuple("Empty", "reason issue")

# Panels legitimately empty until a specific activity occurs. Each needs a reason + a TALOS- id, so
# "this panel shows nothing" is a reviewed decision, not a silent gap. The --live audit SKIPs these
# (rather than failing) but still reports them, so a real regression in a data-bearing panel is caught.
EXPECTED_EMPTY = {
    # cowrie recon-canary panels: fire only on the anti-honeypot fingerprinting pattern (SHELL_BEHAVIOR/
    # filter_output/===DONE===/uname/lspci), which is sporadic — not a broken query.
    # Falco honeypot-breach tripwires — empty = healthy (nobody escaped the emulation into the container).
    ("falco-ops", "HONEYPOT BREACHES"): Empty(
        "by design — Falco breach tripwire; non-empty only if an attacker escapes into the container. Empty = healthy.", "TALOS-slbn"),
    ("falco-ops", "HONEYPOT BREACH events (any = someone escaped the emulation)"): Empty(
        "by design — Falco breach tripwire; non-empty only on a real container escape. Empty = healthy.", "TALOS-slbn"),
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
    ("honeypot-ops", "HONEYPOT BREACH (Falco) — should ALWAYS be empty"): Empty(
        "by design — Falco breach tripwire; empty = healthy (nobody escaped the emulation)", "TALOS-slbn"),
}

# grafana dashboard-variable macros -> concrete values for a standalone query
MACROS = {
    "$__range": "1h", "[$__range]": "[1h]", "$__interval": "5m", "$__rate_interval": "5m",
    "$__auto": "5m",
}
