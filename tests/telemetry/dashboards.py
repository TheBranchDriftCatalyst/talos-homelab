"""Registry + config for the telemetry test layer.

Audits Grafana dashboards panel-by-panel: offline (structure) + --live (each panel's query returns
data, or is a justified EXPECTED_EMPTY). Add a dashboard by dropping its json path here.
"""
from collections import namedtuple

# dashboards to audit: (name, repo json path, uid)
DASHBOARDS = [
    ("cowrie-ops", "infrastructure/base/monitoring/grafana-dashboards/json/cowrie-ops.json", "cowrie-ops"),
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
    ("cowrie-ops", "Failed Logins"): Empty(
        "0 until a real SSH brute-force attempt hits the honeypot (cowrie accepts most creds, so most "
        "sessions log success not failure)", "TALOS-a8vo"),
}

# grafana dashboard-variable macros -> concrete values for a standalone query
MACROS = {
    "$__range": "1h", "[$__range]": "[1h]", "$__interval": "5m", "$__rate_interval": "5m",
    "$__auto": "5m",
}
