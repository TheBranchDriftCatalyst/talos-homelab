"""haproxy-novelty-bouncer — a CrowdSec remediation component for the honeypot front.

# doc() bouncer-role: What this sidecar does
#   section: Overview
#   order: 10
#   Polls the CrowdSec LAPI for `silentdrop` decisions and maintains haproxy's replay.map
#   over the admin socket with `add map` / `del map`. The map lives ONLY in haproxy's memory,
#   so a haproxy restart empties it until the next reconcile — there is no file on disk.
#
# diagram() bouncer-flow: Decision path
#   section: Overview
#   order: 20
#   flowchart LR
#     lapi[(CrowdSec LAPI)] -->|poll 30s| sc[novelty-bouncer]
#     sc -->|add map / del map| hap[haproxy admin socket]
#     hap --> drop["tcp-request connection silent-drop"]

The honeypot is reached over raw TCP (VIP -> haproxy -> cowrie), which no CrowdSec
bouncer touches, so decisions have never had any effect there. That is deliberate for
`ban`: an attacker must keep reaching the honeypot while being blocked everywhere else.

This consumes ONLY decisions of type `silentdrop`, which exactly one scenario produces
(homelab/cowrie-replay-drop, via the cowrie_replay_drop profile). Everything else --
every `ban`, community blocklist entry, and CAPI import -- is ignored, so the honeypot
stays open to novel attackers by construction.

ON THE NAME: the "novelty" analysis is NOT done here -- it lives entirely in the
scenario homelab/cowrie-replay-drop, which counts distinct commands per source. This
component never sees a command and counts nothing; it only enforces whatever carries
type=silentdrop. If a second scenario ever emits that type, this enforces it unchanged
and the name becomes a slight misnomer. Rename it then; do not add heuristics here.

Shape deliberately mirrors crowdsec/decision-exporter/exporter.py: same stdlib-only
approach, same VERIFIED-TLS hop to the LAPI, same "never trust a partial read".
When one of them changes, CHANGE BOTH -- fixing only one of this pair is how the exporter
spent two hours down on 2026-09-18 while this file carried the identical defect.
"""
import json
import os
import re
import ipaddress
import socket
import ssl
import time
from pathlib import Path
from urllib.request import Request, urlopen

MAX_BYTES = 8 * 1024 * 1024
POLL_SECONDS = 30
MAP_PATH = '/usr/local/etc/haproxy/replay.map'
# Only this decision type is enforced here. A `ban` must NOT close the honeypot.
DROP_TYPE = 'silentdrop'
# LAPI is TLS. This used to run ssl._create_unverified_context(), which accepts ANY
# certificate -- confidentiality without authentication on the hop that tells this process
# which addresses to silently drop. Anything able to answer on that Service name could have
# fed it an arbitrary drop list, including one covering legitimate traffic.
#
# Verification is cheap now: crowdsec certs are signed by homelab-ca (TALOS-k5vm), and
# trust-manager publishes that CA into EVERY namespace as the homelab-ca-bundle ConfigMap,
# so this is a plain mount with no cross-namespace copying and rotation comes for free.
#
# Fails LOUDLY if the CA is absent rather than silently downgrading to unverified. This
# bouncer fails OPEN by design (a missing map means nothing is dropped, and the honeypot
# keeps collecting), so refusing to start is the safe direction.
_CA_FILE = os.environ.get('LAPI_CA_FILE', '/tls/ca.crt')


def _tls_context():
    """Build the TLS context PER CALL, and check for the CA HERE rather than at import.

    Both halves of this are lessons paid for the same day this file was written, in the
    sibling exporter:
      - a module-level context caches the CA read at startup, so when cert-manager rotated
        the LAPI certificate underneath it the process kept trusting a dead CA for two hours
        with no self-healing (nothing restarts a non-chart Deployment on rotation);
      - an import-time SystemExit fires on any machine without the pod's /tls mount, which
        broke the offline test suite -- the module could not be imported at all.

    Checking at first use keeps the fail-loud guarantee: this bouncer still refuses to talk
    to the LAPI unverified, and reconcile() surfaces the error. It fails OPEN by design (an
    empty map drops nothing and the honeypot keeps collecting), so erroring here is safe.
    """
    if not os.path.isfile(_CA_FILE):
        raise RuntimeError(f'LAPI CA bundle missing at {_CA_FILE}; refusing to connect unverified')
    return ssl.create_default_context(cafile=_CA_FILE)
_IPV4 = re.compile(r'^\d{1,3}(?:\.\d{1,3}){3}$')


