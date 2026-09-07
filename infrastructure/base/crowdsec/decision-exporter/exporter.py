"""Read-only, bounded local decision inventory. Never part of enforcement."""
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

LIMIT = 1000
MAX_BYTES = 8 * 1024 * 1024
ORIGINS = {'crowdsec', 'cscli', 'cscli-import'}
DURATION = re.compile(r'(\d+(?:\.\d+)?)(h|ms|us|µs|ns|m|s)')
UNITS = {'h': 3600, 'm': 60, 's': 1, 'ms': .001, 'us': .000001, 'µs': .000001, 'ns': .000000001}


def seconds(value):
    parts = DURATION.findall(value)
    if not parts or ''.join(a + b for a, b in parts) != value:
        raise ValueError('invalid duration')
    return sum(float(a) * UNITS[b] for a, b in parts)


def inventory(payload, now):
    if payload is None:
        return {}
    if not isinstance(payload, list):
        raise ValueError('invalid decision response')
    result = {}
    for d in payload:
        # Defense in depth: do not export community IPs or simulated decisions.
        if d['origin'] not in ORIGINS or d.get('simulated', False):
            continue
        duration = d['duration']
        if duration.startswith('-') or duration == '0s':
            continue
        result[str(d['id'])] = {
            'decision_id': str(d['id']), 'value': d['value'], 'scope': d['scope'],
            'action': d['type'], 'origin': d['origin'], 'scenario': d['scenario'],
            'expires': now + seconds(duration),
        }
    return result


def render(current, now):
    # Newest decision IDs first; total/omitted always describe the complete response.
    selected = sorted(current.values(), key=lambda d: int(d['decision_id']), reverse=True)[:LIMIT]
    lines = ['crowdsec_decision_inventory_success 1',
             f'crowdsec_decision_inventory_last_success_timestamp_seconds {now}',
             f'crowdsec_local_decisions_count {len(current)}',
             f'crowdsec_local_decisions_omitted {max(0, len(current) - LIMIT)}']
    for d in selected:
        labels = ','.join(f'{k}={json.dumps(str(v), ensure_ascii=False)}' for k, v in d.items() if k != 'expires')
        lines.append(f'crowdsec_local_decision_expires_timestamp_seconds{{{labels}}} {d["expires"]}')
    return '\n'.join(lines) + '\n'


class Inventory:
    def __init__(self):
        self.metrics = 'crowdsec_decision_inventory_success 0\n'
        self.previous = None

    def refresh(self):
        try:
            key = Path(os.environ['API_KEY_FILE']).read_text().strip()
            request = Request(os.environ['LAPI_URL'] + '/v1/decisions?origins=crowdsec,cscli,cscli-import',
                              headers={'X-Api-Key': key, 'User-Agent': 'crowdsec-decision-inventory/1.0.0'})
            with urlopen(request, timeout=10) as response:
                raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError('decision response exceeds limit')
            now = time.time()
            current = inventory(json.loads(raw), now)
            metrics = render(current, now)
            # Bound log volume too. Removal means no longer in LAPI; not proof of unblock.
            old = self.previous or {}
            for id_ in sorted(current.keys() - old.keys())[:LIMIT]:
                event = 'snapshot' if self.previous is None else 'observed'
                print(json.dumps({'event': event, 'observed_at': now, **current[id_]}), flush=True)
            if self.previous is not None:
                for id_ in sorted(old.keys() - current.keys())[:LIMIT]:
                    print(json.dumps({'event': 'removed', 'observed_at': now, **old[id_]}), flush=True)
            self.previous = current
            self.metrics = metrics
        except Exception as exc:
            # Never retain stale decision rows or publish zero as a successful inventory.
            self.metrics = 'crowdsec_decision_inventory_success 0\n'
            print(json.dumps({'event': 'inventory_error', 'error_type': type(exc).__name__}), flush=True)

    def run(self):
        while True:
            self.refresh()
            time.sleep(30)


def main():
    state = Inventory()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in ('/healthz', '/metrics'):
                self.send_error(404)
                return
            body = ('ok\n' if self.path == '/healthz' else state.metrics).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; version=0.0.4; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    threading.Thread(target=state.run, daemon=True).start()
    HTTPServer(('0.0.0.0', 9108), Handler).serve_forever()


if __name__ == '__main__':
    main()
