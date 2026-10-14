#!/usr/bin/env python3
"""helm-values-lint — flag HelmRelease spec.values keys the chart does not define.

Helm silently ignores values at paths a chart never reads. This repo has been
bitten by that four times (tempo, mimir's nginx block, argocd's rbac block,
argocd's resourceTrackingMethod). See README.md for the full scope statement,
including what this checker deliberately does NOT catch.

Two subcommands matter:

  refresh   NETWORK. `helm pull`s every referenced chart, derives a small
            schema fingerprint from it, and writes it under cache/.
  check     OFFLINE. Walks every HelmRelease's spec.values against the cached
            fingerprint and reports keys the chart does not define.

`check` never touches the network. A release whose chart is not in the cache is
reported as SKIPPED and makes the run exit non-zero in --strict mode -- a
missing fingerprint is never a pass.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Iterable

import yaml

TOOL_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOL_DIR.parent.parent
CACHE_DIR = TOOL_DIR / "cache"
ALLOW_FILE = TOOL_DIR / "allow.yaml"

SKIP_DIRS = {
    ".git", ".direnv", ".claude", "node_modules", ".output", ".beads",
    "cache", "testdata",
}

# ── colour ────────────────────────────────────────────────────────────────────
_TTY = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if _TTY else s


def red(s): return _c("31", s)
def yellow(s): return _c("33", s)
def green(s): return _c("32", s)
def dim(s): return _c("2", s)
def bold(s): return _c("1", s)


# ── repo scanning ─────────────────────────────────────────────────────────────
def iter_yaml_files(roots: Iterable[Path]) -> Iterable[Path]:
    for root in roots:
        if root.is_file():
            yield root
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fn in filenames:
                if fn.endswith((".yaml", ".yml")):
                    yield Path(dirpath) / fn


def load_docs(path: Path) -> list[dict]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    # Flux envsubst / go templates make some manifests invalid YAML; skip those
    # rather than crash (they are reported in the summary as unparseable).
    try:
        return [d for d in yaml.safe_load_all(text) if isinstance(d, dict)]
    except yaml.YAMLError:
        return []


class HelmRelease:
    def __init__(self, doc: dict, path: Path):
        self.path = path
        self.doc = doc
        md = doc.get("metadata") or {}
        self.name = md.get("name") or "<unnamed>"
        self.namespace = md.get("namespace") or "default"
        spec = doc.get("spec") or {}
        self.values = spec.get("values")
        self.values_from = spec.get("valuesFrom")
        chart = (spec.get("chart") or {}).get("spec") or {}
        self.chart = chart.get("chart")
        self.version = chart.get("version")
        src = chart.get("sourceRef") or {}
        self.src_kind = src.get("kind")
        self.src_name = src.get("name")
        self.src_ns = src.get("namespace") or self.namespace
        self.chart_ref = spec.get("chartRef")

    @property
    def rel_path(self) -> str:
        try:
            return str(self.path.relative_to(REPO_ROOT))
        except ValueError:
            return str(self.path)


def discover(roots: list[Path]) -> tuple[list[HelmRelease], dict[tuple[str, str], dict]]:
    """Return (helmreleases, {(name, namespace): HelmRepository spec})."""
    releases: list[HelmRelease] = []
    repos: dict[tuple[str, str], dict] = {}
    for p in iter_yaml_files(roots):
        for doc in load_docs(p):
            api = str(doc.get("apiVersion") or "")
            kind = doc.get("kind")
            if kind == "HelmRelease" and api.startswith("helm.toolkit.fluxcd.io"):
                releases.append(HelmRelease(doc, p))
            elif kind == "HelmRepository" and api.startswith("source.toolkit.fluxcd.io"):
                md = doc.get("metadata") or {}
                key = (md.get("name"), md.get("namespace") or "default")
                repos[key] = doc.get("spec") or {}
    releases.sort(key=lambda r: (r.rel_path, r.name))
    return releases, repos


# ── cache fingerprints ────────────────────────────────────────────────────────
def slug(chart: str, version: str) -> str:
    s = f"{chart}@{version}"
    return re.sub(r"[^A-Za-z0-9._@+-]", "_", s)


def cache_path(chart: str, version: str) -> Path:
    return CACHE_DIR / f"{slug(chart, version)}.json"


KIND_MAP = "map"
KIND_MAP_EMPTY = "map-empty"
KIND_LIST = "list"
KIND_NULL = "null"
KIND_SCALAR = "scalar"
OPAQUE_KINDS = {KIND_MAP_EMPTY, KIND_LIST, KIND_NULL, KIND_SCALAR}


def kind_of(v: Any) -> str:
    if isinstance(v, dict):
        return KIND_MAP if v else KIND_MAP_EMPTY
    if isinstance(v, list):
        return KIND_LIST
    if v is None:
        return KIND_NULL
    return KIND_SCALAR


def flatten(values: Any, prefix: str = "", out: dict[str, str] | None = None) -> dict[str, str]:
    """Flatten a chart's default values into {dotted path: kind}."""
    if out is None:
        out = {}
    if not isinstance(values, dict):
        return out
    for k, v in values.items():
        path = f"{prefix}{k}"
        out[path] = kind_of(v)
        if isinstance(v, dict) and v:
            flatten(v, path + ".", out)
    return out


