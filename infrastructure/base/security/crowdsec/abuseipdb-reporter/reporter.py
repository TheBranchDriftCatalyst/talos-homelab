#!/usr/bin/env python3
"""Report Cowrie honeypot attackers to AbuseIPDB — policy-compliant (abuseipdb.com/reporting-policy).

Sources the LAST 24h of honeypot activity from ClickHouse (ClickStack), not CrowdSec decisions, so each
report carries a detailed description (ports, creds tried, commands executed, timestamps). Reports ONLY
IPs that completed SSH/Telnet negotiation (client.version / login / command events) — never bare TCP
connects — so nothing spoofed/scan-only is ever reported (policy: TCP only if the 3-way handshake
completed). DRY_RUN=1 prints what it WOULD report and sends nothing.

WAS LOKI, NOW CLICKHOUSE (TALOS-suxd.3). Cowrie's events reach both stores the same way — the logship
sidecar's stdout, collected by Alloy — so this is a read-path swap, not a change of source data.

THE SWAP FIXED A LIVE BUG. The Loki query passed limit=5000 with direction=forward, which returns the
5000 OLDEST matching lines, not a sample of the window. Measured on one real 24h window: 17,980
handshake events existed, the first 5000 of them ended at 17:24 — roughly six hours in — and covered
59 of the 122 attacker IPs. So this job had been silently reporting under half the attackers every
night, with no error and a plausible-looking count in its output. Aggregating server-side removes the
row cap entirely: one row per IP comes back, so there is nothing left to truncate.

AGGREGATION IS IN SQL, deliberately. Cleaning/truncating/deduping/sorting the strings in ClickHouse
mirrors the old Python set-building exactly while keeping the response small: fetching the raw command
text for a 24h window is ~1.8MB (one IP alone had 675 distinct commands and 543KB of input), against a
128Mi pod. Two subtleties make the mirror faithful: substringUTF8 slices by code point like Python's
[:n] (plain substring would cut bytes and could split a UTF-8 sequence), and ClickHouse's byte-order
arraySort agrees with Python's code-point sorted() because UTF-8 preserves that ordering.
"""
import datetime
import ipaddress
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

CH = os.environ.get("CLICKHOUSE_URL", "http://clickhouse-hyperdx-logs.monitoring.svc:8123")
KEY = os.environ.get("ABUSEIPDB_API_KEY", "")
DRY = os.environ.get("DRY_RUN", "1") == "1"
WINDOW_H = int(os.environ.get("WINDOW_HOURS", "24"))
NS = os.environ.get("HONEYPOT_NS", "honeypot")

# handshake-completing events only — the policy's non-spoofed requirement. This tuple is the single
# definition: it is interpolated into the SQL below, so the store-side filter and the comment text can
# never drift apart.
REAL = ("cowrie.client.version", "cowrie.login.failed", "cowrie.login.success", "cowrie.command.input")

# One row per source IP. Note every string is cleaned and truncated BEFORE groupUniqArray, so the
# dedup happens on the same value the report will print — the old code deduped post-_clean() too.
SQL = """
WITH ev AS (
    SELECT
        JSONExtractString(Body, 'src_ip')   AS ip,
        JSONExtractString(Body, 'eventid')  AS eventid,
        TimestampTime                       AS t,
        JSONHas(Body, 'username')           AS has_user,
        JSONExtractString(Body, 'username') AS username,
        JSONExtractString(Body, 'password') AS password,
        JSONExtractString(Body, 'input')    AS input,
        JSONExtractInt(Body, 'dst_port')    AS dst_port
    FROM default.otel_logs
    WHERE TimestampTime >= now() - toIntervalHour({window:UInt16})
      AND LogAttributes['namespace'] = {ns:String}
      AND LogAttributes['container'] = 'logship'
      AND JSONExtractString(Body, 'src_ip') != ''
      AND JSONExtractString(Body, 'eventid') IN (%(real)s)
)
SELECT
    ip,
    count()                                                     AS n_total,
    countIf(eventid = 'cowrie.login.failed')                     AS n_login_failed,
    countIf(eventid = 'cowrie.login.success')                    AS n_login_success,
    countIf(eventid = 'cowrie.command.input' AND input != '')    AS n_commands,
    toUnixTimestamp(min(t))                                      AS first_epoch,
    toUnixTimestamp(max(t))                                      AS last_epoch,
    -- sorted+sliced in SQL so only the 6 the report uses cross the wire
    arraySlice(arraySort(groupUniqArrayIf(
        substringUTF8(trimBoth(replaceRegexpAll(concat(username, '/', password), '\\\\s+', ' ')), 1, 60),
        eventid IN ('cowrie.login.failed', 'cowrie.login.success') AND has_user)), 1, 6) AS creds,
    arraySlice(arraySort(groupUniqArrayIf(
        substringUTF8(trimBoth(replaceRegexpAll(input, '\\\\s+', ' ')), 1, 80),
        eventid = 'cowrie.command.input' AND input != '')), 1, 6) AS cmds,
    -- ALL ports, not a slice: the old code joined the whole set
    arraySort(groupUniqArrayIf(toString(dst_port), dst_port != 0)) AS ports
FROM ev
GROUP BY ip
ORDER BY ip
FORMAT JSONEachRow
""" % {"real": ", ".join("'%s'" % e for e in REAL)}


