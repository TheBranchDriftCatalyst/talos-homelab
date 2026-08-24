#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = ["rich>=13.7"]
# ///
"""
Catalyst Cluster — Talos OS Upgrade Orchestrator

A proper, idempotent, parallel-safe Talos OS upgrade with a live UI.

What it does:
  - Discovers cluster nodes and their current Talos versions
  - Computes the upgrade path through intermediate minors (Sidero requires this)
  - Upgrades the control plane first, then all workers in parallel
  - Verifies each node's actual version after upgrade (not just talosctl exit code)
  - Auto-skips nodes already on the target version (handles partial-failure resume)
  - Settles between phases to avoid kubelet-CRI race conditions

Usage:
  ./scripts/upgrade-talos.py v1.13.0
  ./scripts/upgrade-talos.py v1.13.0 --dry-run
  ./scripts/upgrade-talos.py v1.13.0 --settle 60
  ./scripts/upgrade-talos.py v1.13.0 --skip-health-check
  ./scripts/upgrade-talos.py v1.13.0 --only talos06            # retry one node

Override patch versions:
  LATEST_PATCH_1_11=v1.11.5 ./scripts/upgrade-talos.py v1.13.0

Requires:
  - uv installed (https://docs.astral.sh/uv/) — handles the rich dep automatically
  - talosctl + kubectl in PATH
  - ./configs/talosconfig
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Iterable, Optional

from rich.align import Align
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.logging import RichHandler
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text


# ===========================================================================
# Configuration
# ===========================================================================

DEFAULT_TALOSCONFIG = "./configs/talosconfig"
DEFAULT_INSTALLER_BASE = "ghcr.io/siderolabs/installer"
NODE_WAIT_TIMEOUT = 900          # seconds to wait for a node to return Ready
DEFAULT_SETTLE_SECONDS = 30      # delay between phases
UI_REFRESH_PER_SECOND = 4

# Default patch versions per minor (current as of May 2026).
# Override with LATEST_PATCH_1_<MINOR>=v1.<MINOR>.<patch>
# TODO: Might be nice to try and genereate this auto
DEFAULT_PATCH_VERSIONS: dict[int, str] = {
    11: "v1.11.4",
    12: "v1.12.3",
}


# ===========================================================================
# Logging setup — verbose to file, curated to UI
# ===========================================================================

LOG_DIR = Path(".upgrade-logs")
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / f"upgrade-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"


class RecentLogHandler(logging.Handler):
    """In-memory ring buffer of recent log records for the live UI."""

    def __init__(self, maxlen: int = 12):
        super().__init__()
        self.records: deque[str] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        with self._lock:
            self.records.append(msg)

    def lines(self) -> list[str]:
        with self._lock:
            return list(self.records)


def setup_logging() -> RecentLogHandler:
    log = logging.getLogger("talos-upgrade")
    log.setLevel(logging.DEBUG)
    log.propagate = False

    file_h = logging.FileHandler(LOG_FILE)
    file_h.setLevel(logging.DEBUG)
    file_h.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    ))
    log.addHandler(file_h)

    recent = RecentLogHandler(maxlen=12)
    recent.setLevel(logging.INFO)
    recent.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))
    log.addHandler(recent)

    return recent


log = logging.getLogger("talos-upgrade")


# ===========================================================================
# Domain model
# ===========================================================================

class NodeState(str, Enum):
    PENDING = "pending"
    UPGRADING = "upgrading"
    WAITING = "waiting"
    READY = "ready"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass
class Node:
    name: str
    ip: str
    role: str                 # "control-plane" or "worker"
    current_version: str      # e.g. "v1.11.4" or "?"
    target_version: str = ""  # the version we're trying to land on
    state: NodeState = NodeState.PENDING
    last_message: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0
    # Installer image base URL minus version tag, resolved from live machine config.
    # e.g. "ghcr.io/siderolabs/installer" (stock) or
    #      "factory.talos.dev/installer/<schematic-id>" (factory with extensions)
    installer_base: str = ""
    # Desired installer base, resolved from the repo's *-schematic.yaml via
    # factory.talos.dev. If set and != installer_base, we have schematic drift
    # and the node should be re-upgraded with this new URL.
    target_installer_base: str = ""
    # Path to the schematic YAML in repo (if found)
    schematic_path: Optional[Path] = None
    # True if the node's installer is a factory URL (schematic with extensions baked in)
    has_factory_installer: bool = False
    # Extensions reported by the node (post-discovery)
    extensions: list[str] = field(default_factory=list)

    @property
    def is_cp(self) -> bool:
        return self.role == "control-plane"

    @property
    def duration_seconds(self) -> float:
        if not self.started_at:
            return 0
        end = self.finished_at or time.time()
        return end - self.started_at

    def duration_text(self) -> str:
        s = int(self.duration_seconds)
        if s <= 0:
            return ""
        return f"{s // 60}m{s % 60:02d}s"


# ===========================================================================
# Shell wrappers
# ===========================================================================

def run_cmd(cmd: list[str], *, timeout: float = 30, check: bool = False) -> subprocess.CompletedProcess:
    log.debug("$ %s", " ".join(cmd))
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=check)
    except subprocess.TimeoutExpired:
        log.error("command timed out (%ss): %s", timeout, " ".join(cmd))
        raise


def talosctl(*args: str, talosconfig: str = DEFAULT_TALOSCONFIG, timeout: float = 30) -> subprocess.CompletedProcess:
    return run_cmd(["talosctl", "--talosconfig", talosconfig, *args], timeout=timeout)


def kubectl(*args: str, timeout: float = 30) -> subprocess.CompletedProcess:
    return run_cmd(["kubectl", *args], timeout=timeout)


VERSION_TAG_RE = re.compile(r"Tag:\s*(v\S+)")
VERSION_PARSE_RE = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")


def parse_version(v: str) -> Optional[tuple[int, int, int]]:
    m = VERSION_PARSE_RE.match(v)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def version_ge(a: str, b: str) -> bool:
    """Returns True if version `a` is greater than or equal to version `b`."""
    pa, pb = parse_version(a), parse_version(b)
    if pa is None or pb is None:
        return False
    return pa >= pb


def get_talos_version(ip: str) -> Optional[str]:
    """Return the server-reported Talos version for the given node IP, or None."""
    r = talosctl("--nodes", ip, "version")
    if r.returncode != 0:
        return None
    in_server = False
    for line in r.stdout.splitlines():
        if line.strip().startswith("Server:"):
            in_server = True
            continue
        if in_server:
            m = VERSION_TAG_RE.search(line)
            if m:
                return m.group(1)
    return None


def get_node_status(name: str) -> str:
    r = kubectl("get", "node", name, "--no-headers")
    if r.returncode != 0:
        return "Unknown"
    parts = r.stdout.split()
    return parts[1] if len(parts) >= 2 else "Unknown"


# Matches an installer image URL with version tag, e.g.
#   ghcr.io/siderolabs/installer:v1.11.1
#   factory.talos.dev/installer/abc123:v1.11.1
INSTALLER_IMAGE_RE = re.compile(
    r"(?P<base>\S*?/installer(?:/[a-f0-9]+)?):v(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
)


def get_installer_base(ip: str) -> tuple[str, bool]:
    """Return (installer_base, is_factory) from the node's live machine config.

    installer_base is the URL minus the `:vX.Y.Z` tag.  Falls back to the stock
    installer if the field can't be read.
    """
    r = talosctl("--nodes", ip, "get", "machineconfig", "-o", "yaml", timeout=20)
    if r.returncode != 0:
        log.warning("[%s] could not read machineconfig (rc=%d); falling back to stock installer",
                    ip, r.returncode)
        return (DEFAULT_INSTALLER_BASE, False)

    # Find the install.image line.  The YAML structure is:
    #   machine:
    #     install:
    #       image: <URL>:<tag>
    for line in r.stdout.splitlines():
        m = INSTALLER_IMAGE_RE.search(line)
        if m and "kubelet" not in line:
            base = m.group("base")
            is_factory = "factory.talos.dev" in base
            return (base, is_factory)

    log.warning("[%s] no installer image found in machineconfig; falling back to stock", ip)
    return (DEFAULT_INSTALLER_BASE, False)


def get_node_extensions(ip: str) -> list[str]:
    """Return the list of Talos system extensions installed on the node.

    talosctl emits a stream of pretty-printed JSON objects (one per resource),
    NOT one object per line. We parse with raw_decode to walk the stream.
    """
    import json
    r = talosctl("--nodes", ip, "get", "extensions", "-o", "json", timeout=20)
    if r.returncode != 0 or not r.stdout.strip():
        return []
    decoder = json.JSONDecoder()
    names: list[str] = []
    text = r.stdout
    pos = 0
    while pos < len(text):
        # Skip whitespace between objects
        while pos < len(text) and text[pos] in " \t\n\r":
            pos += 1
        if pos >= len(text):
            break
        try:
            doc, end = decoder.raw_decode(text, pos)
        except json.JSONDecodeError:
            break
        name = doc.get("spec", {}).get("metadata", {}).get("name")
        if name:
            names.append(name)
        pos = end
    return names


def discover_cluster(talosconfig: str) -> list[Node]:
    r = kubectl("get", "nodes", "--no-headers", "-o", "wide")
    if r.returncode != 0:
        raise RuntimeError(f"kubectl get nodes failed: {r.stderr.strip()}")

    nodes: list[Node] = []
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) < 6:
            continue
        name, _status, roles, _age, _version, ip = parts[:6]
        role = "control-plane" if "control-plane" in roles else "worker"
        current = get_talos_version(ip) or "?"
        base, is_factory = get_installer_base(ip)
        exts = get_node_extensions(ip)
        nodes.append(Node(
            name=name, ip=ip, role=role,
            current_version=current,
            installer_base=base,
            has_factory_installer=is_factory,
            extensions=exts,
        ))
    return nodes


# ===========================================================================
# Health check
# ===========================================================================

def health_check(nodes: list[Node], cp: Node, talosconfig: str) -> tuple[bool, list[str]]:
    """Returns (ok, issues). Tolerates cordoned state."""
    issues: list[str] = []

    # 1. talosctl health
    log.info("health: talosctl reachability + cluster bootstrap")
    r = talosctl("--nodes", cp.ip, "health", "--server=false", "--wait-timeout=30s", timeout=45)
    talos_ok = r.returncode == 0
    cordon_induced = "expected" in r.stdout and "ready pods" in r.stdout
    all_cordoned = all(
        "SchedulingDisabled" in get_node_status(n.name) for n in nodes
    )
    if talos_ok:
        log.info("health: talosctl healthy")
    elif all_cordoned and cordon_induced:
        log.info("health: talosctl reports a replica-count issue (cordon-induced) — tolerating")
    else:
        msg = "talosctl health failed:\n" + r.stdout.strip()[-400:]
        issues.append(msg)

    # 2. node Ready (cordon OK)
    log.info("health: every node should be Ready (cordon allowed)")
    for n in nodes:
        status = get_node_status(n.name)
        if not status.startswith("Ready"):
            issues.append(f"{n.name} status={status}")
    if not any(i.startswith(n.name + " status") for n in nodes for i in issues):
        log.info("health: all %d nodes Ready", len(nodes))

    # 3. Cilium DaemonSet — the must-have
    log.info("health: cilium DaemonSet")
    r = kubectl("get", "ds", "-n", "kube-system", "cilium", "-o",
                "jsonpath={.status.desiredNumberScheduled},{.status.numberReady}")
    if r.returncode == 0 and "," in r.stdout:
        desired, ready = r.stdout.split(",", 1)
        if desired.strip() and ready.strip() and desired == ready:
            log.info("health: cilium %s/%s ready", ready, desired)
        else:
            issues.append(f"cilium DaemonSet desired={desired} ready={ready}")
    else:
        issues.append("cilium DaemonSet status unreadable")

    # 4. etcd
    log.info("health: etcd status from control plane")
    r = talosctl("--nodes", cp.ip, "etcd", "status", timeout=20)
    if r.returncode == 0:
        log.info("health: etcd reachable")
    else:
        issues.append(f"etcd status failed: {r.stderr.strip()[:200]}")

    # 5. API server responsive
    log.info("health: kube API responsive")
    r = kubectl("version", "--request-timeout=10s", timeout=15)
    if r.returncode != 0:
        issues.append("kube API server not responsive")
    else:
        log.info("health: API responsive")

    # 6. version skew (informational only)
    versions = {n.current_version for n in nodes if n.current_version != "?"}
    if len(versions) > 1:
        log.info("health: nodes span versions %s — upgrade will normalize", ", ".join(sorted(versions)))
    else:
        log.info("health: all nodes on %s", next(iter(versions), "unknown"))

    # 7. Admission webhooks must have healthy backends.
    # See: docs/06-troubleshooting/2026-05-21-cilium-cascading-meltdown.md
    # A broken admission webhook (e.g., opentelemetry-operator with no Ready
    # endpoints) makes apiserver block on every pod create — and during a
    # Talos upgrade we create LOTS of pods.  Catching this before we start
    # prevents cascading meltdowns.
    log.info("health: admission webhook backends")
    broken_webhooks = _find_broken_webhooks()
    if broken_webhooks:
        for w in broken_webhooks:
            issues.append(f"broken admission webhook: {w}")
    else:
        log.info("health: all admission webhooks have healthy endpoints")

    return (len(issues) == 0, issues)


def _find_broken_webhooks() -> list[str]:
    """Return a list of admission webhooks whose service backend has no Ready endpoints.

    A broken webhook will cause apiserver to block on every pod admission, which
    creates a cluster-wide outage waiting to happen.
    """
    import json
    broken: list[str] = []
    for kind in ("mutatingwebhookconfigurations", "validatingwebhookconfigurations"):
        r = kubectl("get", kind, "-o", "json", "--request-timeout=15s", timeout=20)
        if r.returncode != 0:
            continue
        try:
            data = json.loads(r.stdout)
        except json.JSONDecodeError:
            continue
        for cfg in data.get("items", []):
            cfg_name = cfg.get("metadata", {}).get("name", "?")
            for wh in cfg.get("webhooks", []):
                svc_ref = wh.get("clientConfig", {}).get("service")
                if not svc_ref:
                    continue  # URL-based webhook, can't easily check
                ns = svc_ref.get("namespace", "")
                name = svc_ref.get("name", "")
                # Check the service has Ready endpoints
                eps = kubectl("get", "endpoints", "-n", ns, name, "-o", "json", timeout=10)
                if eps.returncode != 0:
                    broken.append(f"{cfg_name}/{wh.get('name','?')} → svc {ns}/{name} (endpoints missing)")
                    continue
                try:
                    ep_data = json.loads(eps.stdout)
                except json.JSONDecodeError:
                    broken.append(f"{cfg_name}/{wh.get('name','?')} → svc {ns}/{name} (endpoints unparseable)")
                    continue
                subsets = ep_data.get("subsets") or []
                # An "addresses" list (not just "notReadyAddresses") means ≥1 Ready
                has_ready = any(s.get("addresses") for s in subsets)
                if not has_ready:
                    fail_policy = wh.get("failurePolicy", "Fail")
                    broken.append(
                        f"{cfg_name}/{wh.get('name','?')} → svc {ns}/{name} "
                        f"(no Ready endpoints, failurePolicy={fail_policy})"
                    )
    return broken


# ===========================================================================
# Upgrade orchestrator
# ===========================================================================

class UpgradeOrchestrator:
    def __init__(
        self,
        target: str,
        *,
        talosconfig: str = DEFAULT_TALOSCONFIG,
        installer_base: str = DEFAULT_INSTALLER_BASE,
        settle_seconds: int = DEFAULT_SETTLE_SECONDS,
        dry_run: bool = False,
        only: Optional[list[str]] = None,
        skip_intermediate: bool = False,
        uncordon_on_success: bool = True,
        update_manifests: bool = True,
        refresh_schematics: bool = True,
        force: bool = False,
        force_drain: bool = False,
    ):
        self.target = target
        self.talosconfig = talosconfig
        self.installer_base = installer_base
        self.settle_seconds = settle_seconds
        self.dry_run = dry_run
        self.only = set(only) if only else None
        self.skip_intermediate = skip_intermediate
        self.uncordon_on_success = uncordon_on_success
        self.update_manifests = update_manifests
        self.refresh_schematics = refresh_schematics
        self.force = force
        self.force_drain = force_drain

        self.nodes: list[Node] = []
        self.cp: Optional[Node] = None
        self.workers: list[Node] = []
        self.path: list[str] = []
        self.start_time = time.time()
        self.current_phase: Optional[str] = None
        self.lock = threading.Lock()
        self.aborted = False

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def discover(self) -> None:
        self.nodes = discover_cluster(self.talosconfig)
        cps = [n for n in self.nodes if n.is_cp]
        if not cps:
            raise RuntimeError("no control-plane node found via kubectl")
        if len(cps) > 1:
            log.warning("found %d control-plane nodes; this tool was designed for single-CP", len(cps))
        self.cp = cps[0]
        self.workers = [n for n in self.nodes if not n.is_cp]

        if self.only:
            log.info("filtering to only: %s", ", ".join(sorted(self.only)))
            self.workers = [w for w in self.workers if w.name in self.only]
            if self.cp.name not in self.only:
                self.cp = None  # don't touch CP if not requested

        log.info("discovered %d nodes (CP: %s, workers: %s)",
                 len(self.nodes),
                 self.cp.name if self.cp else "(none in scope)",
                 ", ".join(w.name for w in self.workers) or "(none in scope)")

        # Pre-flight: report per-node installer + flag schematic mismatches
        log.info("─── per-node installer images ───")
        for n in self.nodes:
            flavor = "factory" if n.has_factory_installer else "stock"
            log.info("  %-14s %s (%s)  extensions: %s",
                     n.name, n.installer_base, flavor,
                     ", ".join(n.extensions) if n.extensions else "(none)")
        self._warn_schematic_mismatches()

    def _warn_schematic_mismatches(self) -> None:
        """Emit a warning for nodes whose live installer disagrees with the
        repo schematic — i.e. running stock when a factory schematic exists,
        or factory URL says extensions but none reported by the node.

        Also stashes the resolved schematic path onto each node for later
        use by resolve_schematics_from_repo().
        """
        configs_dir = Path("configs/nodes")
        if not configs_dir.exists():
            log.info("no configs/nodes dir — skipping schematic-mismatch check")
            return

        for n in self.nodes:
            # Look for a schematic file mentioning this node
            schematics = list(configs_dir.glob(f"**/{n.name}*schematic*.yaml"))
            if not schematics and n.name == "talos02-gpu":
                schematics = list(configs_dir.glob("**/talos02*schematic*.yaml"))
            if not schematics:
                continue

            n.schematic_path = schematics[0]
            content = schematics[0].read_text()
            # Crude but effective: extract extension names from the schematic
            expected = re.findall(r"-\s+siderolabs/([\w-]+)", content)
            if not expected:
                continue

            missing = [e for e in expected if e not in n.extensions]
            if missing:
                log.warning("[%s] schematic expects extensions %s, "
                            "but node has %s — installer URL may be wrong",
                            n.name, expected, n.extensions or "(none)")
            if not n.has_factory_installer and expected:
                log.warning("[%s] schematic expects extensions but installer is stock "
                            "— upgrade will NOT restore extensions unless machine "
                            "config is fixed to point at the factory URL",
                            n.name)

    def resolve_schematics_from_repo(self) -> None:
        """For each node with a *-schematic.yaml in the repo, POST it to
        factory.talos.dev and store the returned schematic ID as the desired
        installer base.  Detects "schematic drift" — when the repo's schematic
        YAML has been updated (e.g., new extension added) but the live machine
        config still references an older schematic ID.

        Sets node.target_installer_base to the correct factory URL.  During
        upgrade, this URL is used instead of node.installer_base (live config).
        """
        if not self.refresh_schematics:
            log.info("--no-refresh-schematics set; using live installer URLs as-is")
            return

        any_resolved = False
        for n in self.nodes:
            if not n.schematic_path:
                continue
            try:
                content = n.schematic_path.read_bytes()
            except OSError as e:
                log.warning("[%s] could not read %s: %s", n.name, n.schematic_path, e)
                continue

            import urllib.request, urllib.error, json
            try:
                req = urllib.request.Request(
                    "https://factory.talos.dev/schematics",
                    data=content,
                    method="POST",
                    headers={"Content-Type": "application/x-yaml"},
                )
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = json.loads(resp.read())
            except (urllib.error.URLError, OSError, ValueError) as e:
                log.warning("[%s] factory.talos.dev POST failed: %s", n.name, e)
                continue

            schematic_id = data.get("id")
            if not schematic_id:
                log.warning("[%s] factory.talos.dev returned no id: %s", n.name, data)
                continue

            target_base = f"factory.talos.dev/installer/{schematic_id}"
            n.target_installer_base = target_base
            any_resolved = True

            if n.installer_base != target_base:
                log.warning(
                    "[%s] schematic drift detected:\n"
                    "    live: %s\n"
                    "    repo: %s\n"
                    "    → will re-upgrade with new schematic",
                    n.name, n.installer_base, target_base
                )
            else:
                short = schematic_id[:12]
                log.info("[%s] schematic up-to-date (%s…)", n.name, short)

        if not any_resolved:
            log.info("no schematic files in configs/nodes/ — using live installer URLs")

    def compute_path(self) -> None:
        # If skip_intermediate or only one minor away, go direct
        target_minor = self._minor_of(self.target)
        if not target_minor:
            raise ValueError(f"invalid target version: {self.target}")

        in_scope = ([self.cp] if self.cp else []) + self.workers
        minors = [self._minor_of(n.current_version) for n in in_scope if n.current_version != "?"]
        minors = [m for m in minors if m is not None]
        min_minor = min(minors) if minors else target_minor

        path: list[str] = []
        if self.skip_intermediate:
            path = [self.target]
        else:
            m = min_minor
            while m < target_minor:
                env_override = os.environ.get(f"LATEST_PATCH_1_{m}")
                v = env_override or DEFAULT_PATCH_VERSIONS.get(m, f"v1.{m}.0")
                path.append(v)
                m += 1
            path.append(self.target)
        self.path = path
        log.info("upgrade path: %s", " → ".join(path))

    @staticmethod
    def _minor_of(version: str) -> Optional[int]:
        m = re.match(r"v?(\d+)\.(\d+)\.(\d+)", version)
        return int(m.group(2)) if m else None

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def upgrade_one(self, node: Node, version: str) -> bool:
        """Upgrade one node and verify it returns Ready on `version`."""
        # Prefer target_installer_base (resolved from repo schematic via
        # factory.talos.dev) over the live machine config's installer_base.
        # This makes schematic updates apply automatically on next upgrade.
        base = node.target_installer_base or node.installer_base or self.installer_base
        image = f"{base}:{version}"

        # Pre-flight: if node is already on or past this version, skip.
        # This prevents accidental downgrades when a node is further ahead than
        # the phase version (e.g., partial-failure resume where some workers
        # are already on the final target).
        #
        # EXCEPTIONS that trigger re-upgrade even when at target version:
        #   - --force flag explicitly set
        #   - node.target_installer_base != node.installer_base (schematic drift)
        #   - factory installer URL but no extensions installed (repair)
        is_final_phase = version == self.path[-1]
        has_schematic_drift = (
            node.target_installer_base
            and node.target_installer_base != node.installer_base
        )
        needs_extension_repair = (
            node.has_factory_installer
            and not node.extensions
            and is_final_phase
        )
        with self.lock:
            if version_ge(node.current_version, version):
                if self.force:
                    node.last_message = f"--force: re-upgrading even though at {node.current_version}"
                    log.info("[%s] %s", node.name, node.last_message)
                elif has_schematic_drift and is_final_phase:
                    node.last_message = f"schematic drift — re-upgrading with new installer"
                    log.info("[%s] %s", node.name, node.last_message)
                elif needs_extension_repair:
                    node.last_message = (
                        f"factory installer but no extensions installed — "
                        f"re-upgrading to restore"
                    )
                    log.info("[%s] %s", node.name, node.last_message)
                else:
                    node.state = NodeState.SKIPPED
                    node.last_message = (
                        f"already on {node.current_version}"
                        if node.current_version == version
                        else f"already past ({node.current_version} ≥ {version})"
                    )
                    log.info("[%s] %s — skipping", node.name, node.last_message)
                    return True
            node.state = NodeState.UPGRADING
            node.target_version = version
            node.started_at = time.time()
            node.finished_at = 0
            node.last_message = "starting upgrade"

        log.info("[%s] upgrading %s → %s", node.name, node.current_version, version)

        if self.dry_run:
            log.info("[%s] [dry-run] would: talosctl --nodes %s upgrade --image %s --wait", node.name, node.ip, image)
            with self.lock:
                node.state = NodeState.READY
                node.current_version = version
                node.finished_at = time.time()
                node.last_message = "(dry-run)"
            return True

        cmd = [
            "talosctl", "--talosconfig", self.talosconfig,
            "--nodes", node.ip, "upgrade",
            "--image", image, "--wait", "--preserve=true",
        ]
        if self.force_drain:
            cmd.append("--force")
        log.debug("[%s] $ %s", node.name, " ".join(cmd))

        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
            )
        except FileNotFoundError:
            with self.lock:
                node.state = NodeState.FAILED
                node.last_message = "talosctl not found"
                node.finished_at = time.time()
            return False

        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            log.debug("[%s] %s", node.name, line)
            # Parse out phase/task transitions for the UI status line
            phase = re.search(r"phase:\s*(\w+)\s+action:\s*START", line)
            stage = re.search(r"stage:\s*(\w+)", line)
            if phase:
                with self.lock:
                    node.last_message = f"phase: {phase.group(1)}"
            elif stage and stage.group(1) in {"BOOTING", "RUNNING"}:
                with self.lock:
                    node.last_message = f"stage: {stage.group(1)}"
        rc = proc.wait()

        if rc != 0:
            with self.lock:
                node.state = NodeState.FAILED
                node.last_message = f"talosctl exit {rc}"
                node.finished_at = time.time()
            log.error("[%s] talosctl upgrade exited %d", node.name, rc)
            return False

        # Now poll for Ready AND correct version (don't trust exit code alone)
        with self.lock:
            node.state = NodeState.WAITING
            node.last_message = f"waiting for Ready on {version}"

        deadline = time.time() + NODE_WAIT_TIMEOUT
        last_status = ""
        while time.time() < deadline and not self.aborted:
            status = get_node_status(node.name)
            if status != last_status:
                last_status = status
                with self.lock:
                    node.last_message = f"k8s status: {status}"
            if status.startswith("Ready"):
                actual = get_talos_version(node.ip)
                if actual == version:
                    with self.lock:
                        node.state = NodeState.READY
                        node.current_version = actual
                        node.finished_at = time.time()
                        node.last_message = f"Ready on {actual} in {node.duration_text()}"
                    log.info("[%s] Ready on %s (took %s)", node.name, actual, node.duration_text())
                    return True
            time.sleep(3)

        with self.lock:
            node.state = NodeState.FAILED
            node.last_message = f"timeout after {NODE_WAIT_TIMEOUT}s"
            node.finished_at = time.time()
        log.error("[%s] timeout waiting for Ready on %s", node.name, version)
        return False

    def upgrade_workers_parallel(self, version: str) -> bool:
        if not self.workers:
            return True

        def needs_upgrade(w: Node) -> bool:
            if not version_ge(w.current_version, version):
                return True
            if self.force:
                return True
            is_final_phase = version == self.path[-1]
            if not is_final_phase:
                return False
            # Schematic drift — repo's schematic resolved to a different ID
            if w.target_installer_base and w.target_installer_base != w.installer_base:
                return True
            # Factory installer but no extensions installed → repair
            if w.has_factory_installer and not w.extensions:
                return True
            return False

        workers_needing = [w for w in self.workers if needs_upgrade(w)]
        already = [w for w in self.workers if not needs_upgrade(w)]
        for w in already:
            with self.lock:
                w.state = NodeState.SKIPPED
                w.last_message = (
                    f"already on {w.current_version}"
                    if w.current_version == version
                    else f"already past ({w.current_version} ≥ {version})"
                )
        if already:
            log.info("workers already at/past %s: %s", version, ", ".join(w.name for w in already))

        if not workers_needing:
            log.info("all workers already on %s", version)
            return True

        log.info("upgrading workers in parallel: %s → %s",
                 ", ".join(w.name for w in workers_needing), version)

        results: dict[str, bool] = {}
        threads: list[threading.Thread] = []
        for w in workers_needing:
            t = threading.Thread(
                target=lambda w=w: results.__setitem__(w.name, self.upgrade_one(w, version)),
                name=f"upgrade-{w.name}",
                daemon=True,
            )
            t.start()
            threads.append(t)
        for t in threads:
            t.join()

        ok = all(results.values())
        failed = [name for name, r in results.items() if not r]
        if failed:
            log.error("workers failed at %s: %s", version, ", ".join(failed))
        return ok

    def run_phase(self, version: str) -> bool:
        if self.aborted:
            return False
        self.current_phase = version
        log.info("======== phase → %s ========", version)

        # CP first (if in scope). upgrade_one handles already-at-or-past logic.
        if self.cp:
            if not self.upgrade_one(self.cp, version):
                return False
            # Settle briefly to let the CP fully stabilize before stressing workers
            if self.cp.state == NodeState.READY and self.settle_seconds > 0:
                log.info("CP upgrade done — settling %ds before workers", min(15, self.settle_seconds))
                for _ in range(min(15, self.settle_seconds)):
                    if self.aborted:
                        return False
                    time.sleep(1)

        # Then workers in parallel
        if not self.upgrade_workers_parallel(version):
            return False

        # Settle: avoid the kubelet-CRI race on the next phase
        if self.settle_seconds > 0 and version != self.path[-1]:
            log.info("settling for %ds before next phase", self.settle_seconds)
            for i in range(self.settle_seconds):
                if self.aborted:
                    return False
                time.sleep(1)
        return True

    def reset_for_next_phase(self) -> None:
        with self.lock:
            for n in self.nodes:
                if n.state in (NodeState.READY, NodeState.SKIPPED):
                    n.state = NodeState.PENDING
                    n.last_message = ""
                    n.started_at = 0
                    n.finished_at = 0

    def uncordon_all_successful(self) -> None:
        """Uncordon every node that ended in READY or SKIPPED state.

        Talos auto-uncordons nodes it cordoned itself during upgrade, but it
        does NOT touch nodes that were manually cordoned beforehand (e.g. by
        shutdown-cluster.sh). This makes the post-upgrade state consistent.
        """
        if self.dry_run:
            log.info("[dry-run] would uncordon all successful nodes")
            return

        cordoned: list[str] = []
        for n in self.nodes:
            if n.state not in (NodeState.READY, NodeState.SKIPPED):
                continue
            status = get_node_status(n.name)
            if "SchedulingDisabled" in status:
                cordoned.append(n.name)

        if not cordoned:
            log.info("no nodes need uncordoning")
            return

        log.info("uncordoning %d nodes: %s", len(cordoned), ", ".join(cordoned))
        for name in cordoned:
            r = kubectl("uncordon", name)
            if r.returncode == 0:
                log.info("[%s] uncordoned", name)
            else:
                log.warning("[%s] uncordon failed: %s", name, r.stderr.strip())

    def bump_manifest_versions(self) -> None:
        """Update worker-<node>.yaml install.image fields to match the freshly
        upgraded state:

          - new Talos version tag (always)
          - new schematic ID if refresh_schematics resolved a different URL

        Also runs a generic version-tag bump against any other installer-image
        lines (controlplane.yaml, etc.).  Skips kubelet and other unrelated
        images.  Files unchanged are not rewritten.
        """
        if self.dry_run:
            log.info("[dry-run] would update installer image lines in configs/nodes/")
            return

        configs_dir = Path("configs/nodes")
        if not configs_dir.exists():
            log.warning("configs/nodes not found — skipping manifest version bump")
            return

        updated: list[tuple[Path, list[str]]] = []

        # 1) Per-node updates: rewrite each worker-<name>.yaml install.image to
        #    the exact target_installer_base:target_version pair.
        for n in self.nodes:
            if n.state not in (NodeState.READY, NodeState.SKIPPED):
                continue
            # Find worker-<name>.yaml under configs/nodes/**/
            files = list(configs_dir.glob(f"**/worker-{n.name}.yaml"))
            if n.is_cp:
                files += list(configs_dir.glob("controlplane.yaml"))
            for f in files:
                target_base = n.target_installer_base or n.installer_base
                if not target_base:
                    continue
                desired_image = f"{target_base}:{self.target}"
                if self._set_install_image(f, desired_image):
                    updated.append((f, [f"  → {desired_image}"]))

        # 2) Generic version-tag bumps for any remaining installer URLs
        #    (e.g. worker-base.yaml referenced by all workers).
        files = sorted(configs_dir.glob("**/*.yaml"))
        for f in files:
            try:
                content = f.read_text()
            except OSError as e:
                log.warning("could not read %s: %s", f, e)
                continue

            replaced_lines: list[str] = []

            def _sub(m: re.Match) -> str:
                old_full = m.group(0)
                new_full = f"{m.group('base')}:{self.target}"
                if old_full != new_full:
                    replaced_lines.append(
                        f"  {f.name}: "
                        f"v{m.group('major')}.{m.group('minor')}.{m.group('patch')} → {self.target}"
                    )
                return new_full

            new_content = INSTALLER_IMAGE_RE.sub(_sub, content)
            if new_content != content:
                f.write_text(new_content)
                # Only count if not already counted by per-node pass
                already = any(p == f for p, _ in updated)
                if not already:
                    updated.append((f, replaced_lines))

        if not updated:
            log.info("manifests already on %s — nothing to bump", self.target)
            return

        log.info("updated %d manifest file(s) for target %s:", len(updated), self.target)
        for f, lines in updated:
            log.info("  %s", f)
            for ln in lines:
                log.info("    %s", ln)
        log.info("review changes with: git diff configs/nodes/")

    @staticmethod
    def _set_install_image(path: Path, desired_image: str) -> bool:
        """Set the `install.image: <url>` line in a machine config file.
        Returns True if the file was modified.

        Matches the first `install:` block's `image:` line.  Preserves
        indentation.  If the file has no install.image line, no change.
        """
        try:
            text = path.read_text()
        except OSError:
            return False

        new_text, n_subs = re.subn(
            r"(?m)^(\s*image:\s+)\S*?/installer(?:/[a-f0-9]+)?:v\d+\.\d+\.\d+",
            lambda m: f"{m.group(1)}{desired_image}",
            text,
        )
        if n_subs > 0 and new_text != text:
            path.write_text(new_text)
            return True
        return False

    def run(self) -> bool:
        for i, v in enumerate(self.path):
            ok = self.run_phase(v)
            if not ok:
                return False
            if i < len(self.path) - 1:
                self.reset_for_next_phase()

        # All phases succeeded — optionally uncordon nodes that talosctl missed
        if self.uncordon_on_success:
            self.uncordon_all_successful()
        else:
            log.info("--no-uncordon set; leaving cordon state untouched")
            log.info("to uncordon manually: kubectl uncordon <node>")

        # Bump versions in repo machine configs so they match the new running state
        if self.update_manifests:
            self.bump_manifest_versions()
        else:
            log.info("--no-update-manifests set; configs/nodes/ left as-is")

        return True


# ===========================================================================
# UI
# ===========================================================================

STATE_GLYPH = {
    NodeState.PENDING:   ("⋯", "dim"),
    NodeState.UPGRADING: (None, "cyan"),     # spinner
    NodeState.WAITING:   (None, "yellow"),   # spinner
    NodeState.READY:     ("✓", "green"),
    NodeState.SKIPPED:   ("—", "dim"),
    NodeState.FAILED:    ("✗", "red"),
}


def _state_renderable(state: NodeState) -> Text | Spinner:
    glyph, style = STATE_GLYPH[state]
    if glyph is None:
        return Spinner("dots", text=Text(state.value, style=style))
    return Text(glyph, style=style)


def _elapsed(start: float) -> str:
    s = int(time.time() - start)
    return f"{s // 60}m{s % 60:02d}s"


def make_header(orch: UpgradeOrchestrator) -> Panel:
    elapsed = _elapsed(orch.start_time)
    phase = orch.current_phase or "—"
    path_display = " → ".join(orch.path) if orch.path else "—"

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold magenta")
    grid.add_column()
    grid.add_row("target",  Text(orch.target, style="bold green"))
    grid.add_row("phase",   Text(phase, style="bold cyan"))
    grid.add_row("path",    Text(path_display, style="bright_white"))
    grid.add_row("elapsed", Text(elapsed, style="bold"))
    grid.add_row("logfile", Text(str(LOG_FILE), style="dim"))

    title = Text(" catalyst-cluster · talos upgrade ", style="bold magenta on grey15")
    return Panel(grid, title=title, border_style="magenta", padding=(0, 1))


def make_nodes_table(orch: UpgradeOrchestrator) -> Panel:
    t = Table(
        show_header=True, header_style="bold",
        expand=True, border_style="bright_black", row_styles=["", "dim"],
    )
    t.add_column("node", style="bold", no_wrap=True)
    t.add_column("ip", no_wrap=True)
    t.add_column("role")
    t.add_column("installer", no_wrap=True)
    t.add_column("from", justify="right")
    t.add_column("→")
    t.add_column("target", justify="right")
    t.add_column("state", min_width=12)
    t.add_column("elapsed", justify="right")
    t.add_column("note", no_wrap=False, overflow="ellipsis")

    with orch.lock:
        all_nodes = list(orch.nodes)

    # Order: CP first, then workers alphabetical
    all_nodes.sort(key=lambda n: (0 if n.is_cp else 1, n.name))
    for n in all_nodes:
        role_style = "yellow" if n.is_cp else "white"
        installer_label = "factory" if n.has_factory_installer else "stock"
        installer_style = "bright_magenta" if n.has_factory_installer else "dim"
        t.add_row(
            n.name,
            Text(n.ip, style="dim"),
            Text(n.role, style=role_style),
            Text(installer_label, style=installer_style),
            Text(n.current_version, style="dim"),
            Text("→", style="dim"),
            Text(n.target_version or orch.target, style="bright_white"),
            _state_renderable(n.state),
            Text(n.duration_text(), style="dim"),
            Text(n.last_message, style="dim"),
        )
    return Panel(t, title="nodes", border_style="cyan", padding=(0, 1))


def make_log_panel(recent: RecentLogHandler) -> Panel:
    lines = recent.lines()
    if not lines:
        body = Text("(no events yet)", style="dim")
    else:
        body = Text("\n".join(lines), style="white")
    return Panel(body, title="recent events", border_style="bright_black", padding=(0, 1))


def build_layout(orch: UpgradeOrchestrator, recent: RecentLogHandler) -> Layout:
    root = Layout()
    root.split_column(
        Layout(name="header", size=8),
        Layout(name="nodes", ratio=2),
        Layout(name="log", size=14),
    )
    root["header"].update(make_header(orch))
    root["nodes"].update(make_nodes_table(orch))
    root["log"].update(make_log_panel(recent))
    return root


# ===========================================================================
# Banner / final summary
# ===========================================================================

BANNER = r"""
   _   _ ____   ____ ____      _    ____  _____
  | | | |  _ \ / ___|  _ \    / \  |  _ \| ____|
  | | | | |_) | |  _| |_) |  / _ \ | | | |  _|
  | |_| |  __/| |_| |  _ <  / ___ \| |_| | |___
   \___/|_|    \____|_| \_\/_/   \_\____/|_____|
