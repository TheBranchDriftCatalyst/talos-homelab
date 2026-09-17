"""Reconcile CrowdSec `silentdrop` decisions into haproxy's replay.map (TALOS-hdw8).

The honeypot is reached over raw TCP (VIP -> haproxy -> cowrie), which no CrowdSec
bouncer touches, so decisions have never had any effect there. That is deliberate for
`ban`: an attacker must keep reaching the honeypot while being blocked everywhere else.

This consumes ONLY decisions of type `silentdrop`, which exactly one scenario produces
(homelab/cowrie-replay-drop, via the cowrie_replay_drop profile). Everything else --
every `ban`, community blocklist entry, and CAPI import -- is ignored, so the honeypot
stays open to novel attackers by construction.

Shape deliberately mirrors crowdsec/decision-exporter/exporter.py: same stdlib-only
approach, same unverified-TLS hop to the LAPI, same "never trust a partial read".
"""
import json
import os
import re
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
# LAPI is TLS with a self-signed in-cluster CA (TALOS-3pdz/dw2p); same hop the
# decision exporter makes.
_TLS_CTX = ssl._create_unverified_context()
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
        # haproxy map keys are plain addresses; refuse anything else rather than
        # feeding an unvalidated string into the admin socket.
        if not _IPV4.match(value):
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
        request = Request(os.environ['LAPI_URL'] + '/v1/decisions',
                          headers={'X-Api-Key': key, 'User-Agent': 'honeypot-dropwatch/1.0.0'})
        with urlopen(request, timeout=10, context=_TLS_CTX) as response:
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
