#!/usr/bin/env python3
"""mega-log-analysis — turn the centralised error-log stream into a ticket tree.

This exists because ServiceName only became trustworthy on 2026-10-15 (0.35% ->
100% coverage, TALOS-7e6j). Before that, errors could not be attributed per
service and this campaign was not expressible.

It is deliberately a PIPELINE, not a report: every stage writes a JSON artifact
the next stage reads, so the whole thing is re-runnable and the ticket tree can
be regenerated from a later window without hand-editing anything.

  census      errors per service for a window
  signatures  cluster bodies into normalised signatures per service
  triage      classify each signature: misclassified / expected / real
  tickets     emit (and with --apply, create) the beads L1/L2/L3 tree
  prompt      emit the swarm agent prompt for one signature
  burndown    diff a fresh census against a committed baseline
  selftest    prove every classifier can fire

THE ONE THING TO KNOW BEFORE TRUSTING THE NUMBERS: a third of rows whose
SeverityText says error are not errors -- the body itself says INFO, TRACE or
WARN. `triage` is what separates them, and `tickets` refuses to file anything
classified `misclassified` because the fix for those is the pipeline, not the
app. See README.md "Findings".

Deps are stdlib + pyyaml only, matching dev/helm-values-lint: the flake's
pythonEnv provides pytest, pyyaml and rich and nothing else, so there is no
build step and this runs from a clean checkout.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

TOOL_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOL_DIR.parent.parent
BASELINE_DIR = TOOL_DIR / "baseline"
EXPECTED_FILE = TOOL_DIR / "expected.yaml"

# The ClickHouse that backs ClickStack/HyperDX. Reached by exec rather than a
# driver because there is no in-cluster route and no python clickhouse client in
# the flake.
CH_POD = os.environ.get("MLA_CH_POD", "chi-hyperdx-logs-logs-0-0-0")
CH_NS = os.environ.get("MLA_CH_NS", "monitoring")
ERROR_SEVERITIES = ("error", "fatal", "critical")

# ── colour ────────────────────────────────────────────────────────────────────
_TTY = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if _TTY else s


def red(s): return _c("31", s)
def yellow(s): return _c("33", s)
def green(s): return _c("32", s)
def cyan(s): return _c("36", s)
def dim(s): return _c("2", s)
def bold(s): return _c("1", s)


def now_utc() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


# ── clickhouse ────────────────────────────────────────────────────────────────
def ch(query: str, timeout: int = 180) -> str:
    """Run one query, return raw stdout. Raises with ClickHouse's own error text.

    ClickHouse puts the useful part of a failure in the body, not the exit code,
    so the message is carried through rather than collapsed to 'command failed'.
    """
    proc = subprocess.run(
        ["kubectl", "-n", CH_NS, "exec", "-i", CH_POD, "--", "clickhouse-client", "-q", query],
        capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"clickhouse query failed: {proc.stderr.strip()[:400]}")
    return proc.stdout


def tsv(query: str) -> list[list[str]]:
    out = ch(query + " FORMAT TSV")
    return [ln.split("\t") for ln in out.splitlines() if ln.strip()]


def _sev_list() -> str:
    return ", ".join(f"'{s}'" for s in ERROR_SEVERITIES)


# Normalisation happens in SQL so the grouping is done by ClickHouse rather than
# by pulling every body across the wire. Order matters: ANSI first (kyverno and
# traefik wrap their level in escape codes, which would otherwise survive into
# the signature and split one cause into many), then long hex, then digits.
SIG_EXPR = (
    "substring(replaceRegexpAll(replaceRegexpAll(replaceRegexpAll("
    "Body, '\\x1b\\\\[[0-9;]*m', ''), '[0-9a-f]{8,}', '<h>'), '[0-9]+', '<n>'), 1, 160)"
)

# Facts that must be read from the RAW body, because SIG_EXPR destroys them.
# Numeric levels are the clearest case: pino writes {"level":30} for info, and
# normalisation rewrites that to {"level":<n>}, erasing the only evidence of
# what the line actually was. Found while reviewing clickstack, whose 301
# "errors"/h are all level 30.
LEVEL_NUM_EXPR = "any(toInt32OrZero(extract(Body, '\"level\"[ ]*:[ ]*([0-9]+)')))"

# Does the body declare a level AT ALL, in any convention we recognise?
HAS_LEVEL_EXPR = (
    "max(match(Body, '\"level\"|level=|^[IWEF][0-9]{4} |TRC|DBG|ERR|\"s\"[ ]*:'))"
)

# Does the body contain any error vocabulary? Used ONLY to protect the
# no-declared-level heuristic from suppressing a genuine error.
HAS_ERRWORD_EXPR = (
    "max(match(lower(Body), 'error|fail|exception|denied|refused|timeout|unable|"
    "cannot|panic|fatal|traceback|not found|invalid'))"
)


def sig_id(service: str, sig: str) -> str:
    """Stable id for a (service, signature) pair.

    Embedded in ticket descriptions so `tickets` is idempotent: a re-run finds
    the existing ticket instead of filing a duplicate. Must not change when
    counts change, so only service+signature feed it.
    """
    return hashlib.sha1(f"{service}\x00{sig}".encode()).hexdigest()[:12]


# ── triage ────────────────────────────────────────────────────────────────────
# A row is "misclassified" when the body states its own level and that level is
# not an error. These are pipeline bugs, never app bugs.
MISCLASSIFIED_RULES: list[tuple[str, str]] = [
    ("body_says_TRACE", r"TRC"),
    ("body_says_DEBUG", r"DBG"),
    ("body_says_klog_info", r"^I<n> "),
    ("body_says_klog_warn", r"^W<n> "),
    ("body_says_json_info", r'"(s|level|severity)"\s*:\s*"?(I|info|INFO)'),
    ("body_says_json_warn", r'"(s|level|severity)"\s*:\s*"?(W|warn|WARN|warning)'),
    # logfmt. Added after the first real run: crowdsec-lapi and mimir emit
    # `level=info` in logfmt, which the JSON rules above cannot see. That gap
    # alone left 94 signatures / 1,547 rows/h wrongly classified `real`.
    ("body_says_logfmt_info", r"\blevel=info\b"),
    ("body_says_logfmt_warn", r"\blevel=warn(ing)?\b"),
    ("body_says_logfmt_debug", r"\blevel=(debug|trace)\b"),
]

# A line that states level=error ANYWHERE is an error, even if it also carries a
# nested `level=info` (mimir's alertmanager lines do exactly this: an outer
# error wrapping an inner info-level component field). Without this guard the
# logfmt rules above would swallow genuine errors.
ERROR_WINS = re.compile(r"\blevel=(error|fatal|crit)|\"(s|level|severity)\"\s*:\s*\"?(E|error|fatal)")


class Expected:
    """Signatures that are errors but are not bugs, each with its evidence.

    Mirrors dev/helm-values-lint/allow.yaml: an entry is a DELIBERATE decision,
    and "it was noisy" is not a reason. Entries carry `why` so a later reader can
    judge whether it still holds.
    """

    def __init__(self, entries: list[dict[str, Any]]):
        self.entries = entries
        self._compiled = [(e, re.compile(e["pattern"])) for e in entries]

    @classmethod
    def load(cls, path: Path) -> "Expected":
        if not path.exists():
            return cls([])
        doc = yaml.safe_load(path.read_text()) or {}
        return cls(doc.get("expected") or [])

    def match(self, service: str, sig: str) -> dict[str, Any] | None:
        for entry, rx in self._compiled:
            if entry.get("service") not in (None, service):
                continue
            if rx.search(sig):
                return entry
        return None


def classify(service: str, sig: str, expected: Expected,
             level_num: int = 0, has_level: bool = True,
             has_errword: bool = True) -> tuple[str, str]:
    """Return (verdict, reason). Order matters: misclassification wins.

    A row that is really INFO must not be filed as an app bug even if it also
    matches an `expected` pattern -- the pipeline fix changes its severity and
    the expected entry then becomes dead.

    level_num / has_level / has_errword come from the RAW body (see the *_EXPR
    constants); they cannot be recovered from the normalised signature. They
    default to the conservative values, so a caller that does not supply them
    gets the old text-only behaviour rather than silent over-suppression.
    """
    error_wins = bool(ERROR_WINS.search(sig))

    # Numeric levels (pino/bunyan): 10 trace, 20 debug, 30 info, 40 warn,
    # 50 error, 60 fatal. Anything under 50 is not an error.
    if level_num and level_num < 50 and not error_wins:
        return "misclassified", f"body_says_numeric_level_{level_num}"

    for name, pattern in MISCLASSIFIED_RULES:
        if re.search(pattern, sig):
            if error_wins:
                break  # an explicit error level outranks any info/warn marker
            return "misclassified", name

    # Last resort, deliberately conservative: the body declares NO level in any
    # convention AND contains no error vocabulary at all. Requiring the ABSENCE
    # of error words rather than the PRESENCE of progress words is what keeps
    # this from suppressing real failures -- measured on a live hour, it selects
    # 356 rows/h (alertmanager-config render banners, crowdsec-web-ui sync
    # progress) while 1,098 rows that also lack a level but DO carry error
    # vocabulary stay `real`.
    if not has_level and not has_errword:
        return "misclassified", "no_declared_level_and_no_error_vocabulary"
    hit = expected.match(service, sig)
    if hit:
        return "expected", hit.get("why", "listed in expected.yaml")
    return "real", "no rule matched"


# ── census ────────────────────────────────────────────────────────────────────
def collect(window_h: int) -> dict[str, Any]:
    services = [
        {"service": r[0], "errors": int(r[1]), "per_sec": round(int(r[1]) / (window_h * 3600), 4),
         "namespace": r[2] if len(r) > 2 else ""}
        for r in tsv(f"""
            SELECT ServiceName, count(), any(ResourceAttributes['k8s.namespace.name'])
            FROM default.otel_logs
            WHERE TimestampTime > now() - INTERVAL {window_h} HOUR
              AND SeverityText IN ({_sev_list()})
            GROUP BY ServiceName ORDER BY count() DESC""")
    ]
    sigs = [
        {"service": r[0], "sig": r[1], "count": int(r[2]),
         "level_num": int(r[3]), "has_level": r[4] == "1", "has_errword": r[5] == "1"}
        for r in tsv(f"""
            SELECT ServiceName, {SIG_EXPR} AS sig, count(),
                   {LEVEL_NUM_EXPR}, {HAS_LEVEL_EXPR}, {HAS_ERRWORD_EXPR}
            FROM default.otel_logs
            WHERE TimestampTime > now() - INTERVAL {window_h} HOUR
              AND SeverityText IN ({_sev_list()})
            GROUP BY ServiceName, sig ORDER BY count() DESC""")
        if len(r) >= 6
    ]
    expected = Expected.load(EXPECTED_FILE)
    for s in sigs:
        s["sig_id"] = sig_id(s["service"], s["sig"])
        s["verdict"], s["reason"] = classify(
            s["service"], s["sig"], expected,
            s["level_num"], s["has_level"], s["has_errword"])
    return {
        "window_hours": window_h,
        "captured_utc": _dt.datetime.now(_dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "total_errors": sum(s["errors"] for s in services),
        "services": services,
        "signatures": sigs,
    }


def load_artifact(path: Path | None) -> dict[str, Any]:
    if path:
        return json.loads(path.read_text())
    snaps = sorted(BASELINE_DIR.glob("census-*.json"))
    if not snaps:
        raise SystemExit(red("no artifact given and baseline/ is empty — run `census --save` first"))
    return json.loads(snaps[-1].read_text())


# ── commands ──────────────────────────────────────────────────────────────────
def cmd_census(args) -> int:
    data = collect(args.window)
    print(bold("mega-log-analysis · census"))
    print("-" * 72)
    print(f"window {args.window}h · captured {data['captured_utc']}")
    print(f"{bold('total errors')} {data['total_errors']:,} "
          f"({data['total_errors'] / (args.window * 3600):.2f}/sec) "
          f"across {len(data['services'])} services\n")
    print(f"  {'errors':>8}  {'/sec':>7}  service")
    for s in data["services"][: args.top]:
        print(f"  {s['errors']:>8,}  {s['per_sec']:>7.3f}  {s['service']}  {dim(s['namespace'])}")
    if len(data["services"]) > args.top:
        print(dim(f"  … {len(data['services']) - args.top} more"))
    if args.save:
        BASELINE_DIR.mkdir(exist_ok=True)
        out = BASELINE_DIR / f"census-{now_utc()}.json"
        out.write_text(json.dumps(data, indent=2) + "\n")
        print(f"\n{green('saved')} {out.relative_to(REPO_ROOT)}")
    return 0


def cmd_signatures(args) -> int:
    data = collect(args.window) if args.refresh else load_artifact(args.artifact)
    sigs = sorted(data["signatures"], key=lambda s: -s["count"])
    if args.service:
        sigs = [s for s in sigs if s["service"] in args.service]
    if not sigs:
        print(yellow("no signatures match"))
        return 0
    total = sum(s["count"] for s in sigs)
    keep = [s for s in sigs if s["count"] >= args.min_count]
    print(bold("mega-log-analysis · signatures"))
    print("-" * 72)
    covered = sum(s["count"] for s in keep)
    print(f"{len(sigs)} signatures · {len(keep)} at >={args.min_count}/window "
          f"covering {covered / total * 100:.1f}% of {total:,} errors\n")
    for s in keep[: args.top]:
        mark = {"real": red("REAL"), "misclassified": yellow("MISC"),
                "expected": dim("EXPD")}[s["verdict"]]
        print(f"  {s['count']:>7,}  {mark}  {cyan(s['service'])}  {dim(s['sig_id'])}")
        print(f"           {s['sig'][:110]}")
    return 0


def cmd_triage(args) -> int:
    data = collect(args.window) if args.refresh else load_artifact(args.artifact)
    sigs = data["signatures"]
    total = sum(s["count"] for s in sigs) or 1
    by_verdict: dict[str, int] = {}
    by_reason: dict[str, int] = {}
    for s in sigs:
        by_verdict[s["verdict"]] = by_verdict.get(s["verdict"], 0) + s["count"]
        by_reason[s["reason"]] = by_reason.get(s["reason"], 0) + s["count"]
    print(bold("mega-log-analysis · triage"))
    print("-" * 72)
    for v in ("real", "misclassified", "expected"):
        n = by_verdict.get(v, 0)
        colour = {"real": red, "misclassified": yellow, "expected": dim}[v]
        print(f"  {colour(v.ljust(14))} {n:>8,}  {n / total * 100:>5.1f}%")
    print(f"\n  {dim('why')}")
    for reason, n in sorted(by_reason.items(), key=lambda kv: -kv[1])[:10]:
        print(f"    {n:>8,}  {reason}")
    actionable = [s for s in sigs if s["verdict"] == "real" and s["count"] >= args.min_count]
    print(f"\n  {bold('actionable')}: {len(actionable)} signatures at >={args.min_count}, "
          f"{len({s['service'] for s in actionable})} services")
    return 0


def _service_tier(data: dict[str, Any], min_errors: int) -> list[dict[str, Any]]:
    """Services that earn their own sub-epic: real errors at or above the floor."""
    per_service: dict[str, dict[str, Any]] = {}
    for s in data["signatures"]:
        if s["verdict"] != "real":
            continue
        e = per_service.setdefault(s["service"], {"service": s["service"], "errors": 0, "sigs": []})
        e["errors"] += s["count"]
        e["sigs"].append(s)
    ns = {s["service"]: s.get("namespace", "") for s in data["services"]}
    out = [dict(e, namespace=ns.get(e["service"], ""))
           for e in per_service.values() if e["errors"] >= min_errors]
    return sorted(out, key=lambda e: -e["errors"])


def cmd_tickets(args) -> int:
    """Emit the L1/L2/L3 tree as a plan. Dry-run unless --apply.

    IDEMPOTENT BY SIGNATURE ID: every leaf description embeds `sig:<id>`, and a
    re-run searches beads for that marker before filing. Without it, re-running
    this against a later window would duplicate the whole tree.
    """
    data = load_artifact(args.artifact)
    tier = _service_tier(data, args.min_errors)
    print(bold("mega-log-analysis · tickets"))
    print("-" * 72)
    print(f"from {data['captured_utc']} · window {data['window_hours']}h")
    print(f"{len(tier)} service sub-epics at >={args.min_errors} real errors/window\n")

    existing = _existing_sig_ids() if (args.apply or args.check_existing) else set()
    new_leaves = 0
    for svc in tier:
        leaves = [s for s in svc["sigs"] if s["count"] >= args.min_count]
        print(f"  {bold('L2')} {cyan(svc['service']):<36} {svc['errors']:>7,} err  "
              f"{dim(svc['namespace'])}")
        for leaf in leaves:
            fresh = leaf["sig_id"] not in existing
            new_leaves += fresh
            state = green("(new)") if fresh else dim("(exists)")
            print(f"       {bold('L3')} {leaf['count']:>7,}  {leaf['sig_id']}  {state}")
            print(f"            {dim(leaf['sig'][:96])}")
    print(f"\n  {len(tier)} sub-epics · {new_leaves} new leaf tickets")
    if not args.apply:
        print(dim("  dry run — pass --apply to create them"))
    else:
        # Deliberately not wired: the operator reviews the L2 list before any
        # tree is created, and propose-only is the standing rule for this
        # campaign. Flipping this on is its own reviewed change.
        print(red("  --apply is not wired: the L2 list is reviewed with the operator first"))
    return 0


def _existing_sig_ids() -> set[str]:
    """Signature ids already filed in beads, so re-runs do not duplicate.

    Uses `bd list --json`, NOT `bd search`. bd search matches TITLES only, so it
    never saw the sig:<id> marker that lives in the description -- the first
    implementation silently reported every already-filed leaf as new. Found by
    re-running `tickets` after creating the tree and getting "23 new" when the
    answer was zero.

    Closed tickets count as filed: a signature that was fixed and closed must
    not reappear as new work on the next census.
    """
    for args in (["bd", "list", "--all", "--json"], ["bd", "list", "--json"]):
        try:
            out = subprocess.run(args, capture_output=True, text=True, timeout=120)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return set()
        if out.returncode == 0 and out.stdout.strip():
            return set(re.findall(r"sig:([0-9a-f]{12})", out.stdout))
    return set()


def cmd_prompt(args) -> int:
    data = load_artifact(args.artifact)
    match = [s for s in data["signatures"] if s["sig_id"] == args.sig_id]
    if not match:
        raise SystemExit(red(f"no signature {args.sig_id} in artifact"))
    s = match[0]
    samples = tsv(f"""
        SELECT substring(Body, 1, 400) FROM default.otel_logs
        WHERE TimestampTime > now() - INTERVAL {data['window_hours']} HOUR
          AND SeverityText IN ({_sev_list()}) AND ServiceName = '{s['service']}'
          AND {SIG_EXPR} = '{s['sig'].replace("'", "''")}'
        LIMIT 3""")
    body = "\n".join("  " + r[0][:400] for r in samples) or "  (no sample retrieved)"
    print(f"""You are diagnosing ONE error signature in the talos-homelab Kubernetes cluster.

