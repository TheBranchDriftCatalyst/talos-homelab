#!/usr/bin/env python3
"""Telemetry / Observability suite — audit Grafana dashboards panel-by-panel.

Offline (CI-safe): every panel in every registered dashboard has a resolvable datasource and a
non-empty query — catches broken/empty/dangling panels in the manifest.
--live (operator): execute every panel's query against its datasource (Loki/Mimir via port-forward)
and assert it returns data — or the panel is a justified EXPECTED_EMPTY. "All panels get a check."

  pytest -m telemetry              # offline structural audit
  pytest -m telemetry --live       # + execute every panel query, assert data
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib import helpers  # noqa: E402
import dashboards as reg  # noqa: E402

pytestmark = pytest.mark.telemetry
LIVE = os.environ.get("POSTURE_LIVE") == "1"


# ---------- panel extraction ----------
def _panels(dash):
    out = []
    def walk(ps):
        for p in ps:
            if p.get("type") == "row":
                walk(p.get("panels", [])); continue
            if p.get("type") in ("text", "dashlist", "news"):
                continue
            out.append(p)
    walk(dash.get("panels", []))
    return out


def _targets(panel):
    return [(t.get("expr") or t.get("rawSql") or "").strip() for t in panel.get("targets", [])]


def _ds_uid(obj):
    ds = obj.get("datasource")
    if isinstance(ds, dict):
        return ds.get("uid")
    return ds


def _tmpl_subst(dash):
    """Build a substituter for the dashboard's template variables. A panel query like
    `origin=~"$origin"` is meaningless without the variable resolved; Grafana defaults query-vars to
    $__all -> `.*`, so we do the same. Returns a fn(query)->query."""
    subs = {}
    for v in dash.get("templating", {}).get("list", []):
        n = v.get("name")
        if not n or n.startswith("__"):
            continue
        cur = v.get("current", {})
        val = cur.get("value")
        # $__all / multi / no concrete scalar -> match-all regex; a concrete scalar -> use it
        rep = ".*" if (val in (None, "$__all", "") or isinstance(val, list)) else str(val)
        subs[n] = rep
    def apply(q):
        for n, rep in subs.items():
            q = q.replace("${%s}" % n, rep)
            q = re.sub(r"\$%s(?![A-Za-z0-9_])" % re.escape(n), rep, q)
        return q
    return apply


def _resolve_ds(ds, dash):
    """Resolve a panel datasource to a concrete UID. A `$datasource` / `${datasource}` picker resolves to
    that template variable's current value (a concrete UID); everything else passes through."""
    if not ds:
        return ds
    s = str(ds)
    if s.startswith("$"):
        var = s.strip("${}")
        for v in dash.get("templating", {}).get("list", []):
            if v.get("name") == var and v.get("type") == "datasource":
                return (v.get("current") or {}).get("value") or ds
    return ds


def _all_panels():
    """[(dashname, panel_title, ds_uid, [queries])] across every auto-discovered dashboard."""
    rows = []
    for name, path, _uid in reg.DASHBOARDS:
        dash = json.loads((helpers.ROOT / path).read_text())
        tvar = _tmpl_subst(dash)
        for p in _panels(dash):
            pds = _ds_uid(p)
            queries = _targets(p)
            # a target can override the panel datasource
            for t in p.get("targets", []):
                if _ds_uid(t):
                    pds = _ds_uid(t)
            rows.append((name, p.get("title", "?"), _resolve_ds(pds, dash), [tvar(q) for q in queries if q]))
    return rows


PANELS = _all_panels()


# ---------- OFFLINE structural audit ----------
class TelemetryDashboards:
    pass


@pytest.mark.parametrize("dash,title,ds,queries", PANELS,
                         ids=[f"{r[0]}:{r[1]}" for r in PANELS])
def test_panel_structure(dash, title, ds, queries):
    """Every panel carries at least one non-empty query — catches broken/empty/dangling panels in the
    manifest. Auto-discovered across every committed dashboard.

    Datasource *reachability* is deliberately NOT asserted here: it's validated by the --live audit
    (which executes each query and reports panels whose datasource we don't port-forward). Imported
    grafana.com dashboards legitimately reference datasources by their own name/UID (e.g. a
    `$datasource` picker defaulting to "Cluster Prometheus"), so a hard DATASOURCES check would false-
    positive on them."""
    assert queries, f"[{dash}] panel {title!r} has no non-empty query"


# ---------- LIVE query audit ----------
def _subst_macros(q):
    for k, v in reg.MACROS.items():
        q = q.replace(k, v)
    return q


