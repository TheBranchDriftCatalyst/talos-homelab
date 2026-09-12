"""Accepted-risk registry for the ingress-accessibility layer (Layer 3).

This is the REVIEW SURFACE: every exception to a contract is an entry carrying a rationale and a
beads id. A PR that adds an un-gated route shows up as an allowlist diff, not a silently-passing
test. An entry with no rationale / no TALOS- id fails the test that consumes it.

Entries marked `UNREVIEWED` are inherited from the 2026-09-12 ALPHA audit (TALOS-a8vo) and have a
blocking beads child; the --live layer (L4/L6/L7) does the real verification on them immediately.
"""
from collections import namedtuple

Accepted = namedtuple("Accepted", "reason issue reviewed")

# --- /api & /feed carve-outs (priority>0 PathPrefix(/api|/feed) with no auth/lan-only) ---
# The frigate carve-out is NOT here — it carries lan-only (the 002 fix) and passes the contract.
API_CARVEOUT_ALLOWLIST = {
    ("media", "sonarr"): Accepted(
        "Sonarr enforces AUTH__METHOD=External + its own X-Api-Key on /api (verified 401 off-LAN); "
        "carve-out needed for Prowlarr sync + RSS. Restore lan-only as defense-in-depth (TALOS-a8vo P1).",
        "TALOS-a8vo", "2026-09-12"),
    ("media", "radarr"): Accepted(
        "Radarr own X-Api-Key auth (verified 401 off-LAN); carve-out for Prowlarr sync + RSS. "
        "lan-only pending (TALOS-a8vo P1).", "TALOS-a8vo", "2026-09-12"),
    ("media", "prowlarr"): Accepted(
        "Prowlarr own X-Api-Key auth (verified 401 off-LAN). lan-only pending (TALOS-a8vo P1).",
        "TALOS-a8vo", "2026-09-12"),
    ("media", "sabnzbd"): Accepted(
        "SABnzbd requires API key (403 'API Key Required'). lan-only pending.", "TALOS-a8vo", "2026-09-12"),
    ("media", "seerr"): Accepted(
        "Overseerr/Jellyseerr requires session cookie (401). lan-only pending.", "TALOS-a8vo", "2026-09-12"),
    ("media", "tautulli"): Accepted(
        "Tautulli requires apikey (401). lan-only pending.", "TALOS-a8vo", "2026-09-12"),
    # UNREVIEWED — book/comic *arr set; app-level auth returns 401 but not individually re-verified.
    ("media-experimental", "bindery"): Accepted(
        "UNREVIEWED — app enforces API key (401). Verify + gate.", "TALOS-a8vo", "2026-09-12"),
    ("media-experimental", "chaptarr"): Accepted(
        "UNREVIEWED — app enforces API key. Verify + gate.", "TALOS-a8vo", "2026-09-12"),
    ("media-experimental", "librarr"): Accepted(
        "UNREVIEWED — app enforces API key. Verify + gate.", "TALOS-a8vo", "2026-09-12"),
    ("media-experimental", "livrarr"): Accepted(
        "UNREVIEWED — app enforces API key. Verify + gate.", "TALOS-a8vo", "2026-09-12"),
    ("media-experimental", "mylar3"): Accepted(
        "UNREVIEWED — app enforces API key. Verify + gate.", "TALOS-a8vo", "2026-09-12"),
    ("media-experimental", "storyteller"): Accepted(
        "UNREVIEWED — app enforces API key. Verify + gate.", "TALOS-a8vo", "2026-09-12"),
    ("media", "posterizarr"): Accepted(
        "UNREVIEWED — /api/status returns 200 (run-state/log tail), /api/config 401. Gate or lan-only.",
        "TALOS-a8vo", "2026-09-12"),
    ("media", "posterr"): Accepted(
        "UNREVIEWED — /api returns 404 (no such backend path); carve-out present but inert. Verify.",
        "TALOS-a8vo", "2026-09-12"),
    ("media", "pulsarr"): Accepted(
        "UNREVIEWED — /api returns 404 (no such backend path); carve-out present but inert. Verify.",
        "TALOS-a8vo", "2026-09-12"),
    # media/maintainerr now carries lan-only on its /api carve-out (P0 mitigation, frigate-002 pattern):
    # off-LAN/WAN blocked; pod-CIDR residue tracked in LAN_ONLY_PERIMETER_ONLY below.
    ("media", "maintainerr"): Accepted(
        "lan-only on /api carve-out (P0 fix); no app auth, so relies on lan-only. Pod-CIDR residue: "
        "see LAN_ONLY_PERIMETER_ONLY + the lan-only-excludes-pod-CIDR P1.", "TALOS-a8vo", "2026-09-12"),
}