def _utc(epoch):
    return datetime.datetime.fromtimestamp(int(epoch), datetime.timezone.utc)


# ClickHouse's own query parameters, so the window and namespace are never string-concatenated in.
url = CH + "/?" + urllib.parse.urlencode({
    "param_window": str(WINDOW_H), "param_ns": NS, "default_format": "JSONEachRow"})
req = urllib.request.Request(url, data=SQL.encode(), headers={"Content-Type": "text/plain"})
try:
    raw = urllib.request.urlopen(req, timeout=60).read().decode()
except urllib.error.HTTPError as e:
    # ClickHouse puts the actual SQL error in the body; without it the message is just "500".
    print(f"FATAL: ClickHouse query failed: {e.code} {e.read().decode()[:500]}", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f"FATAL: ClickHouse query failed: {e}", file=sys.stderr)
    sys.exit(1)

rows = [json.loads(ln) for ln in raw.splitlines() if ln.strip()]

reported = skipped = 0
for a in rows:
    ip = a["ip"]
    try:
        if ipaddress.ip_address(ip).is_private:
            skipped += 1
            continue
    except ValueError:
        skipped += 1
        continue
    # Structurally guaranteed by the IN (...) filter above, which is why the old "no-handshake" skip
    # branch never actually fired — the Loki query filtered on the same four eventids. Kept as a real
    # assertion rather than deleted, so that if the filter is ever widened the policy still holds.
    if a["n_total"] <= 0:
        skipped += 1
        continue
    cats = ["18", "22"]                          # Brute-Force, SSH
    if a["n_commands"]:
        cats.append("15")                        # Hacking (executed commands in the fake shell)
    logins = a["n_login_failed"] + a["n_login_success"]
    first, last = _utc(a["first_epoch"]), _utc(a["last_epoch"])
    parts = [f"Cowrie SSH/Telnet honeypot: {a['n_total']} malicious events over {WINDOW_H}h."]
    if logins:
        parts.append(f"{logins} SSH/Telnet login attempts; creds tried: "
                     f"{', '.join(a['creds']) or 'n/a'}.")
    if a["n_commands"]:
        parts.append(f"Commands executed: {' | '.join(a['cmds'])}.")
    parts.append(f"Dest ports: {','.join(a['ports']) or '2222/2223'}. "
                 f"First {first.replace(microsecond=0).isoformat()}, "
                 f"last {last.replace(microsecond=0).isoformat()} UTC.")
    comment = " ".join(parts)[:1024]
    ts = last.replace(microsecond=0).isoformat()
    if DRY:
        print(f"WOULD REPORT {ip}  categories={','.join(cats)}  timestamp={ts}\n    {comment}")
        reported += 1
        continue
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
    except urllib.error.URLError as ex:
        # transient DNS/egress blip (e.g. socket.gaierror EAI_AGAIN) — log + skip this IP, do NOT abort
        # the whole daily batch (HTTPError is a URLError subclass, so it is still caught above first).
        print(f"report {ip} FAILED (network): {ex.reason}", file=sys.stderr)
print(f"done: {'would report' if DRY else 'reported'} {reported} IP(s), skipped {skipped} "
      f"(private / no events)")