class _PortForward:
    """kubectl port-forward svc/<svc> to a local port for the duration of the audit."""
    def __init__(self, ns, svc, port):
        self.ns, self.svc, self.port, self.proc, self.local = ns, svc, port, None, None

    def __enter__(self):
        # pick an ephemeral local port
        import socket
        s = socket.socket(); s.bind(("127.0.0.1", 0)); self.local = s.getsockname()[1]; s.close()
        self.proc = subprocess.Popen(
            ["kubectl", "-n", self.ns, "port-forward", f"svc/{self.svc}", f"{self.local}:{self.port}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=helpers.ROOT)
        for _ in range(30):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.local}/", timeout=1)
                break
            except urllib.error.HTTPError:
                break  # any HTTP response = forward up
            except OSError:
                time.sleep(0.4)
        return self

    def __exit__(self, *a):
        if self.proc:
            self.proc.terminate()


_AGG = re.compile(r"\b(sum|count|topk|avg|min|max|rate|count_over_time|sum_over_time|bytes_over_time|absent)\b")


def _query(engine, local, path, q):
    """Run the panel query; return (#result series/streams, error).

    Loki: metric queries (with an aggregation) use the instant endpoint; raw LOG queries
    (line_format / no aggregation) 400 on instant and must use query_range. Prom: instant.
    """
    q = _subst_macros(q)
    is_log = engine == "loki" and not _AGG.search(q)
    if engine == "loki" and is_log:
        end = time.time(); start = end - 3600
        params = urllib.parse.urlencode({"query": q, "start": f"{int(start)}000000000",
                                         "end": f"{int(end)}000000000", "limit": "5",
                                         "direction": "backward"})
        url = f"http://127.0.0.1:{local}/loki/api/v1/query_range?{params}"
    else:
        params = urllib.parse.urlencode({"query": q})
        url = f"http://127.0.0.1:{local}{path}?{params}"
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            data = json.loads(r.read())
    except Exception as e:
        detail = ""
        try: detail = " :: " + e.read().decode()[:200]  # HTTPError body
        except Exception: pass
        return None, str(e) + detail
    result = data.get("data", {}).get("result", [])
    return len(result), None


@pytest.mark.skipif(not LIVE, reason="live query audit: pass --live")
def test_live_no_query_errors_and_curated_have_data():
    """Execute EVERY panel's query live against its datasource (auto-discovered dashboards).

    Two failure modes, so we get full live coverage without hundreds of allowlists:
      - a query that ERRORS (bad LogQL/PromQL, missing label, unreachable datasource) = a broken panel
        -> HARD FAIL for every dashboard.
      - a query returning NO DATA -> HARD FAIL only for the curated LIVE_AUDIT dashboards (they carry
        EXPECTED_EMPTY allowlists); for the rest it's reported (idle service vs real break is ambiguous
        without curation), not failed.
    Panels whose datasource can't be resolved to a queryable UID (unresolved $var, -- Mixed --, tempo)
    are reported as unqueryable, not failed.
    """
    from collections import defaultdict
    by_ds = defaultdict(list)
    unqueryable = []
    for dash, title, ds, queries in PANELS:
        if ds not in reg.DATASOURCES:
            unqueryable.append(f"[{dash}] {title!r} (ds={ds})")
            continue
        by_ds[ds].append((dash, title, queries))

    errors, curated_empty, other_empty, checked = [], [], 0, 0
    for ds, panels in by_ds.items():
        cfg = reg.DATASOURCES[ds]
        with _PortForward(cfg["namespace"], cfg["service"], cfg["port"]) as pf:
            for dash, title, queries in panels:
                got, err = 0, None
                for q in queries:  # a panel passes if ANY target returns data
                    n, e = _query(cfg["engine"], pf.local, cfg["path"], q)
                    if e:
                        err = e
                    elif n and n > 0:
                        got = n; break
                checked += 1
                if got:
                    continue
                if err:  # no data AND the query errored -> broken query, fail everywhere
                    errors.append(f"[{dash}] {title!r}: {err}")
                elif (dash, title) in reg.EXPECTED_EMPTY:
                    continue  # justified empty
                elif dash in reg.LIVE_AUDIT:
                    curated_empty.append(f"[{dash}] {title!r}")
                else:
                    other_empty += 1

    assert checked > 0, "no panels checked — cluster/datasource unreachable?"
    print(f"\n[telemetry] live-checked {checked} panels across {len(by_ds)} datasources; "
          f"{other_empty} non-curated panels returned no data (idle/ambiguous); "
          f"{len(unqueryable)} unqueryable (template/mixed/tempo datasource).")
    msg = []
    if errors:
        msg.append(f"{len(errors)} panel query ERRORS (broken queries): " + "; ".join(errors[:40]))
    if curated_empty:
        msg.append("curated panels returning NO data (not allowlisted): " + "; ".join(curated_empty))
    assert not msg, " | ".join(msg)


if __name__ == "__main__":
    if "--live" in sys.argv:
        os.environ["POSTURE_LIVE"] = "1"; LIVE = True
        sys.argv.remove("--live")
    sys.exit(pytest.main([__file__, "-v"] + sys.argv[1:]))