_P = r"([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_-]*)*)"
REF_RE = re.compile(r"\.Values\." + _P)
# A subtree the chart dumps VERBATIM (`toYaml .Values.foo`) is free-form by
# construction: whatever you put under it lands in a rendered config file, so
# the chart's own values.yaml is not an enumeration of the legal keys. This is
# the single biggest false-positive source -- charts routinely ship the real
# options COMMENTED OUT under such a key (tempo's `# s3:` block is exactly
# that). `with`/`range`/`omit`/alias uses are deliberately NOT treated this
# way: those re-read individual fields, so an unknown key under them really can
# be dead (traefik's `service.type` and mimir's `gateway.enabledNonEnterprise`
# are both found through a `with`-consumed parent).
DUMP_RES = [
    re.compile(r"to(?:Yaml|Json)\s+\(?\.Values\." + _P),
    re.compile(r"\.Values\." + _P + r"\s*\|\s*to(?:Yaml|Json)"),
]
# `{{- with .Values.foo }} ... {{- toYaml . | nindent 4 }}` is the same verbatim
# dump written the other way round, and it is the idiom Loki uses for every
# section of its generated config.
#
# The test is deliberately narrow: the VERY NEXT template action after the
# `with` must be the dot-dump. A wider look-ahead window was tried first and
# over-suppressed badly -- any `{{- with .Values.<component> }}` wrapping a
# whole Deployment has some unrelated `toYaml .` a few lines down, which hid
# two real findings (mimir's gateway.enabledNonEnterprise and argocd's
# applicationSet.enabled). Requiring adjacency keeps those.
WITH_RE = re.compile(r"\b(?:with|range)\b[^}]*?\.Values\." + _P)
ACTION_RE = re.compile(r"\{\{(.*?)\}\}", re.S)
# `toYaml .` / `. | toYaml` / `tpl (. | toYaml) $` -- the dot must stand ALONE.
# `toYaml .annotations` is NOT a whole-subtree dump, and an earlier version that
# matched it suppressed mimir's gateway.enabledNonEnterprise.
DOT_DUMP_RE = re.compile(
    r"to(?:Yaml|Json)\s+[.$](?![A-Za-z0-9_])"
    r"|(?<![A-Za-z0-9_.])\.\s*\|\s*to(?:Yaml|Json)"
)


def _template_files(chart_dir: Path) -> Iterable[Path]:
    """Every file in THIS chart that can contain a `.Values.` reference.

    Deliberately does NOT descend into charts/ -- a subchart's `.Values.rbac`
    means the SUBCHART's rbac, which from the parent is `<alias>.rbac`. Mixing
    the two namespaces is not a theoretical problem: argo-cd bundles redis-ha,
    whose templates read `.Values.rbac.create`, and that alone was enough to
    suppress the known-dead top-level `rbac` block this whole ticket is about.
    Subcharts are scanned separately, with their root as a prefix.

    values.yaml is included on purpose: loki and tempo ship their application
    config as a `tpl`-rendered STRING inside values.yaml, so
    `.Values.loki.limits_config` and `.Values.tempo.storage` are dumped from
    there and appear nowhere under templates/.

    NOTES.txt is excluded: it renders the post-install message, never a
    resource, so a `.Values.x` there is not a functional read of x. Scanning it
    suppressed mimir's dead `nginx:` block, whose only mention anywhere in the
    chart is a legacy `$gateway := .Values.nginx` in NOTES.txt.
    """
    for sub in chart_dir.rglob("*"):
        if not sub.is_file():
            continue
        if sub.suffix not in (".tpl", ".yaml", ".yml", ".txt", ".json"):
            continue
        if sub.name == "NOTES.txt":
            continue
        rel = sub.relative_to(chart_dir).parts
        if "charts" in rel:
            continue
        if "templates" in rel or "files" in rel:
            yield sub
        elif sub.name in ("values.yaml", "values.yml") and len(rel) == 1:
            yield sub


