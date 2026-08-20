#!/usr/bin/env python3
"""Inventory and validate every live GrafanaDashboard query.

The script reads the live Grafana catalog rather than only repo-local JSON so
Grafana.com imports and application-owned GrafanaDashboard CRs are included.
It deliberately writes machine-readable artifacts; the checked-in audit report
is generated from those artifacts by ``report``.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import glob
import json
import os
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Any


GRAFANA_POD = "deploy/grafana-deployment"
GRAFANA_NAMESPACE = "monitoring"
GRAFANA_URL = "http://127.0.0.1:3000"
MIMIR_URL = "http://mimir-gateway.monitoring.svc/prometheus"
LOKI_URL = "http://loki.monitoring.svc:3100"


def run(command: list[str], *, check: bool = True) -> str:
    result = subprocess.run(command, text=True, capture_output=True)
    if check and result.returncode:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(command)}\n{result.stderr}")
    return result.stdout


def pod_get(url: str, timeout: int = 30) -> dict[str, Any]:
    output = run([
        "kubectl", "-n", GRAFANA_NAMESPACE, "exec", GRAFANA_POD, "--",
        "wget", f"--timeout={timeout}", "-qO-", url,
    ])
    return json.loads(output)


def walk_panels(panels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for panel in panels:
        found.append(panel)
        if isinstance(panel.get("panels"), list):
            found.extend(walk_panels(panel["panels"]))
    return found


def variable_values(dashboard: dict[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}
    for variable in dashboard.get("templating", {}).get("list", []):
        name = variable.get("name")
        if not name:
            continue
        current = variable.get("current", {}).get("value")
        if isinstance(current, list):
            current = next((str(value) for value in current if value not in ("$__all", "All")), None)
        if current in ("$__all", "All") and variable.get("allValue") not in (None, ""):
            current = variable["allValue"]
        if current in (None, "", "$__all", "All"):
            options = variable.get("options", []) or []
            current = next((str(option.get("value")) for option in options
                            if option.get("value") not in (None, "", "$__all", "All")), None)
        if current in (None, "", "$__all", "All") and variable.get("type") in ("custom", "interval"):
            raw = variable.get("query", "")
            if isinstance(raw, str) and raw:
                current = raw.split(",", 1)[0].strip()
        if current not in (None, ""):
            values[name] = str(current)
    return values


def datasource(target: dict[str, Any], panel: dict[str, Any], dashboard: dict[str, Any], values: dict[str, str]) -> tuple[str, str]:
    source = target.get("datasource") or panel.get("datasource") or dashboard.get("datasource") or {}
    if isinstance(source, str):
        uid, kind = source, source
    else:
        uid, kind = str(source.get("uid", "")), str(source.get("type", ""))
    for name, value in values.items():
        uid = uid.replace(f"${{{name}}}", value).replace(f"${name}", value)
        kind = kind.replace(f"${{{name}}}", value).replace(f"${name}", value)
    return uid, kind


def query_language(uid: str, kind: str, target: dict[str, Any]) -> str:
    joined = f"{uid} {kind}".lower()
    if "loki" in joined:
        return "logql"
    if "tempo" in joined:
        return "traceql"
    if target.get("expr") or "prometheus" in joined or "mimir" in joined or "$datasource" in joined or joined.strip() in ("", "default"):
        return "promql"
    if target.get("rawSql"):
        return "sql"
    return kind or uid or "unknown"


def extract_queries(dashboard: dict[str, Any], uid: str) -> list[dict[str, Any]]:
    queries: list[dict[str, Any]] = []
    values = variable_values(dashboard)
    for variable in dashboard.get("templating", {}).get("list", []):
        if variable.get("type") != "query":
            continue
        raw = variable.get("query", "")
        if isinstance(raw, dict):
            raw = raw.get("query", "")
        if not isinstance(raw, str) or not raw.strip():
            continue
        ds = variable.get("datasource") or dashboard.get("datasource") or {}
        ds_uid = ds if isinstance(ds, str) else ds.get("uid", "")
        ds_type = ds if isinstance(ds, str) else ds.get("type", "")
        queries.append({
            "dashboard_uid": uid, "dashboard_title": dashboard.get("title", uid),
            "source": "variable", "panel_id": None, "panel_title": f"Variable: {variable.get('name', '')}",
            "ref_id": variable.get("name", ""), "datasource_uid": ds_uid,
            "datasource_type": ds_type, "language": query_language(str(ds_uid), str(ds_type), {}),
            "query": raw.strip(), "variable_values": values,
        })
    for panel in walk_panels(dashboard.get("panels", [])):
        for target in panel.get("targets", []) or []:
            if target.get("hide") is True:
                hidden = True
            else:
                hidden = False
            raw = target.get("expr") or target.get("query") or target.get("rawSql") or ""
            if not isinstance(raw, str) or not raw.strip():
                continue
            ds_uid, ds_type = datasource(target, panel, dashboard, values)
            queries.append({
                "dashboard_uid": uid, "dashboard_title": dashboard.get("title", uid),
                "source": "panel", "panel_id": panel.get("id"), "panel_title": panel.get("title", "Untitled"),
                "panel_type": panel.get("type", ""), "ref_id": target.get("refId", ""),
                "datasource_uid": ds_uid, "datasource_type": ds_type,
                "language": query_language(ds_uid, ds_type, target), "query": raw.strip(), "hidden": hidden,
                "variable_values": values,
            })
    for index, query in enumerate(queries, start=1):
        query["query_id"] = f"{uid}:{index:04d}"
    return queries


def inventory(output: Path) -> None:
    cr_list = json.loads(run(["kubectl", "get", "grafanadashboard", "-A", "-o", "json"]))
    crds = []
    for item in cr_list.get("items", []):
        spec = item.get("spec", {})
        crds.append({
            "namespace": item["metadata"]["namespace"], "name": item["metadata"]["name"],
            "folder_ref": spec.get("folderRef"), "grafana_com_id": spec.get("grafanaCom", {}).get("id"),
            "config_map_ref": spec.get("configMapRef"), "url": spec.get("url"),
            "synchronized": any(c.get("type") == "DashboardSynchronized" and c.get("status") == "True"
                                for c in item.get("status", {}).get("conditions", [])),
        })
    catalog = pod_get(f"{GRAFANA_URL}/api/search?type=dash-db&limit=5000")
    dashboards = []
    queries = []
    for entry in sorted(catalog, key=lambda value: value["uid"]):
        response = pod_get(f"{GRAFANA_URL}/api/dashboards/uid/{urllib.parse.quote(entry['uid'])}")
        dashboard = response["dashboard"]
        extracted = extract_queries(dashboard, entry["uid"])
        dashboards.append({
            "uid": entry["uid"], "title": entry["title"], "folder_uid": entry.get("folderUid"),
            "folder_title": entry.get("folderTitle"), "tags": entry.get("tags", []),
            "url": entry.get("url"),
            "query_count": len(extracted), "panel_count": len(walk_panels(dashboard.get("panels", []))),
        })
        queries.extend(extracted)
    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "crds": crds, "dashboards": dashboards, "queries": queries,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote {output}: {len(crds)} CRDs, {len(dashboards)} dashboards, {len(queries)} queries")


VARIABLE_DEFAULTS = {
    "__interval": "5m", "__rate_interval": "5m", "__range": "6h", "__range_s": "21600",
    "__auto_interval_bucket": "5m",
    "__interval_ms": "300000", "__from": str(int((dt.datetime.now().timestamp() - 21600) * 1000)),
    "__to": str(int(dt.datetime.now().timestamp() * 1000)), "__timezone": "UTC",
}


def substitute(query: str, values: dict[str, str], language: str) -> str:
    result = query
    for name, value in sorted(VARIABLE_DEFAULTS.items(), key=lambda pair: len(pair[0]), reverse=True):
        result = result.replace(f"${{{name}}}", value).replace(f"${name}", value)
    for name, value in sorted(values.items(), key=lambda pair: len(pair[0]), reverse=True):
        result = result.replace(f"${{{name}}}", value).replace(f"${name}", value)
        result = re.sub(rf"\$\{{{re.escape(name)}:[^}}]+\}}", value, result)
    result = re.sub(r'\[\$\{?[A-Za-z_][A-Za-z0-9_]*(?::[^}]*)?\}?\]', '[5m]', result)
    wildcard = ".+" if language == "logql" else ".*"
    # Variables are frequently embedded inside a larger label regex, for
    # example pod=~"($cluster)-[0-9]+$". Resolve unknown variables inside
    # quoted matchers as wildcards before the generic scalar fallback below.
    def matcher_variables(match: re.Match[str]) -> str:
        operator, body = match.groups()
        had_variable = bool(re.search(r'\$\{?[A-Za-z_][A-Za-z0-9_]*(?::[^}]*)?\}?', body))
        body = re.sub(r'\$\{?[A-Za-z_][A-Za-z0-9_]*(?::[^}]*)?\}?', wildcard, body)
        # An unresolved exact-match variable represents "all" during the
        # backend audit. A literal equality such as cluster=".*" matches
        # nothing, so promote it to a regex matcher. Grafana performs the same
        # effective expansion when an All-valued query variable is selected.
        if had_variable and operator == "=":
            operator = "=~"
        return f'{operator}"{body}"'

    result = re.sub(r'([=!~]+)\s*"([^"]*)"', matcher_variables, result)
    result = re.sub(r'=~\s*"\$\{?[A-Za-z_][A-Za-z0-9_]*(?::[^}]*)?\}?"', f'=~"{wildcard}"', result)
    result = re.sub(r'!~\s*"\$\{?[A-Za-z_][A-Za-z0-9_]*(?::[^}]*)?\}?"', '!~"a^"', result)
    result = re.sub(r'=\s*"\$\{?[A-Za-z_][A-Za-z0-9_]*(?::[^}]*)?\}?"', f'=~"{wildcard}"', result)
    result = re.sub(r'!=\s*"\$\{?[A-Za-z_][A-Za-z0-9_]*(?::[^}]*)?\}?"', '!~"a^"', result)
    result = re.sub(r'\$\{?[A-Za-z_][A-Za-z0-9_]*(?::[^}]*)?\}?', '1', result)
    return result


def prometheus_variable(query: str) -> str | None:
    match = re.fullmatch(r'label_values\((.*),\s*([A-Za-z_][A-Za-z0-9_]*)\)', query.strip())
    if not match:
        return None
    selector, label = match.groups()
    if "," not in selector and "{" not in selector:
        selector = f"{{__name__=\"{selector.strip()}\"}}"
    return f"count by ({label}) ({selector})"


def validate_one(item: dict[str, Any]) -> dict[str, Any]:
    result = dict(item)
    language = item["language"]
    raw = item["query"]
    if item.get("hidden"):
        result.update(status="SKIP", reason="hidden target")
        return result
    if language == "promql":
        expression = prometheus_variable(raw) or raw
        if raw.startswith("query_result(") and raw.endswith(")"):
            expression = raw[len("query_result("):-1]
        expression = substitute(expression, item.get("variable_values", {}), language)
        if raw.startswith(("label_names(", "metrics(")) or (raw.startswith("label_values(") and prometheus_variable(raw) is None):
            result.update(status="REVIEW", reason="Grafana variable helper requires UI evaluation", evaluated_query=expression)
            return result
        url = f"{MIMIR_URL}/api/v1/query?query={urllib.parse.quote(expression, safe='')}"
    elif language == "logql":
        if raw.startswith(("label_values(", "label_names(", "query_result(")):
            result.update(status="REVIEW", reason="Loki variable helper requires Grafana UI evaluation", evaluated_query=raw)
            return result
        expression = substitute(raw, item.get("variable_values", {}), language)
        now_ns = int(dt.datetime.now().timestamp() * 1_000_000_000)
        start_ns = now_ns - 6 * 60 * 60 * 1_000_000_000
        url = (f"{LOKI_URL}/loki/api/v1/query_range?query={urllib.parse.quote(expression, safe='')}"
               f"&start={start_ns}&end={now_ns}&limit=1")
    else:
        result.update(status="SKIP", reason=f"unsupported datasource/language: {language}")
        return result
    try:
        response = pod_get(url, timeout=45)
        data = response.get("data", {}).get("result", [])
        if response.get("status") != "success":
            result.update(status="FAIL", reason=response.get("error", "backend rejected query"))
        elif data:
            result.update(status="PASS", reason="query executed and returned data", series=len(data))
        else:
            result.update(status="EMPTY", reason="query executed successfully but returned no data", series=0)
        result["evaluated_query"] = expression
    except Exception as error:  # noqa: BLE001 - audit must retain every failure
        result.update(status="FAIL", reason=str(error), evaluated_query=locals().get("expression", raw))
    return result


def validate(source: Path, output: Path, shard_index: int, shard_count: int, workers: int) -> None:
    payload = json.loads(source.read_text())
    selected = [q for index, q in enumerate(payload["queries"]) if index % shard_count == shard_index]
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(validate_one, selected))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"shard_index": shard_index, "shard_count": shard_count, "results": results}, indent=2) + "\n")
    counts: dict[str, int] = {}
    for result in results:
        counts[result["status"]] = counts.get(result["status"], 0) + 1
    print(f"wrote {output}: {json.dumps(counts, sort_keys=True)}")


def escape_cell(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def report(inventory_path: Path, result_glob: str, output: Path) -> None:
    payload = json.loads(inventory_path.read_text())
    merged: dict[str, dict[str, Any]] = {}
    for filename in glob.glob(result_glob):
        for item in json.loads(Path(filename).read_text()).get("results", []):
            merged[item["query_id"]] = item
    counts: dict[str, int] = {}
    for query in payload["queries"]:
        status = merged.get(query["query_id"], {}).get("status", "NOT_RUN")
        counts[status] = counts.get(status, 0) + 1
    lines = [
        "# Grafana Dashboard Query Audit",
        "",
        f"Generated: {dt.datetime.now(dt.timezone.utc).isoformat()}",
        "",
        "This is the canonical verification checklist for every live `GrafanaDashboard` CRD and dashboard query.",
        "Regenerate it with `scripts/audit-grafana-dashboards.py`; `EMPTY` is a review item, not automatically a defect.",
        "",
        "## Summary",
        "",
        f"- Dashboard CRDs: {len(payload['crds'])}",
        f"- Live Grafana dashboards: {len(payload['dashboards'])}",
        f"- Queries: {len(payload['queries'])}",
    ]
    for status in ("PASS", "EMPTY", "FAIL", "REVIEW", "SKIP", "NOT_RUN"):
        lines.append(f"- {status}: {counts.get(status, 0)}")
    failures = [merged[q["query_id"]] for q in payload["queries"]
                if merged.get(q["query_id"], {}).get("status") == "FAIL"]
    reviews = [merged[q["query_id"]] for q in payload["queries"]
               if merged.get(q["query_id"], {}).get("status") == "REVIEW"]
    empty_counts: dict[str, int] = {}
    for query in payload["queries"]:
        if merged.get(query["query_id"], {}).get("status") == "EMPTY":
            empty_counts[query["dashboard_title"]] = empty_counts.get(query["dashboard_title"], 0) + 1
    lines.extend(["", "## Backend-rejected queries", "",
                  "These are confirmed query defects: the selected backend returned an error after variable substitution.", "",
                  "| Check | Dashboard | Panel | Ref | Query | Backend finding |", "|---|---|---|---|---|---|"])
    for item in failures:
        lines.append("| " + " | ".join([
            "[ ]", escape_cell(item["dashboard_title"]), escape_cell(item["panel_title"]),
            escape_cell(item.get("ref_id", "")), f"`{escape_cell(item['query'])}`", escape_cell(item["reason"]),
        ]) + " |")
    lines.extend(["", "## Empty-result review queue", "",
                  "These queries are syntactically valid but returned no data in the six-hour audit window. Verify each against intended deployment state.", "",
                  "| Check | Dashboard | Empty queries |", "|---|---|---|"])
    for title, count in sorted(empty_counts.items(), key=lambda value: (-value[1], value[0].lower())):
        lines.append(f"| [ ] | {escape_cell(title)} | {count} |")
    lines.extend(["", "## Grafana-helper review queue", "",
                  "These template helpers are evaluated by Grafana rather than directly by Prometheus/Loki and require a UI/API-variable check.", "",
                  "| Check | Dashboard | Variable | Query | Finding |", "|---|---|---|---|---|"])
    for item in reviews:
        lines.append("| " + " | ".join([
            "[ ]", escape_cell(item["dashboard_title"]), escape_cell(item["panel_title"]),
            f"`{escape_cell(item['query'])}`", escape_cell(item["reason"]),
        ]) + " |")
    lines.extend(["", "## CRD reconciliation checklist", "", "| Check | Namespace | CRD | Source | Synchronized |", "|---|---|---|---|---|"])
    for crd in sorted(payload["crds"], key=lambda value: (value["namespace"], value["name"])):
        source = crd.get("config_map_ref") or (f"grafana.com/{crd['grafana_com_id']}" if crd.get("grafana_com_id") else crd.get("url") or "inline")
        ok = crd["synchronized"]
        lines.append(f"| [{'x' if ok else ' '}] | {escape_cell(crd['namespace'])} | {escape_cell(crd['name'])} | {escape_cell(source)} | {ok} |")
    lines.extend(["", "## Query verification checklist", ""])
    grouped: dict[str, list[dict[str, Any]]] = {}
    for query in payload["queries"]:
        grouped.setdefault(query["dashboard_uid"], []).append(query)
    dashboard_meta = {item["uid"]: item for item in payload["dashboards"]}
    for uid in sorted(grouped, key=lambda value: dashboard_meta[value]["title"].lower()):
        meta = dashboard_meta[uid]
        lines.extend([
            f"### {meta['title']} (`{uid}`)", "",
            f"Folder: {meta.get('folder_title') or 'General'} · Panels: {meta['panel_count']} · Queries: {meta['query_count']}", "",
            "| Check | Status | Source | Panel / variable | Ref | Datasource | Query | Finding |",
            "|---|---|---|---|---|---|---|---|",
        ])
        for query in grouped[uid]:
            checked = merged.get(query["query_id"], {})
            status = checked.get("status", "NOT_RUN")
            mark = "x" if status == "PASS" else " "
            lines.append("| " + " | ".join([
                f"[{mark}]", status, escape_cell(query["source"]), escape_cell(query["panel_title"]),
                escape_cell(query.get("ref_id", "")), escape_cell(query.get("datasource_uid") or query.get("datasource_type")),
                f"`{escape_cell(query['query'])}`", escape_cell(checked.get("reason", "not run")),
            ]) + " |")
        lines.append("")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n")
    print(f"wrote {output}")


def render(inventory_path: Path, output: Path, screenshot_dir: Path, base_url: str) -> None:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise RuntimeError("install Playwright for the selected Python interpreter") from error
    payload = json.loads(inventory_path.read_text())
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    with sync_playwright() as playwright:
        launch_options: dict[str, Any] = {"headless": True}
        if executable := os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE"):
            launch_options["executable_path"] = executable
        browser = playwright.chromium.launch(**launch_options)
        context = browser.new_context(ignore_https_errors=True, viewport={"width": 1920, "height": 1080})
        for dashboard in payload["dashboards"]:
            page = context.new_page()
            uid = dashboard["uid"]
            console_errors: list[str] = []
            page_errors: list[str] = []
            failed_requests: list[str] = []

            def on_console(message: Any) -> None:
                if message.type == "error":
                    console_errors.append(message.text)

            page.on("console", on_console)
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.on("requestfailed", lambda request: failed_requests.append(f"{request.method} {request.url}: {request.failure}"))
            path = dashboard.get("url") or f"/d/{urllib.parse.quote(uid)}"
            url = f"{base_url.rstrip('/')}{path}?orgId=1&from=now-6h&to=now"
            started = dt.datetime.now()
            navigation_error = ""
            status_code = None
            try:
                response = page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                status_code = response.status if response else None
                page.locator("body").wait_for(state="visible", timeout=10_000)
                try:
                    page.get_by_text(dashboard["title"], exact=False).first.wait_for(state="visible", timeout=2_000)
                except PlaywrightTimeoutError:
                    pass
                page.wait_for_timeout(2_000)
                page.add_style_tag(content="*,*::before,*::after{animation:none!important;transition:none!important}")
                page.screenshot(path=str(screenshot_dir / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', uid)}.png"), full_page=True)
            except Exception as error:  # noqa: BLE001 - preserve render failures in the report
                navigation_error = str(error)
            body = page.locator("body").inner_text(timeout=10_000) if not navigation_error else ""
            lowered = body.lower()
            results.append({
                "uid": uid, "title": dashboard["title"], "url": url, "status_code": status_code,
                "duration_seconds": (dt.datetime.now() - started).total_seconds(),
                "navigation_error": navigation_error, "console_errors": sorted(set(console_errors)),
                "page_errors": sorted(set(page_errors)), "failed_requests": sorted(set(failed_requests)),
                "no_data_text_count": lowered.count("no data"),
                "query_error_text_count": lowered.count("query error") + lowered.count("bad gateway"),
                "access_denied": "access denied" in lowered or "unauthorized" in lowered,
                "rendered": not navigation_error and status_code == 200 and dashboard["title"].lower() in lowered,
            })
            page.close()
        browser.close()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "results": results}, indent=2) + "\n")
    print(f"wrote {output}: {sum(1 for item in results if item['rendered'])}/{len(results)} rendered")


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    inv = subparsers.add_parser("inventory")
    inv.add_argument("--output", type=Path, required=True)
    val = subparsers.add_parser("validate")
    val.add_argument("--inventory", type=Path, required=True)
    val.add_argument("--output", type=Path, required=True)
    val.add_argument("--shard-index", type=int, default=0)
    val.add_argument("--shard-count", type=int, default=1)
    val.add_argument("--workers", type=int, default=4)
    rep = subparsers.add_parser("report")
    rep.add_argument("--inventory", type=Path, required=True)
    rep.add_argument("--results-glob", required=True)
    rep.add_argument("--output", type=Path, required=True)
    ren = subparsers.add_parser("render")
    ren.add_argument("--inventory", type=Path, required=True)
    ren.add_argument("--output", type=Path, required=True)
    ren.add_argument("--screenshot-dir", type=Path, required=True)
    ren.add_argument("--base-url", default="https://grafana.talos00")
    args = parser.parse_args()
    if args.command == "inventory":
        inventory(args.output)
    elif args.command == "validate":
        validate(args.inventory, args.output, args.shard_index, args.shard_count, args.workers)
    elif args.command == "report":
        report(args.inventory, args.results_glob, args.output)
    else:
        render(args.inventory, args.output, args.screenshot_dir, args.base_url)


if __name__ == "__main__":
    main()