"""


def print_banner(console: Console) -> None:
    console.print(Text(BANNER, style="magenta"))
    console.print(Text("  catalyst-cluster · talos upgrade orchestrator\n",
                       style="bold magenta"))


def print_summary(console: Console, orch: UpgradeOrchestrator, success: bool) -> None:
    t = Table(
        show_header=True, header_style="bold",
        border_style="magenta", expand=True, title="upgrade summary",
    )
    t.add_column("node", style="bold")
    t.add_column("ip")
    t.add_column("role")
    t.add_column("current", justify="right")
    t.add_column("target", justify="right")
    t.add_column("state")
    t.add_column("duration", justify="right")
    nodes = sorted(orch.nodes, key=lambda n: (0 if n.is_cp else 1, n.name))
    for n in nodes:
        state_text = Text(n.state.value)
        if n.state == NodeState.READY:
            state_text.stylize("green")
        elif n.state == NodeState.FAILED:
            state_text.stylize("red")
        elif n.state == NodeState.SKIPPED:
            state_text.stylize("dim")
        t.add_row(
            n.name, Text(n.ip, style="dim"), n.role,
            Text(n.current_version, style="bright_white"),
            Text(orch.target, style="dim"),
            state_text,
            Text(n.duration_text(), style="dim"),
        )
    console.print()
    console.print(t)
    console.print()
    total = _elapsed(orch.start_time)
    if success:
        console.print(Text(f"  ✓ upgrade complete in {total}", style="bold green"))
    else:
        console.print(Text(f"  ✗ upgrade did not finish cleanly (elapsed {total})", style="bold red"))
    console.print(Text(f"  full log: {LOG_FILE}", style="dim"))
    console.print()


# ===========================================================================
# Live runner
# ===========================================================================

def run_with_live_ui(orch: UpgradeOrchestrator, recent: RecentLogHandler, console: Console) -> bool:
    """Run the orchestrator in a worker thread and render UI in the main thread."""
    result: dict[str, bool] = {"ok": False, "done": False}

    def worker() -> None:
        try:
            result["ok"] = orch.run()
        except Exception as e:  # pragma: no cover
            log.exception("orchestrator crashed: %s", e)
            result["ok"] = False
        finally:
            result["done"] = True

    t = threading.Thread(target=worker, name="orchestrator", daemon=True)
    t.start()

    with Live(
        build_layout(orch, recent),
        console=console,
        refresh_per_second=UI_REFRESH_PER_SECOND,
        screen=False,
        transient=False,
    ) as live:
        try:
            while not result["done"]:
                live.update(build_layout(orch, recent))
                time.sleep(1 / UI_REFRESH_PER_SECOND)
            # one final update so the final state is visible
            live.update(build_layout(orch, recent))
        except KeyboardInterrupt:
            orch.aborted = True
            log.warning("interrupted — waiting for in-flight upgrades to settle")
            t.join(timeout=120)

    return result["ok"]


# ===========================================================================
# CLI
# ===========================================================================

def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="upgrade-talos",
        description="Catalyst cluster — Talos OS upgrade orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("target", help="target Talos version (e.g. v1.13.0)")
    p.add_argument("--yes", "-y", action="store_true", help="skip the confirmation prompt")
    p.add_argument("--dry-run", "-n", action="store_true", help="show what would happen, touch nothing")
    p.add_argument("--skip-intermediate", action="store_true",
                   help="jump straight to target (NOT recommended by Sidero)")
    p.add_argument("--skip-health-check", action="store_true",
                   help="bypass the pre-upgrade health gate")
    p.add_argument("--no-uncordon", action="store_true",
                   help="leave successful nodes cordoned at the end (default: uncordon them)")
    p.add_argument("--no-update-manifests", action="store_true",
                   help="don't bump installer image version tags in configs/nodes/ after success")
    p.add_argument("--no-refresh-schematics", action="store_true",
                   help="don't resolve repo *-schematic.yaml files against factory.talos.dev "
                        "(default: refresh — detects schematic drift and uses up-to-date IDs)")
    p.add_argument("--force", action="store_true",
                   help="re-upgrade even nodes already at the target version "
                        "(useful for repairing dropped extensions)")
    p.add_argument("--force-drain", action="store_true",
                   help="pass --force to `talosctl upgrade` — skips pre-install "
                        "drain and PDB checks. Use when a pod is blocking eviction "
                        "(e.g. single-instance stateful workload on local-path PV)")
    p.add_argument("--settle", type=int, default=DEFAULT_SETTLE_SECONDS,
                   help=f"seconds to wait between phases (default {DEFAULT_SETTLE_SECONDS})")
    p.add_argument("--only", action="append", default=[],
                   metavar="NODE", help="upgrade only the named node(s) — repeatable")
    p.add_argument("--talosconfig", default=DEFAULT_TALOSCONFIG)
    p.add_argument("--installer-base", default=DEFAULT_INSTALLER_BASE)
    return p.parse_args(argv)


def confirm(console: Console, orch: UpgradeOrchestrator) -> bool:
    in_scope_names = []
    if orch.cp:
        in_scope_names.append(orch.cp.name)
    in_scope_names.extend(w.name for w in orch.workers)
    console.print()
    console.print(Text(f"  → will upgrade: {', '.join(in_scope_names)}", style="bold yellow"))
    console.print(Text(f"  → path: {' → '.join(orch.path)}", style="bold cyan"))
    console.print()
    answer = input("Type 'yes' to proceed: ").strip().lower()
    return answer == "yes"


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(sys.argv[1:]) if argv is None else argv
    args = parse_args(argv)

    if not re.match(r"^v\d+\.\d+\.\d+$", args.target):
        print(f"error: invalid target version {args.target!r} (expected like v1.13.0)", file=sys.stderr)
        return 2
    if not shutil.which("talosctl"):
        print("error: talosctl not in PATH", file=sys.stderr)
        return 1
    if not shutil.which("kubectl"):
        print("error: kubectl not in PATH", file=sys.stderr)
        return 1
    if not Path(args.talosconfig).exists():
        print(f"error: talosconfig missing at {args.talosconfig}", file=sys.stderr)
        return 1

    recent = setup_logging()
    console = Console()
    print_banner(console)
    log.info("logfile: %s", LOG_FILE)

    orch = UpgradeOrchestrator(
        target=args.target,
        talosconfig=args.talosconfig,
        installer_base=args.installer_base,
        settle_seconds=args.settle,
        dry_run=args.dry_run,
        only=args.only or None,
        skip_intermediate=args.skip_intermediate,
        uncordon_on_success=not args.no_uncordon,
        update_manifests=not args.no_update_manifests,
        refresh_schematics=not args.no_refresh_schematics,
        force=args.force,
        force_drain=args.force_drain,
    )

    # Pre-flight: discover, resolve schematics, plan, health-check
    try:
        log.info("discovering cluster…")
        orch.discover()
        log.info("resolving repo schematics via factory.talos.dev…")
        orch.resolve_schematics_from_repo()
        log.info("computing upgrade path…")
        orch.compute_path()
    except Exception as e:
        log.exception("setup failed: %s", e)
        console.print(Text(f"  ✗ {e}", style="red"))
        return 1

    # Health gate
    if not args.skip_health_check:
        log.info("running pre-upgrade health check…")
        ok, issues = health_check(orch.nodes, orch.cp or orch.nodes[0], args.talosconfig)
        if not ok:
            console.print(Text("\n  ✗ pre-upgrade health check failed:", style="bold red"))
            for i in issues:
                console.print(Text(f"    · {i}", style="red"))
            console.print(Text(
                "\n  → fix the issues above, or rerun with --skip-health-check\n",
                style="yellow"))
            return 1
        log.info("health check passed")

    if args.dry_run:
        console.print(Text("\n  (dry-run — no nodes will be touched)\n", style="dim yellow"))

    # Confirm
    if not args.yes and not args.dry_run:
        if not confirm(console, orch):
            print("aborted")
            return 1

    # Handle Ctrl-C cleanly
    def _on_sigint(_sig, _frm):  # pragma: no cover
        orch.aborted = True
    signal.signal(signal.SIGINT, _on_sigint)

    ok = run_with_live_ui(orch, recent, console)
    print_summary(console, orch, ok)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
