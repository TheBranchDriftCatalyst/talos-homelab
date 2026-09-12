#!/usr/bin/env python3
"""Report Cowrie honeypot attackers to AbuseIPDB — policy-compliant (abuseipdb.com/reporting-policy).

Sources the LAST 24h of honeypot activity from Loki (not CrowdSec decisions) so each report carries a
detailed description (ports, creds tried, commands executed, timestamps). Reports ONLY IPs that
completed SSH/Telnet negotiation (client.version / login / command events) — never bare TCP connects —
so nothing spoofed/scan-only is ever reported (policy: TCP only if the 3-way handshake completed).
DRY_RUN=1 prints what it WOULD report and sends nothing.
"""
import collections
import datetime
import ipaddress
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

LOKI = os.environ.get("LOKI_URL", "http://loki.monitoring.svc:3100")
KEY = os.environ.get("ABUSEIPDB_API_KEY", "")
DRY = os.environ.get("DRY_RUN", "1") == "1"
WINDOW_H = int(os.environ.get("WINDOW_HOURS", "24"))
NS = os.environ.get("HONEYPOT_NS", "honeypot")

# handshake-completing events only — the policy's non-spoofed requirement
REAL = ("cowrie.client.version", "cowrie.login.failed", "cowrie.login.success", "cowrie.command.input")


def _clean(x):
    """Collapse all whitespace (incl. newlines in multi-line payloads) to single spaces."""
    return re.sub(r"\s+", " ", str(x)).strip()

now = datetime.datetime.now(datetime.timezone.utc)
start = now - datetime.timedelta(hours=WINDOW_H)
q = ('{namespace="%s", container="logship"} | json | src_ip!="" '
     '| eventid=~"cowrie.(login.success|login.failed|command.input|client.version)"' % NS)
url = LOKI + "/loki/api/v1/query_range?" + urllib.parse.urlencode({
    "query": q, "start": str(int(start.timestamp() * 1e9)), "end": str(int(now.timestamp() * 1e9)),
    "limit": "5000", "direction": "forward"})
try:
    data = json.loads(urllib.request.urlopen(url, timeout=30).read())
except Exception as e:
    print(f"FATAL: Loki query failed: {e}", file=sys.stderr); sys.exit(1)

agg = collections.defaultdict(lambda: {"ev": collections.Counter(), "creds": set(), "cmds": set(),
                                        "first": None, "last": None, "ports": set()})
for stream in data.get("data", {}).get("result", []):
    for ts, line in stream.get("values", []):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        ip = e.get("src_ip")
        if not ip:
            continue
        a = agg[ip]
        eid = e.get("eventid", "")
        a["ev"][eid] += 1
        t = datetime.datetime.fromtimestamp(int(ts) / 1e9, datetime.timezone.utc)
        a["first"] = t if a["first"] is None else min(a["first"], t)
        a["last"] = t if a["last"] is None else max(a["last"], t)
        if eid in ("cowrie.login.failed", "cowrie.login.success") and e.get("username") is not None:
            a["creds"].add(_clean(f'{e.get("username")}/{e.get("password", "")}')[:60])
        if eid == "cowrie.command.input" and e.get("input"):
            a["cmds"].add(_clean(str(e["input"]))[:80])
        if e.get("dst_port"):
            a["ports"].add(str(e["dst_port"]))

reported = skipped = 0
for ip, a in sorted(agg.items()):
    try:
        if ipaddress.ip_address(ip).is_private:
            skipped += 1; continue
    except ValueError:
        skipped += 1; continue
    if not any(a["ev"].get(k) for k in REAL):   # no completed handshake -> never report
        skipped += 1; continue
    cats = ["18", "22"]                          # Brute-Force, SSH
    if a["cmds"]:
        cats.append("15")                        # Hacking (executed commands in the fake shell)
    logins = a["ev"].get("cowrie.login.failed", 0) + a["ev"].get("cowrie.login.success", 0)
    parts = [f"Cowrie SSH/Telnet honeypot: {sum(a['ev'].values())} malicious events over {WINDOW_H}h."]
    if logins:
        parts.append(f"{logins} SSH/Telnet login attempts; creds tried: "
                     f"{', '.join(sorted(a['creds'])[:6]) or 'n/a'}.")
    if a["cmds"]:
        parts.append(f"Commands executed: {' | '.join(sorted(a['cmds'])[:6])}.")
    parts.append(f"Dest ports: {','.join(sorted(a['ports'])) or '2222/2223'}. "
                 f"First {a['first'].replace(microsecond=0).isoformat()}, "
                 f"last {a['last'].replace(microsecond=0).isoformat()} UTC.")
    comment = " ".join(parts)[:1024]
    ts = a["last"].replace(microsecond=0).isoformat()
    if DRY:
        print(f"WOULD REPORT {ip}  categories={','.join(cats)}  timestamp={ts}\n    {comment}")
        reported += 1; continue
    body = urllib.parse.urlencode({"ip": ip, "categories": ",".join(cats),
                                   "comment": comment, "timestamp": ts}).encode()
    req = urllib.request.Request("https://api.abuseipdb.com/api/v2/report", data=body,
                                 headers={"Key": KEY, "Accept": "application/json"})
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=30).read())
        print(f"reported {ip} -> abuseConfidenceScore={r.get('data', {}).get('abuseConfidenceScore')}")
        reported += 1
    except urllib.error.HTTPError as ex:
        print(f"report {ip} FAILED {ex.code}: {ex.read().decode()[:200]}", file=sys.stderr)
print(f"done: {'would report' if DRY else 'reported'} {reported} IP(s), skipped {skipped} "
      f"(private / connect-only / no-handshake)")
