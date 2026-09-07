#!/usr/bin/env python3
"""Replay fixtures through the installed CrowdSec engine without posting LAPI alerts.
Requires kubectl and PyYAML. Uses a private copy of configuration inside an agent.
"""
import json
import subprocess
import uuid
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]

def kube(*args, data=None):
    return subprocess.run(['kubectl', '-n', 'crowdsec', *args], input=data,
                          text=True, capture_output=True, check=True).stdout

pods = json.loads(kube('get', 'pods', '-l', 'type=agent', '-o', 'json'))['items']
pod = next(p['metadata']['name'] for p in pods if any(
    c['type'] == 'Ready' and c['status'] == 'True' for c in p['status']['conditions']))
work = '/tmp/crowdsec-parser-audit-' + uuid.uuid4().hex

def remote(*args, data=None):
    return kube('exec', '-i', pod, '-c', 'crowdsec-agent', '--', *args, data=data)

try:
    remote('cp', '-rf', '/etc/crowdsec', work)
    remote('sed', '-i', 's@/etc/crowdsec/@' + work + '/@g', work + '/config.yaml')
    values = yaml.safe_load((ROOT / 'infrastructure/base/crowdsec/helmrelease.yaml').read_text())['spec']['values']
    parser = values['config']['parsers']['s01-parse']['cowrie-logs.yaml']
    # The custom parser is a mounted regular file, not a symlink to hub content.
    remote('sh', '-c', 'cat > "$1"', 'audit', work + '/parsers/s01-parse/cowrie-logs.yaml', data=parser)
    stamp = '2026-09-07T17:15:00Z'
    cases = []
    for event in ['session.connect', 'login.failed', 'login.success', 'command.input', 'session.closed']:
        cases.append(({'eventid': 'cowrie.' + event, 'src_ip': '198.51.100.42', 'timestamp': stamp}, True))
    for ip in ['10.244.3.223', '192.168.1.33', 'fd00::1']:
        cases.append(({'eventid': 'cowrie.session.connect', 'src_ip': ip, 'timestamp': stamp}, False))
    cases.append(({'eventid': 'cowrie.session.connect', 'timestamp': stamp}, False))
    lines = [stamp + ' stdout F ' + json.dumps(event) for event, _ in cases]
    remote('sh', '-c', 'cat > "$1"', 'audit', work + '/fixtures.log', data='\n'.join(lines) + '\n')
    output = remote('cscli', '-c', work + '/config.yaml', 'explain', '--file', work + '/fixtures.log',
                    '--type', 'containerd', '--labels', 'program:cowrie', '-v')
    # Explain also emits anonymous overflow records and may reorder events.
    chunks = {chunk.splitlines()[0]: chunk for chunk in output.split('line: ')[1:] if chunk.startswith(stamp)}
    assert set(chunks) == set(lines), output
    for (event, expected), line in zip(cases, lines):
        chunk = chunks[line]
        fired = 'homelab/cowrie-activity' in chunk
        assert fired == expected, chunk
        if expected:
            assert 'evt.Meta.source_ip' in chunk and 'evt.Meta.log_type' in chunk, chunk
        print('PASS', event['eventid'], event.get('src_ip', 'missing-source'), 'scenario=' + str(fired))
    # A public tarpit HTTP request must match the detect-only scenario.
    event = {'ClientHost': '198.51.100.43', 'RequestHost': 'trap.knowledgedump.space',
             'RequestMethod': 'GET', 'RequestPath': '/audit', 'RequestProtocol': 'HTTP/1.1',
             'DownstreamStatus': 200, 'StartUTC': stamp, 'request_User-Agent': 'GPTBot'}
    output = remote('cscli', '-c', work + '/config.yaml', 'explain', '--log',
                    stamp + ' stdout F ' + json.dumps(event), '--type', 'containerd',
                    '--labels', 'program:traefik', '-v')
    assert 'homelab/iocaine-tarpit' in output, output
    assert 'homelab/iocaine-tarpit' in yaml.safe_load(values['config']['simulation.yaml'])['exclusions']
    assert 'homelab/cowrie-activity' not in yaml.safe_load(values['config']['simulation.yaml'])['exclusions']
    print('PASS tarpit scenario matches; tarpit simulated, Cowrie enforced')
finally:
    remote('rm', '-rf', work)
