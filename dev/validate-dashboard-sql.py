#!/usr/bin/env python3
"""Execute every ClickHouse SQL target in a dashboard JSON against the live DB.

Grafana macros are substituted with concrete equivalents so the query that runs is
the query the panel will run, modulo the time window. A panel that errors is a
hard failure; a panel that returns 0 rows is reported but not failed, because an
empty security dashboard is a legitimate state.
"""
import json, re, subprocess, sys

POD = ["kubectl","-n","monitoring","exec","-i","chi-hyperdx-logs-logs-0-0-0","--",
       "clickhouse-client","--query"]

def demacro(q):
    q = q.replace("$__timeFilter(TimestampTime)", "TimestampTime > now() - INTERVAL 6 HOUR")
    q = q.replace("$__timeFilter(Timestamp)", "Timestamp > now() - INTERVAL 6 HOUR")
    q = q.replace("$__fromTime", "now() - INTERVAL 6 HOUR")
    q = q.replace("$__toTime", "now()")
    q = re.sub(r"\$__timeInterval\(([^)]+)\)", r"toStartOfInterval(\1, INTERVAL 5 MINUTE)", q)
    q = q.replace("$__interval", "5m").replace("$__range", "6h").replace("$__auto", "5m")
    q = re.sub(r"\$\{?node\}?", "talos00", q)
    return q

def run(q):
    p = subprocess.run(POD + [demacro(q)], capture_output=True, text=True, timeout=120)
    return p.returncode, p.stdout, p.stderr

def targets(path):
    d = json.load(open(path))
    out = []
    def walk(ps):
        for pn in ps:
            if pn.get("type") == "row":
                walk(pn.get("panels", [])); continue
            for t in pn.get("targets", []):
                ds = json.dumps(t.get("datasource", {}))
                if "clickhouse" in ds.lower():
                    out.append((pn.get("title"), pn.get("type"), t.get("rawSql") or t.get("expr") or ""))
    walk(d["panels"])
    return out

fail = empty = ok = 0
for path in sys.argv[1:]:
    print(f"\n### {path.split('/')[-1]}")
    for title, ptype, sql in targets(path):
        if not sql.strip():
            print(f"  [EMPTY SQL] {title}"); fail += 1; continue
        rc, so, se = run(sql)
        if rc != 0:
            print(f"  FAIL  [{ptype}] {title}")
            print("        " + (se.strip().splitlines() or ["?"])[0][:200])
            fail += 1
        else:
            n = len([l for l in so.splitlines() if l.strip()])
            if n == 0:
                print(f"  empty [{ptype}] {title}"); empty += 1
            else:
                print(f"  ok({n:>4}) [{ptype}] {title}"); ok += 1
print(f"\n=== ok={ok} empty={empty} FAIL={fail} ===")
sys.exit(1 if fail else 0)