def wanted(payload):
    """IPs that should currently be dropped. Anything unexpected -> raise, never guess."""
    if payload is None:
        return set()
    if not isinstance(payload, list):
        raise ValueError('invalid decision response')
    result = set()
    for d in payload:
        # `simulated` is what makes the detect-only soak safe: while
        # homelab/cowrie-replay-drop sits in simulation.yaml exclusions its decisions
        # arrive flagged and must never reach the map.
        if d.get('simulated', False):
            continue
        if d.get('type') != DROP_TYPE or d.get('scope') != 'Ip':
            continue
        value = d.get('value', '')
        # haproxy map keys are plain addresses; refuse anything else rather than feeding an
        # unvalidated string into the admin socket. fullmatch + ip_address, NOT re.match:
        # `$` also matches before a trailing newline, so "1.2.3.4\n" passed and would have
        # written a stray newline into the socket, and the regex alone accepts nonsense
        # octets like 999.999.999.999 which haproxy then rejects in a logged loop.
        if not _IPV4.fullmatch(value):
            continue
        try:
            ipaddress.ip_address(value)
        except ValueError:
            continue
        result.add(value)
    return result


class Socket:
    """One admin-socket command per connection -- haproxy closes after each."""

    def __init__(self, path):
        self.path = path

    def run(self, command):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(5)
            sock.connect(self.path)
            sock.sendall((command + '\n').encode())
            chunks = []
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                if sum(map(len, chunks)) > MAX_BYTES:
                    raise ValueError('admin socket response exceeds limit')
        return b''.join(chunks).decode(errors='replace')

    def current(self):
        """Parse `show map` output.

        Real format, verified against haproxy 3.4 over the admin socket:
            0x99b110000 203.0.113.9 1
        i.e. "<entry pointer> <key> <value>" with NO trailing colon on the id.
        Key off the key column looking like an address rather than the id's shape --
        an earlier version tested for a trailing ':' here, never matched anything, and
        would have re-added every IP forever while never expiring one.
        """
        out = self.run(f'show map {MAP_PATH}')
        live = set()
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2 and _IPV4.match(parts[1]):
                live.add(parts[1])
        return live


def reconcile(api, sock):
    live = sock.current()
    target = api()
    for ip in sorted(target - live):
        sock.run(f'add map {MAP_PATH} {ip} 1')
        print(json.dumps({'event': 'drop_added', 'ip': ip}), flush=True)
    for ip in sorted(live - target):
        sock.run(f'del map {MAP_PATH} {ip}')
        print(json.dumps({'event': 'drop_removed', 'ip': ip}), flush=True)
    return len(target)


def main():
    sock = Socket(os.environ.get('HAPROXY_SOCKET', '/var/run/haproxy/admin.sock'))

    def api():
        key = Path(os.environ['API_KEY_FILE']).read_text().strip()
        # FILTER SERVER-SIDE. This used to fetch /v1/decisions -- every decision in the LAPI --
        # and filter down to silentdrop in Python. That worked while the store was small and
        # then silently stopped: once the blocklist feeds pushed the store past MAX_BYTES the
        # read tripped "decision response exceeds limit" on EVERY poll, and this bouncer fails
        # OPEN, so it stopped enforcing while looking alive. Measured at the time: 67,469
        # entries returned for a filter that matches a handful.
        #
        # ?type= makes the LAPI do the filtering, so the payload is proportional to what is
        # actually enforced rather than to how many blocklist IPs happen to be loaded. The
        # client-side checks below are KEPT as defence in depth -- in particular `simulated`,
        # which the server-side filter does not apply and which is the only thing keeping a
        # soaking scenario out of the live map.
        request = Request(os.environ['LAPI_URL'] + f'/v1/decisions?type={DROP_TYPE}&scopes=Ip',
                          headers={'X-Api-Key': key, 'User-Agent': 'haproxy-novelty-bouncer/1.0.0'})
        with urlopen(request, timeout=10, context=_tls_context()) as response:
            raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError('decision response exceeds limit')
        return wanted(json.loads(raw))

    while True:
        try:
            count = reconcile(api, sock)
            print(json.dumps({'event': 'reconciled', 'dropped_ips': count}), flush=True)
        except Exception as exc:
            # Fail OPEN on purpose: if the LAPI or the socket is unreachable we leave the
            # map exactly as it is rather than clearing it. A stale drop list is harmless
            # (these are confirmed replay bots); wrongly emptying it would silently undo
            # enforcement, and wrongly filling it could close the honeypot.
            print(json.dumps({'event': 'reconcile_error', 'error_type': type(exc).__name__}), flush=True)
        time.sleep(POLL_SECONDS)


if __name__ == '__main__':
    main()
