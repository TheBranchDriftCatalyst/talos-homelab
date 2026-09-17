#!/usr/bin/env python3
"""Replay fixtures through the installed CrowdSec engine without posting LAPI alerts.
Requires kubectl and PyYAML. Uses a private copy of configuration inside an agent.
"""
import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]

def kube(*args, data=None):
    return subprocess.run(['kubectl', '-n', 'crowdsec', *args], input=data,
                          text=True, capture_output=True, check=True).stdout

pods = json.loads(kube('get', 'pods', '-l', 'type=agent', '-o', 'json'))['items']
pod = next(p['metadata']['name'] for p in pods if not p['metadata'].get('deletionTimestamp') and any(
    c['type'] == 'Ready' and c['status'] == 'True' for c in p['status']['conditions']))
work = '/tmp/crowdsec-parser-audit-' + uuid.uuid4().hex

def remote(*args, data=None):
    return kube('exec', '-i', pod, '-c', 'crowdsec-agent', '--', *args, data=data)

try:
    remote('cp', '-rf', '/etc/crowdsec', work)
    remote('sed', '-i', 's@/etc/crowdsec/@' + work + '/@g', work + '/config.yaml')
    values = yaml.safe_load((ROOT / 'infrastructure/base/security/crowdsec/helmrelease.yaml').read_text())['spec']['values']
    parser = values['config']['parsers']['s01-parse']['cowrie-logs.yaml']
    # The custom parser is a mounted regular file, not a symlink to hub content.
    remote('sh', '-c', 'cat > "$1"', 'audit', work + '/parsers/s01-parse/cowrie-logs.yaml', data=parser)
    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    # homelab/cowrie-logs is deliberately narrow (TALOS-hdw8): ONLY cowrie.command.input
    # is parsed, because the only consumer is the novelty scenario, which needs the
    # command text. Every other cowrie eventid must fall through -- the haproxy front
    # remains the single ban source for mere connections.
    cases = []
    # Independent IPs prevent blackhole state coupling the fixtures.
    for index in range(3):
        cases.append(({'eventid': 'cowrie.command.input', 'src_ip': f'198.51.100.{42 + index}',
                       'input': 'uname -s -v -n -r -m', 'timestamp': stamp}, True))
    for index, event in enumerate(['session.connect', 'login.failed', 'login.success', 'session.closed']):
        cases.append(({'eventid': 'cowrie.' + event, 'src_ip': f'198.51.100.{60 + index}', 'timestamp': stamp}, False))
    for ip in ['10.244.3.223', '192.168.1.33', 'fd00::1']:
        cases.append(({'eventid': 'cowrie.command.input', 'src_ip': ip,
                       'input': 'uname -s -v -n -r -m', 'timestamp': stamp}, False))
    cases.append(({'eventid': 'cowrie.command.input', 'input': 'x', 'timestamp': stamp}, False))
    lines = [stamp + ' stdout F ' + json.dumps(event) for event, _ in cases]
    remote('sh', '-c', 'cat > "$1"', 'audit', work + '/fixtures.log', data='\n'.join(lines) + '\n')
    output = remote('cscli', '-c', work + '/config.yaml', 'explain', '--file', work + '/fixtures.log',
                    '--type', 'containerd', '--labels', 'program:cowrie', '-v')
    # Explain also emits anonymous overflow records and may reorder events.
    chunks = {chunk.splitlines()[0]: chunk for chunk in output.split('line: ')[1:] if chunk.startswith(stamp)}
    assert set(chunks) == set(lines), output
    for (event, expected), line in zip(cases, lines):
        chunk = chunks[line]
        # Assert on the PARSER, not on scenario firing: homelab/cowrie-replay-drop is a
        # conditional bucket needing >=30 events, so no single fixture can overflow it.
        parsed = 'homelab/cowrie-logs' in chunk
        assert parsed == expected, chunk
        if expected:
            assert 'evt.Meta.source_ip' in chunk and 'evt.Meta.cowrie_command' in chunk, chunk
        print('PASS', event['eventid'], event.get('src_ip', 'missing-source'), 'parsed=' + str(parsed))
    # A public tarpit HTTP request must match the detect-only scenario.
    event = {'ClientHost': '198.51.100.43', 'RequestHost': 'trap.knowledgedump.space',
             'RequestMethod': 'GET', 'RequestPath': '/audit', 'RequestProtocol': 'HTTP/1.1',
             'DownstreamStatus': 200, 'StartUTC': stamp, 'request_User-Agent': 'GPTBot'}
    output = remote('cscli', '-c', work + '/config.yaml', 'explain', '--log',
                    stamp + ' stdout F ' + json.dumps(event), '--type', 'containerd',
                    '--labels', 'program:traefik', '-v')
    assert 'homelab/iocaine-tarpit' in output, output
    exclusions = yaml.safe_load(values['config']['simulation.yaml'])['exclusions']
    assert 'homelab/iocaine-tarpit' in exclusions
    # The honeypot CONNECTION scenario must stay enforcing -- it is the single ban source.
    assert 'homelab/honeypot-vip-activity' not in exclusions
    # The replay scenario is detect-only during its soak (TALOS-hdw8). Flip this assertion
    # to `not in` when it is promoted, so the test keeps tracking intent either way.
    assert 'homelab/cowrie-replay-drop' in exclusions
    print('PASS tarpit + replay simulated; honeypot-vip-activity enforced')
finally:
    remote('rm', '-rf', work)