# --- routes intentionally serving with no middleware (login-plane, outpost, tarpit, tracking) ---
NO_MIDDLEWARE_ALLOWLIST = {
    ("authentik", "authentik-outpost-priv"): Accepted("outpost /outpost.goauthentik.io callbacks must be unauth", "TALOS-lxz5", "2026-09-12"),
    ("authentik", "amberdark-outpost-callbacks"): Accepted("outpost callbacks must be unauth", "TALOS-lxz5", "2026-09-12"),
    ("authentik", "authentik-local"): Accepted("Authentik login plane", "TALOS-lxz5", "2026-09-12"),
    ("authentik", "catalyst-bg"): Accepted("login-page rotating background asset", "TALOS-lxz5", "2026-09-12"),
    ("iocaine", "iocaine-public"): Accepted("tarpit — auth would defeat it", "TALOS-hg7", "2026-09-12"),
    ("crossplane-demo", "plausible-public-tracking"): Accepted("scoped to /js/ + /api/event tracking only", "TALOS-lxz5", "2026-09-12"),
}

# --- public routes exempt from the rate-limit+bot-wrangler chain ---
PUBLIC_CHAIN_ALLOWLIST = {
    ("iocaine", "iocaine-public"): Accepted("tarpit", "TALOS-hg7", "2026-09-12"),
    ("crossplane-demo", "plausible-public-tracking"): Accepted("tracking endpoint by design", "TALOS-lxz5", "2026-09-12"),
    ("authentik", "catalyst-bg"): Accepted("static image asset", "TALOS-lxz5", "2026-09-12"),
}

# --- raw TCP entrypoint routers accepted as open (hostPort, HostSNI(*)) ---
# EMPTY (TALOS-a8vo P0-1 FIXED): the gluetun SOCKS/HTTP-proxy IngressRouteTCPs were the only open
# unauthenticated TCP proxy routers. They have been removed (ingressroute-tcp.yaml deleted + the
# socks/httpproxy Traefik entrypoints dropped from the traefik helmrelease), and the gluetun
# killswitch tightened to drop the pod/service CIDRs. With no route on the socks/httpproxy
# entrypoints, A12 (test_tcp_proxy_routes_are_restricted_or_accepted) finds no offenders and this
# registry stays empty. Any future socks/httpproxy TCP router must be re-justified here.
OPEN_PROXY_ACCEPTED = {}

# --- lan-only: routes relying on it ALONE while it still admits the pod CIDR (10.0.0.0/8) ---
# frigate is the known case (finding 002 east-west residue, TALOS-a8vo P1). Documented, not silent.
LAN_ONLY_PERIMETER_ONLY = {
    ("scratch", "frigate"): Accepted(
        "lan-only currently admits pod CIDR (10.0.0.0/8 ⊇ 10.244/16); off-LAN blocked, east-west open. "
        "Fix by excluding pod CIDR from lan-only (TALOS-a8vo P1).", "TALOS-a8vo", "2026-09-12"),
    ("media", "maintainerr"): Accepted(
        "maintainerr has no app auth; /api relies on lan-only alone. Off-LAN blocked; pod-CIDR residue "
        "closes with the lan-only-excludes-pod-CIDR fix (TALOS-a8vo P1).", "TALOS-a8vo", "2026-09-12"),
}

# --- backends that map a proxy header to a user identity (may NEVER hold an un-gated carve-out) ---
HEADER_TRUSTING_BACKENDS = {"frigate", "grafana", "guacamole"}

# --- live-vs-repo drift: routes managed outside Flux (ArgoCD sister repos) ---
DRIFT_ALLOWLIST = set()  # seed from `kubectl get ingressroute -A -l argocd.argoproj.io/instance`


def valid(entry):
    """An allowlist entry is valid only with a non-empty reason + a TALOS- issue id."""
    return bool(entry and entry.reason.strip() and entry.issue.startswith("TALOS-"))
