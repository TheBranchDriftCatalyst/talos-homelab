"""Registry + config for the telemetry test layer.

Audits Grafana dashboards panel-by-panel: offline (structure) + --live (each panel's query returns
data, or is a justified EXPECTED_EMPTY). Add a dashboard by dropping its json path here.
"""
from collections import namedtuple

# dashboards to audit: (name, repo json path, uid)
DASHBOARDS = [
    ("cowrie-ops", "infrastructure/base/monitoring/grafana-dashboards/json/cowrie-ops.json", "cowrie-ops"),
    ("beelzebub-ops", "infrastructure/base/monitoring/grafana-dashboards/json/beelzebub-ops.json", "beelzebub-ops"),
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
    ("cowrie-ops", "HONEYPOT BREACH (Falco) — should ALWAYS be empty"): Empty(
        "by design — Falco breach tripwire; populated only if an attacker escapes the emulation into "
        "the container. Empty = healthy.", "TALOS-slbn"),
    ("cowrie-ops", "Login Attempts (success vs failed)"): Empty(
        "0 in a quiet window — external SSH login activity on the public honeypot is sporadic", "TALOS-a8vo"),
    ("cowrie-ops", "Sessions Over Time"): Empty(
        "0 in a quiet window — external (non-pod-CIDR) sessions are sporadic", "TALOS-a8vo"),
    ("cowrie-ops", "Failed Logins"): Empty(
        "0 until a real SSH brute-force attempt hits the honeypot (cowrie accepts most creds, so most "
        "sessions log success not failure)", "TALOS-a8vo"),
    # cowrie recon-canary panels: fire only on the anti-honeypot fingerprinting pattern (SHELL_BEHAVIOR/
    # filter_output/===DONE===/uname/lspci), which is sporadic — not a broken query.
    ("cowrie-ops", "Honeypot-Detection Attempts (24h)"): Empty(
        "0 until an anti-honeypot recon canary hits cowrie (SHELL_BEHAVIOR/filter_output/===DONE===) — sporadic", "TALOS-qish"),
    ("cowrie-ops", "Recon / Detection Commands (live)"): Empty(
        "0 until a recon command (uname/lspci/SHELL_BEHAVIOR) hits cowrie — sporadic", "TALOS-qish"),
    # Falco honeypot-breach tripwires — empty = healthy (nobody escaped the emulation into the container).
    ("falco-ops", "HONEYPOT BREACHES"): Empty(
        "by design — Falco breach tripwire; non-empty only if an attacker escapes into the container. Empty = healthy.", "TALOS-slbn"),
    ("falco-ops", "HONEYPOT BREACH events (any = someone escaped the emulation)"): Empty(
        "by design — Falco breach tripwire; non-empty only on a real container escape. Empty = healthy.", "TALOS-slbn"),
    # beelzebub is the 10% haproxy tier + freshly deployed, so its content panels are legitimately sparse
    # until it accumulates sessions. The attacker-IP panels are re-sourced to the haproxy beelzebub backend.
    ("beelzebub-ops", "Commands Captured"): Empty(
        "few captured commands until attackers land on the 10% tier", "TALOS-qish"),
    ("beelzebub-ops", "Failed Logins"): Empty(
        "beelzebub accepts creds like cowrie; failed logins are rare + it is the 10% tier", "TALOS-qish"),
    ("beelzebub-ops", "Captured Commands (live)"): Empty(
        "sparse commands until the 10% tier accumulates sessions", "TALOS-qish"),
    ("beelzebub-ops", "Captured Credentials"): Empty(
        "sparse credential captures until the 10% tier accumulates sessions", "TALOS-qish"),
    ("beelzebub-ops", "Recon / Detection Commands (live)"): Empty(
        "0 until an anti-honeypot recon canary hits beelzebub (10% tier) — sporadic", "TALOS-qish"),
    ("beelzebub-ops", "Login Attempts"): Empty(
        "beelzebub is the 10% tier — sparse login events in any short window", "TALOS-qish"),
    ("beelzebub-ops", "Login Attempts (success vs failed)"): Empty(
        "beelzebub is the 10% tier — sparse login events in any short window", "TALOS-qish"),
    ("beelzebub-ops", "Sessions Over Time"): Empty(
        "beelzebub is the 10% tier — sparse sessions in any short window", "TALOS-qish"),
    ("beelzebub-ops", "Top Commands"): Empty(
        "beelzebub is the 10% tier — sparse commands in any short window", "TALOS-qish"),
    ("beelzebub-ops", "Honeypot-Detection Attempts (24h)"): Empty(
        "0 until an anti-honeypot recon canary hits beelzebub (10% tier) — sporadic", "TALOS-qish"),
}

# grafana dashboard-variable macros -> concrete values for a standalone query
MACROS = {
    "$__range": "1h", "[$__range]": "[1h]", "$__interval": "5m", "$__rate_interval": "5m",
    "$__auto": "5m",
}