def template_refs(chart_dir: Path, prefix: str = "") -> tuple[set[str], set[str]]:
    """Scan one chart's own files.

    Returns (refs, dumps):
      refs  -- every `.Values.<dotted.path>` mentioned, prefixed.
      dumps -- the subset dumped verbatim (toYaml/toJson of the whole subtree).

    Both are only ever used to SUPPRESS findings, so looseness here can reduce
    findings but never invent them.
    """
    refs: set[str] = set()
    dumps: set[str] = set()
    for sub in _template_files(chart_dir):
        try:
            text = sub.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in REF_RE.finditer(text):
            refs.add(prefix + m.group(1))
        for rx in DUMP_RES:
            for m in rx.finditer(text):
                dumps.add(prefix + m.group(1))
        for m in WITH_RE.finditer(text):
            close = text.find("}}", m.end())
            if close < 0:
                continue
            nxt = ACTION_RE.search(text, close + 2)
            if nxt and DOT_DUMP_RE.search(nxt.group(1)):
                dumps.add(prefix + m.group(1))
    return refs, dumps


def build_fingerprint(chart_dir: Path, meta: dict) -> dict:
    values_file = chart_dir / "values.yaml"
    defaults = {}
    if values_file.exists():
        defaults = yaml.safe_load(values_file.read_text(encoding="utf-8")) or {}
    paths = flatten(defaults)

    chart_yaml = {}
    cy = chart_dir / "Chart.yaml"
    if cy.exists():
        chart_yaml = yaml.safe_load(cy.read_text(encoding="utf-8")) or {}

    # Subchart roots. A dependency's values live under its alias (or name), and
    # the parent's values.yaml often does not mention it at all -- so without
    # this, every `minio:` / `redis:` block in a parent release is a false
    # positive. Bundled subcharts get flattened in under their root; unbundled
    # ones become opaque roots.
    deps = []
    sub_scan: list[tuple[set[str], set[str]]] = []
    for dep in chart_yaml.get("dependencies") or []:
        if not isinstance(dep, dict):
            continue
        root = dep.get("alias") or dep.get("name")
        if not root:
            continue
        deps.append(root)
        sub_dir = chart_dir / "charts" / (dep.get("name") or root)
        sub_values = sub_dir / "values.yaml"
        if sub_values.exists():
            sub_defaults = yaml.safe_load(sub_values.read_text(encoding="utf-8")) or {}
            paths.setdefault(root, KIND_MAP)
            flatten(sub_defaults, root + ".", paths)
            sub_refs, sub_dumps = template_refs(sub_dir, root + ".")
            sub_scan.append((sub_refs, sub_dumps))
        else:
            # Cannot enumerate it -> opaque root, never descended into.
            paths.setdefault(root, KIND_MAP_EMPTY)

    # `global` is a Helm built-in shared with every subchart and is valid even
    # when a chart's values.yaml never declares it.
    paths.setdefault("global", KIND_MAP_EMPTY)

    refs, dumps = template_refs(chart_dir)
    for sub_refs, sub_dumps in sub_scan:
        refs |= sub_refs
        dumps |= sub_dumps
    return {
        **meta,
        "appVersion": chart_yaml.get("appVersion"),
        "dependencies": sorted(set(deps)),
        "has_schema": (chart_dir / "values.schema.json").exists(),
        "path_count": len(paths),
        "paths": dict(sorted(paths.items())),
        "refs": sorted(refs),
        "dumps": sorted(dumps),
    }