SERVICE:   {s['service']}
SIGNATURE: {s['sig']}
RATE:      {s['count']} occurrences in the last {data['window_hours']}h
SIG_ID:    {s['sig_id']}

SAMPLE BODIES:
{body}

YOUR TASK
1. Find the root cause. Query ClickHouse for more context if needed:
   kubectl -n {CH_NS} exec {CH_POD} -- clickhouse-client -q "<sql>"
2. Locate the owning manifest in the repo.
3. Propose a concrete patch.

HARD CONSTRAINTS
- PROPOSE ONLY. Make NO commits and NO cluster changes. This is a live GitOps
  cluster; a bad manifest reconciles fleet-wide.
- If the cause is genuinely unclear, say so and STOP. Do not guess. Mark the
  finding `needs-decision` and state exactly what you would need to resolve it.
- Verify every claim against the cluster or the repo. "Probably" is not a
  diagnosis, and an empty result is not proof of absence.

RETURN: root cause · evidence · exact file and change proposed · expected
error-rate change · confidence · whether it needs an operator decision.""")
    return 0


def cmd_burndown(args) -> int:
    base = json.loads(Path(args.baseline).read_text()) if args.baseline else load_artifact(None)
    cur = collect(base["window_hours"])
    b = {s["service"]: s["errors"] for s in base["services"]}
    c = {s["service"]: s["errors"] for s in cur["services"]}
    print(bold("mega-log-analysis · burndown"))
    print("-" * 72)
    print(f"baseline {base['captured_utc']}  ->  now {cur['captured_utc']}")
    delta = cur["total_errors"] - base["total_errors"]
    pct = delta / base["total_errors"] * 100 if base["total_errors"] else 0.0
    arrow = green(f"{delta:+,} ({pct:+.1f}%)") if delta < 0 else red(f"{delta:+,} ({pct:+.1f}%)")
    print(f"total {base['total_errors']:,} -> {cur['total_errors']:,}   {arrow}\n")
    for svc in sorted(set(b) | set(c), key=lambda s: (c.get(s, 0) - b.get(s, 0)))[: args.top]:
        d = c.get(svc, 0) - b.get(svc, 0)
        if d == 0:
            continue
        mark = green(f"{d:+,}") if d < 0 else red(f"{d:+,}")
        print(f"  {b.get(svc, 0):>7,} -> {c.get(svc, 0):>7,}  {mark:>18}  {svc}")
    return 0


def cmd_selftest(args) -> int:
    """Prove every classifier can fire.

    Repo gotcha #11: a check that reports success is not a check that ran. Each
    rule gets a positive fixture that MUST trip it and a negative control that
    must NOT -- a classifier matching everything would pass the positive half
    alone. An unrunnable case fails; it is never skipped into a green result.
    """
    ok = True

    def say(good: bool, label: str, msg: str) -> None:
        nonlocal ok
        print(f"  {green('PASS') if good else red('FAIL')} {label}: {msg}")
        if not good:
            ok = False

    expected = Expected.load(EXPECTED_FILE)

    # 1. Every misclassification rule fires on a real-world shape, taken from
    #    bodies actually measured in this cluster on 2026-10-15.
    positives = {
        "body_says_TRACE": "[<n>m<n>-<n>-<n>T<n>:<n>:<n>Z[<n>m [<n>mTRC[<n>m webhooks/resource",
        "body_says_DEBUG": "[<n>m [<n>mDBG[<n>m reconcile loop",
        "body_says_klog_info": 'I<n> <n>:<n>:<n>.<n> <n> checkpoint_writer.go:<n>] "Saved checkpoint"',
        "body_says_klog_warn": "W<n> <n>:<n>:<n>.<n> <n> reflector.go:<n>] watch closed",
        "body_says_json_info": '{"t":{"$date":"<n>"},"s":"I", "c":"ACCESS","msg":"Connection accepted"}',
        "body_says_json_warn": '{"level":"warn","ts":"<n>","msg":"slow query"}',
        "body_says_logfmt_info": 'time="<n>" level=info msg="<n>.<n>.<n>.<n> - GET /v<n>/decisions"',
        "body_says_logfmt_warn": "ts=<n> caller=x.go:<n> level=warning msg=\"retrying\"",
        "body_says_logfmt_debug": "ts=<n> level=debug component=ruler msg=\"tick\"",
    }
    for rule, sample in positives.items():
        verdict, reason = classify("svc", sample, expected)
        say(verdict == "misclassified" and reason == rule, rule, f"got {verdict}/{reason}")

    # 2. Negative controls: genuine errors must stay `real`. Verbatim shapes from
    #    the cluster, so a regression here is a real miss, not a synthetic one.
    negatives = [
        'ERR error="kubernetes service not found: catalyst-llm/sillytavern"',
        'E<n> <n>:<n>:<n> controller.go:<n>] "Error retrieving parent object" err="clusters.postgresql.cnpg.io"',
        '{"level":"error","ts":"<n>","msg":"Error invoking barman-cloud-check-wal-archive"}',
        "builtins.AttributeError: 'Server' object has no attribute 'socket'",
        # The ERROR_WINS guard: mimir wraps an inner info-level component field
        # inside an outer error line. Without the guard the logfmt rule would
        # swallow this and a real error would vanish from the campaign.
        "ts=<n> caller=handler.go:<n> level=error component=MultiTenantAlertmanager level=info",
    ]
    for sample in negatives:
        verdict, _ = classify("svc", sample, expected)
        say(verdict == "real", "negative-control", f"{verdict} <- {sample[:56]}")

    # 2b. Numeric levels (pino). 30 is info and must be caught; 50 is error and
    #     must NOT be, or clickstack's genuine failures disappear with its noise.
    v, r = classify("clickstack", '[ALERT-TASK] {"level":<n>,"msg":"x"}', expected, level_num=30)
    say(v == "misclassified" and r == "body_says_numeric_level_30", "numeric-level-30", r)
    v, _ = classify("clickstack", '[ALERT-TASK] {"level":<n>,"msg":"x"}', expected, level_num=50)
    say(v == "real", "numeric-level-50-stays-real", v)

    # 2c. The no-declared-level heuristic, and the guard that makes it safe.
    v, r = classify("svc", "== rendering alertmanager config ==", expected,
                    has_level=False, has_errword=False)
    say(v == "misclassified" and r == "no_declared_level_and_no_error_vocabulary",
        "no-level-no-errword", r)
    v, _ = classify("svc", "could not reach upstream: connection refused", expected,
                    has_level=False, has_errword=True)
    say(v == "real", "no-level-BUT-errword-stays-real", v)

    # 3. The signature id must be stable across counts and unique per service, or
    #    `tickets` either duplicates on every run or collides across services.
    a = sig_id("traefik", "service not found")
    say(a == sig_id("traefik", "service not found"), "sig_id-stable", a)
    say(a != sig_id("goldilocks", "service not found"), "sig_id-per-service", "differs")

    # 4. expected.yaml must parse and every entry must carry its evidence.
    for e in expected.entries:
        has_why = bool(e.get("why")) and bool(e.get("pattern"))
        say(has_why, "expected-entry",
            f"{str(e.get('pattern'))[:40]} -> {'has why' if e.get('why') else red('NO why')}")
    if not expected.entries:
        print(f"  {dim('note')} expected.yaml has no entries — nothing is being suppressed")

    print(f"\n{green('selftest OK') if ok else red('selftest FAILED')}")
    return 0 if ok else 1


# ── cli ───────────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mega-log-analysis", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def window(p):
        p.add_argument("--window", type=int, default=1, help="hours to analyse (default 1)")

    def artifact(p):
        p.add_argument("--artifact", type=Path, help="census JSON (default: newest in baseline/)")
        p.add_argument("--refresh", action="store_true", help="query live instead of an artifact")

    p = sub.add_parser("census", help="errors per service for a window")
    window(p)
    p.add_argument("--top", type=int, default=25)
    p.add_argument("--save", action="store_true", help="write a baseline/ snapshot")
    p.set_defaults(func=cmd_census)

    p = sub.add_parser("signatures", help="cluster bodies into signatures per service")
    window(p)
    artifact(p)
    p.add_argument("--service", nargs="*", help="limit to these services")
    p.add_argument("--min-count", type=int, default=60, help="floor per window (default 60)")
    p.add_argument("--top", type=int, default=30)
    p.set_defaults(func=cmd_signatures)

    p = sub.add_parser("triage", help="classify signatures misclassified/expected/real")
    window(p)
    artifact(p)
    p.add_argument("--min-count", type=int, default=60)
    p.set_defaults(func=cmd_triage)

    p = sub.add_parser("tickets", help="emit the beads L1/L2/L3 tree from an artifact")
    p.add_argument("--artifact", type=Path)
    p.add_argument("--min-errors", type=int, default=60, help="floor for a service sub-epic")
    p.add_argument("--min-count", type=int, default=60, help="floor for a signature leaf")
    p.add_argument("--check-existing", action="store_true", help="query bd for already-filed ids")
    p.add_argument("--apply", action="store_true", help="actually create the tickets")
    p.set_defaults(func=cmd_tickets)

    p = sub.add_parser("prompt", help="emit the swarm agent prompt for one signature")
    p.add_argument("sig_id")
    p.add_argument("--artifact", type=Path)
    p.set_defaults(func=cmd_prompt)

    p = sub.add_parser("burndown", help="diff a fresh census against a baseline")
    p.add_argument("--baseline", help="baseline JSON (default: newest in baseline/)")
    p.add_argument("--top", type=int, default=20)
    p.set_defaults(func=cmd_burndown)

    p = sub.add_parser("selftest", help="prove every classifier can fire")
    p.set_defaults(func=cmd_selftest)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
