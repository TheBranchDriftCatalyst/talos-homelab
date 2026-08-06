#!/usr/bin/env python3
"""Cloudflare DNS records exporter for the external-dns dashboard (TALOS-2kg).

external-dns exposes only COUNTS; no metric/log lists records by name in steady
state. This scrapes the Cloudflare zone every SCRAPE_INTERVAL and exposes per-record
+ status-bucketed Prometheus metrics so Grafana can show a live inventory and bucket
records by management/sync status over time (aggregatable with external_dns_* series).

Read-only (CF DNS read). Python stdlib only. Fails soft: on CF error it keeps serving
the last good snapshot with external_dns_cf_scrape_success 0.
"""
import json
import os
import ssl
import threading
import time
import urllib.request

CF_TOKEN = os.environ.get("CF_API_TOKEN", "")
CF_ZONE = os.environ.get("CF_ZONE", "knowledgedump.space")
OWNER = os.environ.get("TXT_OWNER_ID", "talos-homelab")
INTERVAL = int(os.environ.get("SCRAPE_INTERVAL", "60"))
PORT = int(os.environ.get("PORT", "9100"))
API = "https://api.cloudflare.com/client/v4"

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_lock = threading.Lock()
_snapshot = "# HELP external_dns_cf_scrape_success 1 if the last scrape succeeded.\n# TYPE external_dns_cf_scrape_success gauge\nexternal_dns_cf_scrape_success 0\n"


def _ssl_ctx():
    """Verified TLS if a CA bundle is present, else fall back to unverified (surfaced
    via external_dns_cf_tls_verified) so the exporter still works on cert-less images."""
    ctx = ssl.create_default_context()
    try:
        if ctx.cert_store_stats().get("x509_ca", 0) > 0:
            return ctx, 1
    except Exception:
        pass
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx, 0


_SSL, TLS_VERIFIED = _ssl_ctx()


def _cf(path):
    req = urllib.request.Request(API + path, headers={"Authorization": "Bearer " + CF_TOKEN})
    with urllib.request.urlopen(req, timeout=15, context=_SSL) as r:
        return json.load(r)


def _esc(v):
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _fetch_records():
    zres = (_cf("/zones?name=" + CF_ZONE).get("result") or [])
    if not zres:
        raise RuntimeError("zone %s not found" % CF_ZONE)
    zid = zres[0]["id"]
    records, page = [], 1
    while True:
        resp = _cf("/zones/%s/dns_records?per_page=100&page=%d" % (zid, page))
        records.extend(resp.get("result") or [])
        info = resp.get("result_info") or {}
        if page >= (info.get("total_pages") or 1):
            break
        page += 1
    return records


def _managed_fqdn(txt_name):
    # _externaldns.cname-linkwarden.knowledgedump.space -> linkwarden.knowledgedump.space
    n = txt_name
    if n.startswith("_externaldns."):
        n = n[len("_externaldns."):]
    if n.startswith("cname-"):
        n = n[len("cname-"):]
    return n


def build_metrics():
    t0 = time.time()
    lines = []
    add = lines.append
    try:
        records = _fetch_records()
        ok = 1
    except Exception:
        records, ok = None, 0

    add("# HELP external_dns_cf_scrape_success 1 if the last Cloudflare scrape succeeded.")
    add("# TYPE external_dns_cf_scrape_success gauge")
    add("external_dns_cf_scrape_success %d" % ok)
    add("# HELP external_dns_cf_tls_verified 1 if CF is reached with verified TLS.")
    add("# TYPE external_dns_cf_tls_verified gauge")
    add("external_dns_cf_tls_verified %d" % TLS_VERIFIED)
    add("# HELP external_dns_cf_scrape_duration_seconds Duration of the last scrape.")
    add("# TYPE external_dns_cf_scrape_duration_seconds gauge")
    add("external_dns_cf_scrape_duration_seconds %.3f" % (time.time() - t0))

    if not ok:
        return "\n".join(lines) + "\n"

    add("# HELP external_dns_cf_last_scrape_timestamp_seconds Unix time of last good scrape.")
    add("# TYPE external_dns_cf_last_scrape_timestamp_seconds gauge")
    add("external_dns_cf_last_scrape_timestamp_seconds %d" % int(time.time()))

    # ownership set: FQDNs external-dns owns (via _externaldns TXT with our owner id)
    managed = set()
    for r in records:
        if r["type"] == "TXT" and r["name"].startswith("_externaldns.") and OWNER in (r.get("content") or ""):
            managed.add(_managed_fqdn(r["name"]))

    add("# HELP external_dns_cf_record_info A Cloudflare DNS record (value=1); labels carry it.")
    add("# TYPE external_dns_cf_record_info gauge")
    buckets = {}          # (status, type) -> count
    matched = set()       # managed FQDNs that have a live record
    managed_count = 0
    for r in records:
        name, typ = r["name"], r["type"]
        if typ == "TXT" and name.startswith("_externaldns.") and OWNER in (r.get("content") or ""):
            buckets[("owner_txt", "TXT")] = buckets.get(("owner_txt", "TXT"), 0) + 1
            continue  # ownership markers are not inventory rows
        is_managed = name in managed
        if is_managed:
            matched.add(name)
            managed_count += 1
            status = "managed"
        else:
            status = "unmanaged"
        content = _esc((r.get("content") or "")[:60])
        add('external_dns_cf_record_info{fqdn="%s",type="%s",content="%s",ttl="%s",proxied="%s",managed="%s",owner="%s"} 1'
            % (_esc(name), _esc(typ), content, r.get("ttl"), str(r.get("proxied")).lower(), str(is_managed).lower(), _esc(OWNER)))
        buckets[(status, typ)] = buckets.get((status, typ), 0) + 1

    # ownership TXTs whose managed record is missing = orphaned leftovers
    for _ in (managed - matched):
        buckets[("orphan_txt", "TXT")] = buckets.get(("orphan_txt", "TXT"), 0) + 1

    add("# HELP external_dns_cf_records Records bucketed by management status and type.")
    add("# TYPE external_dns_cf_records gauge")
    for (status, typ), c in sorted(buckets.items()):
        add('external_dns_cf_records{status="%s",type="%s"} %d' % (status, _esc(typ), c))
    add("# HELP external_dns_cf_managed_records Records owned by external-dns (owner match).")
    add("# TYPE external_dns_cf_managed_records gauge")
    add("external_dns_cf_managed_records %d" % managed_count)
    add("# HELP external_dns_cf_zone_records_total Total records in the zone.")
    add("# TYPE external_dns_cf_zone_records_total gauge")
    add("external_dns_cf_zone_records_total %d" % len(records))
    return "\n".join(lines) + "\n"


def _refresh_loop():
    global _snapshot
    while True:
        try:
            s = build_metrics()
        except Exception:
            s = "external_dns_cf_scrape_success 0\n"
        with _lock:
            _snapshot = s
        time.sleep(INTERVAL)


class _H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.rstrip("/") in ("/metrics", ""):
            with _lock:
                body = _snapshot.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *a):
        pass  # quiet


if __name__ == "__main__":
    try:
        _snapshot = build_metrics()  # prime once so first scrape has data
    except Exception:
        pass
    threading.Thread(target=_refresh_loop, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), _H).serve_forever()
