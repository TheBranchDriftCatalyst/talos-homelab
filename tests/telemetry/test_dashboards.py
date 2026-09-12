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


def _all_panels():
    """[(dashname, uid, panel_title, ds_uid, [queries])] across every registered dashboard."""
    rows = []
    for name, path, _uid in reg.DASHBOARDS:
        dash = json.loads((helpers.ROOT / path).read_text())
        for p in _panels(dash):
            pds = _ds_uid(p)
            queries = _targets(p)
            # a target can override the panel datasource
            for t in p.get("targets", []):
                if _ds_uid(t):
                    pds = _ds_uid(t)
            rows.append((name, p.get("title", "?"), pds, [q for q in queries if q]))
    return rows


PANELS = _all_panels()


# ---------- OFFLINE structural audit ----------
class TelemetryDashboards:
    pass


@pytest.mark.parametrize("dash,title,ds,queries", PANELS,
                         ids=[f"{r[0]}:{r[1]}" for r in PANELS])
def test_panel_structure(dash, title, ds, queries):
    """Every panel resolves a known datasource and carries at least one non-empty query."""
    assert ds, f"[{dash}] panel {title!r} has no datasource"
    assert ds in reg.DATASOURCES, (
        f"[{dash}] panel {title!r} datasource {ds!r} is not in tests/telemetry/dashboards.py "
        f"DATASOURCES (known: {sorted(reg.DATASOURCES)})")
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


_LIVE_DASHES = sorted({r[0] for r in PANELS})


@pytest.mark.skipif(not LIVE, reason="live query audit: pass --live")
def test_live_every_panel_returns_data_or_is_allowlisted():
    # group panels by datasource so we port-forward each once
    from collections import defaultdict
    by_ds = defaultdict(list)
    for dash, title, ds, queries in PANELS:
        by_ds[ds].append((dash, title, queries))

    empty, errors, checked = [], [], 0
    for ds, panels in by_ds.items():
        cfg = reg.DATASOURCES.get(ds)
        if not cfg:
            errors.append(f"{ds}: unknown datasource"); continue
        with _PortForward(cfg["namespace"], cfg["service"], cfg["port"]) as pf:
            for dash, title, queries in panels:
                # a panel passes if ANY of its targets returns data
                got = 0; err = None
                for q in queries:
                    n, e = _query(cfg["engine"], pf.local, cfg["path"], q)
                    if e:
                        err = e
                    elif n and n > 0:
                        got = n; break
                checked += 1
                if got == 0:
                    if (dash, title) in reg.EXPECTED_EMPTY:
                        continue  # justified empty
                    if err:
                        errors.append(f"[{dash}] {title!r}: query error: {err}")
                    else:
                        empty.append(f"[{dash}] {title!r}")
    assert checked > 0, "no panels checked — cluster/datasource unreachable?"
    msg = []
    if empty:
        msg.append("panels returning NO data (not allowlisted): " + "; ".join(empty))
    if errors:
        msg.append("panel query errors: " + "; ".join(errors))
    assert not msg, " | ".join(msg)


if __name__ == "__main__":
    if "--live" in sys.argv:
        os.environ["POSTURE_LIVE"] = "1"; LIVE = True
        sys.argv.remove("--live")
    sys.exit(pytest.main([__file__, "-v"] + sys.argv[1:]))
