#!/usr/bin/env python3
"""Cloudflare DNS records exporter for the external-dns dashboard (TALOS-2kg).

external-dns exposes only COUNTS; no metric/log lists records by name in steady
state. This scrapes the Cloudflare zone every SCRAPE_INTERVAL and exposes per-record
+ status-bucketed Prometheus metrics so Grafana can show a live inventory and bucket
records by management/sync status over time (aggregatable with external_dns_* series).

Read-only (CF DNS read). Python stdlib only. Fails soft: on CF error it keeps serving
the last good snapshot with external_dns_cf_scrape_success 0.

TALOS-lfxg — intermittent scrape failures (external_dns_cf_scrape_success avg ~0.69/7d):
the CF_API_TOKEN is SHARED with cert-manager + external-dns + cloudflare-ddns, so under
DNS-01 challenge / ddns bursts Cloudflare intermittently rejects this exporter's calls
(observed as fast 401/403 "Invalid API Token", not timeouts). Mitigations here need NO
new CF token:
  (a) poll CF slowly (SCRAPE_INTERVAL default 300s / 5m) to shrink our slice of the
      shared rate budget — ~2 CF calls per 5m instead of per 60s;
  (b) generous HTTP timeout + bounded retry with exponential backoff + jitter, honoring
      Retry-After, so a single transient reject doesn't fail the whole refresh;
  (c) real fail-soft cache: only a SUCCESSFUL scrape overwrites the record inventory; a
      failed refresh keeps serving the last good records (flagging success=0 + snapshot
      age) instead of zeroing every gauge for a full interval.
Recommended follow-up (operator, not done here): give the exporter its OWN read-only CF
token (Zone.Read + DNS.Read) so its rate budget is isolated from cert-manager/external-dns.
"""
import json
import os
import random
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request

CF_TOKEN = os.environ.get("CF_API_TOKEN", "")
CF_ZONE = os.environ.get("CF_ZONE", "knowledgedump.space")
OWNER = os.environ.get("TXT_OWNER_ID", "talos-homelab")
INTERVAL = int(os.environ.get("SCRAPE_INTERVAL", "300"))  # TALOS-lfxg: 5m poll (was 60s)
PORT = int(os.environ.get("PORT", "9100"))
# TALOS-lfxg: retry/backoff knobs (env-overridable, sane defaults).
TIMEOUT = int(os.environ.get("CF_HTTP_TIMEOUT", "30"))    # was a hardcoded 15s
RETRIES = int(os.environ.get("CF_MAX_RETRIES", "3"))      # attempts after the first try
BACKOFF = float(os.environ.get("CF_BACKOFF", "2.0"))      # base seconds for exp backoff
API = "https://api.cloudflare.com/client/v4"

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_lock = threading.Lock()
_snapshot = "# HELP external_dns_cf_scrape_success 1 if the last scrape succeeded.\n# TYPE external_dns_cf_scrape_success gauge\nexternal_dns_cf_scrape_success 0\n"
# TALOS-lfxg: last SUCCESSFUL record inventory (body lines) + when it was taken. A failed
# refresh reuses these so transient CF rejects don't zero the dashboard.
_last_records_body = ""
_last_ok_ts = 0.0


def _log(msg):
    # TALOS-lfxg: surface CF failures on stdout (they were silently swallowed, which is
    # why the intermittent 401/403 was invisible in `kubectl logs`).
    print("[cf-exporter] " + msg, file=sys.stdout, flush=True)


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

# TALOS-lfxg: HTTP statuses worth retrying. 429/5xx are the obvious transients; 401/403
# are included because under shared-token rate pressure CF returns fast bogus auth errors
# for a token that is actually valid (~69% success observed) — a short backoff usually
# clears them. A genuinely revoked token just costs RETRIES extra tries, bounded by backoff.
_RETRY_STATUS = frozenset((401, 403, 429, 500, 502, 503, 504))


