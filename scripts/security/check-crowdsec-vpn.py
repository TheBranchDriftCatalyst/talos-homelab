#!/usr/bin/env python3
"""External enforcement regression: disposable VPN -> baseline -> manual ban -> unblock.

Requires kubectl access, PyYAML, and an unused ProtonVPN canary key. Creates only
its own Pod and a 5-minute manual decision (10 minutes with --ha). Does not trigger an attack scenario.
"""
import argparse
import ipaddress
import json
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

import yaml

ROOT = Path(__file__).resolve().parents[2]


def kubectl(*args, stdin=None, timeout=45, check=True):
    result = subprocess.run(['kubectl', '--request-timeout=30s', *args], input=stdin,
                            capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        # Do not dump container output/headers or secrets on failure.
        detail = next((line for line in result.stderr.splitlines() if line.startswith('curl:')), '')
        raise RuntimeError(f'kubectl {" ".join(args[:6])} failed (exit {result.returncode}) {detail}')
    return result


def public_ip(value):
    address = ipaddress.ip_address(value.strip())
    if not address.is_global or address.version != 4:
        raise RuntimeError('Expected a public IPv4 address')
    return str(address)


def decision_applies(decision, ip):
    # cscli returns alert objects; a bundled CAPI alert can contain other IPs.
    if decision.get('simulated') or decision.get('duration', '-').startswith('-'):
        return False
    if decision.get('duration') == '0s':
        return False
    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network(decision['value'], strict=False)
    except ValueError:
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='https://registry.knowledgedump.space/v2/',
                        help='Owned, protected public HTTPS endpoint with a stable 200 or 401 baseline')
    parser.add_argument('--ha', action='store_true', help='Also replace one LAPI replica while banned and one AppSec replica after unban; requires two Ready replicas of each')
    parser.add_argument('--report', type=Path, help='Write non-secret JSON results')
    args = parser.parse_args()
    target = urlsplit(args.url)
    if target.scheme != 'https' or not target.hostname or target.username or target.password:
        parser.error('--url must be an HTTPS URL without credentials')
    name = 'crowdsec-vpn-test-' + uuid.uuid4().hex[:10]
    reason = 'audit-vpn-' + uuid.uuid4().hex
    report = {'test': name, 'url': args.url, 'reason': reason, 'stages': [], 'passed': False}
    created = False
    ban_attempted = False
    cleaned = True

    def cscli(*cmd):
        return kubectl('-n', 'crowdsec', 'exec', 'deploy/crowdsec-lapi', '--', 'cscli', *cmd).stdout

    def probe(*cmd):
        return kubectl('-n', 'vpn-gateway', 'exec', name, '-c', 'probe', '--', *cmd).stdout.strip()

    def exit_ip():
        return public_ip(probe('curl', '-q', '-4', '--noproxy', '*', '--fail', '--silent',
                               '--show-error', '--max-time', '12', 'https://api.ipify.org'))

    def request(headers=()):
        raw = probe('curl', '-q', '-4', '--noproxy', '*', '--silent', '--show-error',
                    '--max-time', '15', '--output', '/dev/null', '--write-out',
                    '%{http_code} %{remote_ip}', *[arg for h in headers for arg in ('--header', h)], args.url)
        status, remote = raw.split()
        public_ip(remote)  # Reject split-DNS/LAN bypass paths.
        return int(status), remote

    def stage(label, **details):
        report['stages'].append({'stage': label, 'at': time.time(), **details})
        print(f'PASS {label}: {details}', flush=True)

    def wait_status(wanted, vpn_ip, timeout=100):
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            if exit_ip() != vpn_ip:
                raise RuntimeError('VPN exit IP changed during test')
            status, remote = request()
            if remote != report['origin_ip']:
                raise RuntimeError('Target origin IP changed during test')
            if status == wanted:
                return
            last = status
            time.sleep(5)
        raise RuntimeError(f'Expected HTTP {wanted}; last response was HTTP {last}')

    def replace_replica(component, expected_status):
        pods = json.loads(kubectl('-n', 'crowdsec', 'get', 'pods', '-l',
                                 f'k8s-app=crowdsec,type={component}', '-o', 'json').stdout)['items']
        ready = [p for p in pods if not p['metadata'].get('deletionTimestamp') and
                 any(c['type'] == 'Ready' and c['status'] == 'True' for c in p['status'].get('conditions', []))]
        if len(ready) < 2 or len({p['spec']['nodeName'] for p in ready}) < 2:
            raise RuntimeError(f'{component} has insufficient redundancy for replacement test')
        victim = ready[0]['metadata']['name']
        kubectl('-n', 'crowdsec', 'delete', 'pod', victim, '--wait=false')
        # Sample throughout replacement, not just after the deployment recovers.
        samples = 0
        deadline = time.monotonic() + 120
        recovered = False
        while time.monotonic() < deadline:
            if exit_ip() != vpn_ip or request() != (expected_status, report['origin_ip']):
                raise RuntimeError(f'Unexpected HTTP response during {component} replacement')
            samples += 1
            state = json.loads(kubectl('-n', 'crowdsec', 'get', 'pods', '-l',
                                      f'k8s-app=crowdsec,type={component}', '-o', 'json').stdout)['items']
            replacements = [p for p in state if p['metadata']['name'] != victim and
                            not p['metadata'].get('deletionTimestamp') and
                            any(c['type'] == 'Ready' and c['status'] == 'True' for c in p['status'].get('conditions', []))]
            if len(replacements) >= 2 and samples >= 3:
                recovered = True
                break
            time.sleep(3)
        if not recovered:
            raise RuntimeError(f'{component} redundancy did not recover within 120 seconds')
        stage(f'{component} replacement preserved HTTP {expected_status}', samples=samples)


    def interrupted(signum, _frame):
        raise KeyboardInterrupt(f'signal {signum}')

    signal.signal(signal.SIGTERM, interrupted)
    try:
        config = json.loads(cscli('console', 'status', '-o', 'json'))
        if config.get('manual') is not False:
            raise RuntimeError('Manual decision sharing must already be disabled; refusing a community signal')
        # Independent local egress measurement prevents banning the operator/home exit.
        with build_opener(ProxyHandler({})).open('https://api.ipify.org', timeout=15) as response:
            home_ip = public_ip(response.read(100).decode())
        manifest = yaml.safe_load((ROOT / 'infrastructure/base/vpn-gateway/tests/canary-pod.yaml').read_text())
        key = next(e['valueFrom']['secretKeyRef']['key'] for c in manifest['spec']['containers']
                   for e in c.get('env', []) if e['name'] == 'WIREGUARD_PRIVATE_KEY')
        pods = json.loads(kubectl('get', 'pods', '-A', '-o', 'json').stdout)['items']
        for pod in pods:
            if pod['status'].get('phase') in ('Succeeded', 'Failed'):
                continue
            for container in pod['spec'].get('containers', []):
                for env in container.get('env', []):
                    ref = env.get('valueFrom', {}).get('secretKeyRef', {})
                    if ref.get('name') == 'protonvpn-credentials' and ref.get('key') == key:
                        raise RuntimeError(f'VPN canary key is in use by {pod["metadata"]["name"]}')
        manifest['metadata']['name'] = name
        manifest['spec']['automountServiceAccountToken'] = False
        app = next(c for c in manifest['spec']['containers'] if c['name'] == 'probe')
        app.update(image='curlimages/curl:8.16.0', command=['sleep', '100000'])
        # Mark ownership before the API call: cleanup also handles an ambiguous timeout.
        created = True
        kubectl('create', '-f', '-', stdin=json.dumps(manifest))
        kubectl('-n', 'vpn-gateway', 'wait', '--for=condition=Ready', f'pod/{name}', '--timeout=180s', timeout=195)
        deadline = time.monotonic() + 180
        vpn_ip = None
        while time.monotonic() < deadline:
            try:
                vpn_ip = exit_ip()
                break
            except RuntimeError:
                time.sleep(5)
        if vpn_ip is None or vpn_ip == home_ip:
            raise RuntimeError('Independent VPN public egress was not established')
        report['vpn_ip'] = vpn_ip
        stage('independent VPN egress', ip=vpn_ip)
        decisions = json.loads(cscli('decisions', 'list', '--ip', vpn_ip, '--all', '-o', 'json')) or []
        if any(decision_applies(d, vpn_ip)
               for alert in decisions for d in alert.get('decisions', []) or []):
            raise RuntimeError('VPN IP already has an enforced decision; choose a different exit')
        baseline, origin = request()
        if baseline not in (200, 401):
            raise RuntimeError(f'Baseline HTTP {baseline}; expected 200 or 401, no redirects')
        report['origin_ip'] = origin
        stage('unbanned baseline', status=baseline, origin=origin)
        ban_attempted = True
        cscli('decisions', 'add', '--ip', vpn_ip, '--duration', '10m' if args.ha else '5m', '--reason', reason)
        wait_status(403, vpn_ip)
        stage('external request blocked', status=403)
        for header in ('X-Forwarded-For: 192.168.1.1', 'X-Real-IP: 192.168.1.1', 'CF-Connecting-IP: 192.168.1.1'):
            if exit_ip() != vpn_ip or request([header]) != (403, report['origin_ip']):
                raise RuntimeError('Forwarded-header spoofing changed the blocked response')
        stage('untrusted IP headers cannot bypass ban')
        if args.ha:
            replace_replica('lapi', 403)
        cscli('decisions', 'delete', '--origin', 'cscli', '--scenario', reason)
        ban_attempted = False
        wait_status(baseline, vpn_ip)
        stage('access restored after scoped unban', status=baseline)
        if args.ha:
            replace_replica('appsec', baseline)
        report['passed'] = True
    except (Exception, KeyboardInterrupt) as exc:
        report['error'] = str(exc)
        print(f'FAIL: {exc}', file=sys.stderr, flush=True)
    finally:
        if ban_attempted:
            try:
                cscli('decisions', 'delete', '--origin', 'cscli', '--scenario', reason)
            except Exception:
                cleaned = False
                print(f'CLEANUP FAILED: decision {reason}; test decision TTL is the backstop', file=sys.stderr)
        if created:
            try:
                kubectl('-n', 'vpn-gateway', 'delete', 'pod', name, '--ignore-not-found', '--wait=false')
            except Exception:
                cleaned = False
                print(f'CLEANUP FAILED: delete pod vpn-gateway/{name}', file=sys.stderr)
        report['cleanup_succeeded'] = cleaned
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2) + '\n')
    return 0 if report['passed'] and cleaned else 1


if __name__ == '__main__':
    sys.exit(main())