def helm_version() -> str:
    try:
        return subprocess.run(
            ["helm", "version", "--short"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def helm_env(home: Path) -> dict:
    """An isolated HELM_* home.

    Deliberate: `helm pull --repo <url>` still reads the caller's repository
    list, so a single broken entry in the operator's `helm repo list` (one
    unreachable index.yaml) makes every pull fail. Pinning the whole helm home
    into a scratch dir makes `refresh` hermetic and reproducible on any machine
    and in CI.
    """
    env = dict(os.environ)
    env.update({
        "HELM_CACHE_HOME": str(home / "cache"),
        "HELM_CONFIG_HOME": str(home / "config"),
        "HELM_DATA_HOME": str(home / "data"),
        "HELM_REPOSITORY_CONFIG": str(home / "config" / "repositories.yaml"),
        "HELM_REPOSITORY_CACHE": str(home / "cache" / "repository"),
    })
    for k in ("HELM_CACHE_HOME", "HELM_CONFIG_HOME", "HELM_DATA_HOME"):
        Path(env[k]).mkdir(parents=True, exist_ok=True)
    Path(env["HELM_REPOSITORY_CACHE"]).mkdir(parents=True, exist_ok=True)
    return env


def pull_chart(repo_url: str, repo_type: str, chart: str, constraint: str | None,
               dest: Path, env: dict) -> tuple[Path, str]:
    """helm pull + untar. Returns (chart_dir, resolved_version)."""
    args = ["helm", "pull", "--untar", "--untardir", str(dest)]
    if repo_type == "oci":
        args.append(f"{repo_url.rstrip('/')}/{chart}")
    else:
        args += [chart, "--repo", repo_url]
    if constraint:
        args += ["--version", constraint]
    proc = subprocess.run(args, capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip().splitlines()[-1]
                           if (proc.stderr or proc.stdout).strip() else "helm pull failed")
    base = chart.split("/")[-1]
    chart_dir = dest / base
    if not chart_dir.is_dir():
        candidates = [d for d in dest.iterdir() if d.is_dir()]
        if len(candidates) != 1:
            raise RuntimeError(f"could not locate untarred chart in {dest}")
        chart_dir = candidates[0]
    cy = yaml.safe_load((chart_dir / "Chart.yaml").read_text(encoding="utf-8")) or {}
    return chart_dir, str(cy.get("version"))


def cmd_refresh(args) -> int:
    releases, repos = discover([REPO_ROOT / r for r in args.roots])
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    hv = helm_version()
    now = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()

    # Deduplicate: two releases of the same chart+constraint share a fingerprint.
    wanted: dict[tuple[str, str, str, str | None], list[str]] = {}
    skipped: list[tuple[str, str]] = []
    for r in releases:
        if args.only and r.name not in args.only:
            continue
        if r.chart_ref is not None:
            skipped.append((r.name, "uses spec.chartRef (not a HelmRepository chart)"))
            continue
        if r.src_kind != "HelmRepository":
            skipped.append((r.name, f"sourceRef kind {r.src_kind} is not supported"))
            continue
        spec = repos.get((r.src_name, r.src_ns))
        if spec is None:
            skipped.append((r.name, f"HelmRepository {r.src_ns}/{r.src_name} not in repo"))
            continue
        key = (spec.get("url"), spec.get("type", "default"), r.chart, r.version)
        wanted.setdefault(key, []).append(r.name)

    failures: list[tuple[str, str]] = []
    written = 0
    helm_home = Path(tempfile.mkdtemp(prefix="hvl-helm-home-"))
    env = helm_env(helm_home)
    for (url, rtype, chart, constraint), names in sorted(wanted.items(), key=lambda kv: kv[0][2]):
        label = f"{chart} ({constraint or 'latest'})"
        with tempfile.TemporaryDirectory() as td:
            try:
                chart_dir, resolved = pull_chart(url, rtype, chart, constraint, Path(td), env)
            except (RuntimeError, OSError) as e:
                print(f"  {red('FAIL')} {label}: {e}")
                failures.append((chart, str(e)))
                continue
            meta = {
                "chart": chart,
                "version": resolved,
                "constraint": constraint,
                "repo": url,
                "repo_type": rtype,
                "releases": sorted(names),
                "fetched": now,
                "helm": hv,
            }
            fp = build_fingerprint(chart_dir, meta)
        out = cache_path(chart, resolved)
        out.write_text(json.dumps(fp, indent=2, sort_keys=False) + "\n", encoding="utf-8")
        written += 1
        print(f"  {green('ok')}   {label} -> {out.name} "
              f"({fp['path_count']} paths, {len(fp['refs'])} refs, "
              f"{len(fp['dumps'])} verbatim-dumped subtrees)")

    if args.prune:
        # A fingerprint is live if any HelmRelease still in the repo named it.
        live = {r.name for r in releases}
        for f in sorted(CACHE_DIR.glob("*.json")):
            try:
                fp = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not (set(fp.get("releases") or []) & live):
                print(f"  {yellow('prune')} {f.name}")
                f.unlink()

    shutil.rmtree(helm_home, ignore_errors=True)
    print()
    print(f"{written} fingerprint(s) written to {CACHE_DIR.relative_to(REPO_ROOT)}")
    for name, why in skipped:
        print(f"  {dim('skip')} {name}: {why}")
    for chart, why in failures:
        print(f"  {red('fail')} {chart}: {why}")
    return 1 if failures else 0


# ── allowlist ─────────────────────────────────────────────────────────────────
class Allow:
    def __init__(self, data: dict):
        self.releases: dict[str, list[dict]] = data.get("releases") or {}
        self.opaque: list[dict] = data.get("opaque") or []
        self.opaque_leaves: set[str] = set(data.get("opaque_leaf_names") or [])
        self.used: set[tuple[str, str]] = set()

    @classmethod
    def load(cls, path: Path) -> "Allow":
        if not path.exists():
            return cls({})
        return cls(yaml.safe_load(path.read_text(encoding="utf-8")) or {})

    def allowed(self, release: str, path: str) -> str | None:
        for entry in self.releases.get(release, []):
            if entry.get("path") == path:
                self.used.add((release, path))
                return entry.get("reason", "allowlisted")
        return None

    def is_opaque_subtree(self, chart: str, path: str) -> bool:
        """Does an `opaque:` entry cover this path? Used for BOTH known and
        unknown paths."""
        for entry in self.opaque:
            if entry.get("chart") not in (None, chart):
                continue
            p = entry.get("path")
            if p and (path == p or path.startswith(p + ".")):
                return True
        return False

    def is_opaque(self, chart: str, path: str, leaf: str) -> bool:
        """Should the walk stop DESCENDING at this path?

        `opaque_leaf_names` is consulted here and ONLY here: it must never
        suppress an UNKNOWN key. `resources` is in that list so that
        `resources.limits` is not flagged on a chart whose values.yaml only
        shows `resources.requests` -- but kyverno's
        `admissionController.resources` is itself an unknown key (the chart
        nests it at admissionController.container.resources) and is a real,
        measured defect. An earlier version applied the leaf list in the unknown
        branch too and hid exactly that finding."""
        return leaf in self.opaque_leaves or self.is_opaque_subtree(chart, path)

    def unused(self) -> list[tuple[str, str]]:
        out = []
        for rel, entries in self.releases.items():
            for e in entries:
                key = (rel, e.get("path"))
                if key not in self.used:
                    out.append(key)
        return out


# ── the check ─────────────────────────────────────────────────────────────────
class Finding:
    def __init__(self, release: str, rel_path: str, chart: str, version: str,
                 path: str, cls: str, detail: str = ""):
        self.release = release
        self.file = rel_path
        self.chart = chart
        self.version = version
        self.path = path
        self.cls = cls          # "UNKNOWN" | "TYPE"
        self.detail = detail


def load_cache() -> dict[tuple[str, str], dict]:
    """{(chart, version-or-constraint-key): fingerprint}, indexed by chart name."""
    by_chart: dict[str, list[dict]] = {}
    for p in sorted(CACHE_DIR.glob("*.json")):
        try:
            fp = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        by_chart.setdefault(fp["chart"], []).append(fp)
    return by_chart


def pick_fingerprint(by_chart: dict[str, list[dict]], hr: HelmRelease) -> dict | None:
    cands = by_chart.get(hr.chart or "", [])
    if not cands:
        return None
    # exact version pin wins; otherwise match on the recorded constraint;
    # otherwise the single cached fingerprint for this chart.
    for fp in cands:
        if fp.get("version") == hr.version:
            return fp
    for fp in cands:
        if fp.get("constraint") == hr.version:
            return fp
    return cands[0] if len(cands) == 1 else None


def walk_values(hr: HelmRelease, fp: dict, allow: Allow, findings: list[Finding],
                suppressed: list[Finding]) -> None:
    paths: dict[str, str] = fp["paths"]
    refs: set[str] = set(fp.get("refs") or [])
    dumps: set[str] = set(fp.get("dumps") or [])
    chart = fp["chart"]

    def referenced(path: str) -> bool:
        return any(r == path or r.startswith(path + ".") for r in refs)

    def ancestors(path: str) -> list[str]:
        segs = path.split(".")
        return [".".join(segs[:i]) for i in range(1, len(segs))]

    def under_dump(path: str) -> str | None:
        for a in ancestors(path):
            if a in dumps:
                return a
        return None

    def aliased_parent(path: str) -> str | None:
        """Deepest ancestor the chart mentions bare (`{{ with .Values.X }}`,
        `$v := .Values.X`, `include ... .Values.X`). Not a suppressor -- just a
        flag that the subtree is re-read through something this checker cannot
        follow, so the finding deserves a human look."""
        for a in reversed(ancestors(path)):
            if a in refs:
                return a
        return None

    def rec(node: Any, prefix: str) -> None:
        if not isinstance(node, dict):
            return
        for k, v in node.items():
            key = str(k)
            path = f"{prefix}{key}" if prefix else key
            kind = paths.get(path)
            if kind is None:
                f = Finding(hr.name, hr.rel_path, chart, fp["version"], path, "UNKNOWN")
                reason = allow.allowed(hr.name, path)
                dump = under_dump(path)
                if reason:
                    f.detail = f"allowlisted: {reason}"
                    suppressed.append(f)
                elif allow.is_opaque_subtree(chart, path):
                    f.detail = "under an allowlisted free-form subtree"
                    suppressed.append(f)
                elif referenced(path):
                    f.detail = "not in values.yaml but referenced by a chart template"
                    suppressed.append(f)
                elif dump:
                    f.detail = (f".Values.{dump} is dumped verbatim by a template "
                                f"-- subtree is free-form")
                    suppressed.append(f)
                else:
                    alias = aliased_parent(path)
                    if alias:
                        f.detail = (f"VERIFY: .Values.{alias} is read bare by a template "
                                    f"(alias/with/range), so this may still be live")
                    findings.append(f)
                continue
            if allow.is_opaque(chart, path, key) or path in dumps:
                continue
            if kind == KIND_MAP:
                if isinstance(v, dict):
                    rec(v, path + ".")
                elif v is not None:
                    findings.append(Finding(
                        hr.name, hr.rel_path, chart, fp["version"], path, "TYPE",
                        f"chart default is a map, manifest sets {type(v).__name__}"))
            # every other kind is opaque: the chart's default is a scalar, list,
            # null, or an empty map, so its children are free-form by design.

    rec(hr.values, "")


def cmd_check(args) -> int:
    roots = [REPO_ROOT / r for r in args.roots]
    releases, repos = discover(roots)
    if args.only:
        releases = [r for r in releases if r.name in args.only]
    by_chart = load_cache()
    allow = Allow.load(Path(args.allow) if args.allow else ALLOW_FILE)

    findings: list[Finding] = []
    suppressed: list[Finding] = []
    skipped: list[tuple[str, str]] = []
    scanned = 0
    novalues = 0

    for hr in releases:
        if hr.values is None:
            novalues += 1
            continue
        fp = pick_fingerprint(by_chart, hr)
        if fp is None:
            why = (f"no cached fingerprint for chart {hr.chart!r} version {hr.version!r}"
                   if hr.chart else f"no chart.spec.chart (chartRef={hr.chart_ref})")
            skipped.append((f"{hr.name} ({hr.rel_path})", why))
            continue
        scanned += 1
        walk_values(hr, fp, allow, findings, suppressed)

    # ── report ────────────────────────────────────────────────────────────────
    width = shutil.get_terminal_size((100, 24)).columns
    print(bold("helm-values-lint"))
    print("-" * min(width, 72))
    by_release: dict[str, list[Finding]] = {}
    for f in findings:
        by_release.setdefault(f.release, []).append(f)

    for rel in sorted(by_release):
        fs = by_release[rel]
        head = fs[0]
        print(f"\n{red('✗')} {bold(rel)}  {dim(head.file)}")
        print(f"  chart {head.chart} {head.version}")
        for f in sorted(fs, key=lambda x: x.path):
            tag = red("UNKNOWN") if f.cls == "UNKNOWN" else yellow("TYPE   ")
            extra = f"  {dim('— ' + f.detail)}" if f.detail else ""
            print(f"    {tag} spec.values.{f.path}{extra}")

    if args.verbose and suppressed:
        print(f"\n{dim('suppressed (' + str(len(suppressed)) + '):')}")
        for f in sorted(suppressed, key=lambda x: (x.release, x.path)):
            print(dim(f"    {f.release}: spec.values.{f.path} — {f.detail}"))

    print()
    print("-" * min(width, 72))
    print(f"HelmReleases found      : {len(releases)}")
    print(f"  checked               : {scanned}")
    print(f"  no spec.values        : {novalues}")
    print(f"  skipped (no schema)   : {len(skipped)}")
    for name, why in skipped:
        print(f"      {yellow('skip')} {name}: {why}")
    print(f"Findings                : {len(findings)}"
          f"  ({sum(1 for f in findings if f.cls == 'UNKNOWN')} UNKNOWN, "
          f"{sum(1 for f in findings if f.cls == 'TYPE')} TYPE)")
    print(f"Suppressed              : {len(suppressed)}"
          f"  (allowlist + template-referenced; --verbose to list)")

    unused = allow.unused()
    if unused:
        print(f"{yellow('Stale allowlist entries')} : {len(unused)}")
        for rel, path in sorted(unused):
            print(f"      {yellow('stale')} {rel}: {path}")

    rc = 1 if findings else 0
    if args.strict and (skipped or unused):
        rc = 1
    if not findings:
        print(green("\nNo dead value paths — every spec.values key resolves to a path "
                    "its chart defines."))
    if rc and not findings:
        print(yellow("(--strict: failing on the skips/stale entries above.)"))
    return rc


# ── selftest ──────────────────────────────────────────────────────────────────
FIXTURE_MUST_FLAG = {
    "rbac",                      # the real TALOS-o1sb defect shape
    "notAKey",                   # top-level nonsense
    "controller.replicaCountTypo",  # dead leaf under a real parent
}
FIXTURE_MUST_NOT_FLAG = {
    "controller.replicas",           # real chart key
    "controller.resources",          # free-form k8s structure
    "controller.resources.limits",
    "controller.resources.limits.memory",
    "controller.podAnnotations",     # free-form metadata map
    "controller.podAnnotations.prometheus.io/scrape",
    "configs.rbac",                  # real chart key
    "configs.rbac.policy.default",   # real, dotted literal key name
    "configs.cm",                    # allowlisted free-form subtree
    "configs.cm.url",
    "global",                        # Helm built-in
    "global.domain",
}

# The commit that moved argocd's rbac block under `configs` (TALOS-o1sb).
# Checking its parent AND itself turns the historical defect into a regression
# test with a built-in negative control.
ARGOCD_FIX_COMMIT = "d26be8a4"
ARGOCD_HR = "infrastructure/base/argocd/helmrelease.yaml"


def _scan_file(path: Path, by_chart: dict, allow: Allow) -> tuple[set[str], str | None]:
    """Return (flagged paths, error)."""
    findings: list[Finding] = []
    suppressed: list[Finding] = []
    saw = False
    for doc in load_docs(path):
        if doc.get("kind") != "HelmRelease":
            continue
        hr = HelmRelease(doc, path)
        fp = pick_fingerprint(by_chart, hr)
        if fp is None:
            return set(), f"no cached fingerprint for {hr.chart}@{hr.version} — run `refresh`"
        saw = True
        walk_values(hr, fp, allow, findings, suppressed)
    if not saw:
        return set(), f"no HelmRelease parsed from {path}"
    return {f.path for f in findings}, None


def cmd_selftest(args) -> int:
    """Prove the checker fires.

    Repo gotcha #11: a check that reports success is not a check that ran. Three
    cases, and the run FAILS if any of them cannot be executed -- an unrunnable
    case is reported as a failure, never skipped into a green result (the one
    exception is a repo with no git history for the regression commit, which is
    reported as a loud SKIP).
    """
    ok = True

    def say(good: bool, label: str, msg: str) -> None:
        nonlocal ok
        print(f"  {green('PASS') if good else red('FAIL')} {label}: {msg}")
        if not good:
            ok = False

    by_chart = load_cache()
    if not by_chart:
        print(f"  {red('FAIL')} cache is empty — run `task dev:helm-values:refresh` first")
        return 1
    allow = Allow.load(ALLOW_FILE)

    # 1 + 2. Synthetic fixture: it must flag the dead keys AND stay quiet on the
    #        legitimate ones. Both halves matter; a checker that flags
    #        everything would pass the first half alone.
    fixture = TOOL_DIR / "testdata" / "bad-helmrelease.yaml"
    if not fixture.exists():
        say(False, "fixture", f"missing: {fixture}")
    else:
        flagged, err = _scan_file(fixture, by_chart, allow)
        if err:
            say(False, "fixture", err)
        else:
            missing = FIXTURE_MUST_FLAG - flagged
            say(not missing, "fixture fires",
                f"flagged {sorted(flagged & FIXTURE_MUST_FLAG)}" if not missing
                else f"did NOT flag {sorted(missing)} (flagged {sorted(flagged)})")
            noise = FIXTURE_MUST_NOT_FLAG & flagged
            say(not noise, "fixture stays quiet",
                f"{len(FIXTURE_MUST_NOT_FLAG)} legitimate keys not flagged" if not noise
                else f"falsely flagged {sorted(noise)}")

    # 3. Regression against real git history: the argocd rbac defect, and its fix.
    hist = REPO_ROOT / ".git"
    for rev, label, want_rbac in (
        (f"{ARGOCD_FIX_COMMIT}^", "historical argocd (before the fix)", True),
        (ARGOCD_FIX_COMMIT, "historical argocd (after the fix)", False),
    ):
        proc = subprocess.run(["git", "show", f"{rev}:{ARGOCD_HR}"],
                              cwd=REPO_ROOT, capture_output=True, text=True)
        if proc.returncode != 0:
            print(f"  {yellow('SKIP')} {label}: git show {rev} failed "
                  f"(shallow clone or rewritten history?)")
            continue
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "argocd.yaml"
            f.write_text(proc.stdout, encoding="utf-8")
            flagged, err = _scan_file(f, by_chart, allow)
        if err:
            say(False, label, err)
            continue
        has = "rbac" in flagged
        if want_rbac:
            say(has, label, "flagged the dead top-level `rbac` block"
                if has else f"MISSED the known defect (flagged {sorted(flagged)})")
        else:
            say(not has, label, "no longer flags `rbac` — the fix is recognised"
                if not has else "still flags `rbac` after the fix")

    print()
    print(green("selftest OK") if ok else red("selftest FAILED"))
    return 0 if ok else 1


# ── cli ───────────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="helm-values-lint", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--roots", nargs="*",
                       default=["infrastructure", "applications", "clusters"],
                       help="repo-relative directories to scan")
        p.add_argument("--only", nargs="*", help="limit to these HelmRelease names")

    p = sub.add_parser("check", help="offline: lint spec.values against the cache")
    common(p)
    p.add_argument("--allow", help="path to an allowlist (default: allow.yaml)")
    p.add_argument("-v", "--verbose", action="store_true", help="list suppressed findings")
    p.add_argument("--strict", action="store_true",
                   help="also fail on skipped releases and stale allowlist entries")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("refresh", help="NETWORK: helm pull every chart, rebuild cache/")
    common(p)
    p.add_argument("--prune", action="store_true",
                   help="delete cached fingerprints no release references")
    p.set_defaults(func=cmd_refresh)

    p = sub.add_parser("selftest", help="prove the checker fires (fixtures + git history)")
    p.set_defaults(func=cmd_selftest)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