def _cf(path):
    last = None
    for attempt in range(RETRIES + 1):
        try:
            req = urllib.request.Request(API + path, headers={"Authorization": "Bearer " + CF_TOKEN})
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=_SSL) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            last = e
            if e.code in _RETRY_STATUS and attempt < RETRIES:
                # Honor Retry-After if CF sent one, else exponential backoff with full jitter.
                retry_after = 0.0
                try:
                    retry_after = float(e.headers.get("Retry-After") or 0)
                except (TypeError, ValueError):
                    retry_after = 0.0
                delay = retry_after or (BACKOFF * (2 ** attempt))
                delay += random.uniform(0, delay * 0.25)  # decorrelate from cert-manager/ddns bursts
                _log("HTTP %d on %s (attempt %d/%d) — retrying in %.1fs" % (e.code, path, attempt + 1, RETRIES, delay))
                time.sleep(delay)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            if attempt < RETRIES:
                delay = BACKOFF * (2 ** attempt)
                delay += random.uniform(0, delay * 0.25)
                _log("%r on %s (attempt %d/%d) — retrying in %.1fs" % (e, path, attempt + 1, RETRIES, delay))
                time.sleep(delay)
                continue
            raise
    if last:  # exhausted retries
        raise last


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


def _record_lines(records):
    """Build the record-inventory portion of the exposition (everything that depends on a
    successful scrape). Kept separate so the fail-soft path can reuse the last good body."""
    lines = []
    add = lines.append

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
    return "\n".join(lines)


def build_metrics():
    global _last_records_body, _last_ok_ts
    t0 = time.time()
    try:
        records = _fetch_records()
        ok = 1
    except Exception as e:
        records, ok = None, 0
        _log("CF scrape FAILED (serving last good snapshot): %r" % e)  # TALOS-lfxg: no longer silent

    lines = []
    add = lines.append
    add("# HELP external_dns_cf_scrape_success 1 if the last Cloudflare scrape succeeded.")
    add("# TYPE external_dns_cf_scrape_success gauge")
    add("external_dns_cf_scrape_success %d" % ok)
    add("# HELP external_dns_cf_tls_verified 1 if CF is reached with verified TLS.")
    add("# TYPE external_dns_cf_tls_verified gauge")
    add("external_dns_cf_tls_verified %d" % TLS_VERIFIED)
    add("# HELP external_dns_cf_scrape_duration_seconds Duration of the last scrape.")
    add("# TYPE external_dns_cf_scrape_duration_seconds gauge")
    add("external_dns_cf_scrape_duration_seconds %.3f" % (time.time() - t0))
    # TALOS-lfxg: age of the record inventory currently being served (0 right after a good
    # scrape; grows while CF is failing). Lets the dashboard/alerts distinguish "fresh" from
    # "stale but still shown" data even though the record gauges stay populated.
    add("# HELP external_dns_cf_snapshot_age_seconds Age of the served record inventory.")
    add("# TYPE external_dns_cf_snapshot_age_seconds gauge")
    add("external_dns_cf_snapshot_age_seconds %d" % (int(time.time() - _last_ok_ts) if _last_ok_ts else 0))

    if ok:
        body = _record_lines(records)
        _last_records_body = body           # TALOS-lfxg: cache last GOOD inventory
        _last_ok_ts = time.time()
        add("# HELP external_dns_cf_last_scrape_timestamp_seconds Unix time of last good scrape.")
        add("# TYPE external_dns_cf_last_scrape_timestamp_seconds gauge")
        add("external_dns_cf_last_scrape_timestamp_seconds %d" % int(_last_ok_ts))
        return "\n".join(lines) + "\n" + body + "\n"

    # Fail-soft (TALOS-lfxg): reuse the last good inventory if we have one, so a transient
    # CF blip flips scrape_success->0 without wiping every record/bucket gauge.
    if _last_records_body:
        add("# HELP external_dns_cf_last_scrape_timestamp_seconds Unix time of last good scrape.")
        add("# TYPE external_dns_cf_last_scrape_timestamp_seconds gauge")
        add("external_dns_cf_last_scrape_timestamp_seconds %d" % int(_last_ok_ts))
        return "\n".join(lines) + "\n" + _last_records_body + "\n"
    return "\n".join(lines) + "\n"


def _refresh_loop():
    global _snapshot
    while True:
        try:
            s = build_metrics()
        except Exception:
            # build_metrics already fails soft internally; this is a last-resort guard that
            # must NOT clobber a good cached snapshot with a bare zero (TALOS-lfxg).
            with _lock:
                if _snapshot:
                    time.sleep(INTERVAL)
                    continue
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
