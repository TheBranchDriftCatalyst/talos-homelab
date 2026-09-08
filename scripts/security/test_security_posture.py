#!/usr/bin/env python3
"""Security contracts: offline by default; add --live for running-system assertions.

Requires PyYAML. Live mode requires kubectl and LAN access to the public registry.
Live checks are read-only except one harmless registry GET with synthetic headers.
VPN/HA fault injection remains an explicit separate command.
"""
import argparse
import ast
import fnmatch
import json
import re
import subprocess
import sys
import time
import unittest
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import yaml

ROOT = Path(__file__).resolve().parents[2]
LIVE = False


def document(path):
    return yaml.safe_load((ROOT / path).read_text())


def crowdsec_values():
    return document('infrastructure/base/crowdsec/helmrelease.yaml')['spec']['values']


def run(*args, timeout=45):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, cwd=ROOT)
    if result.returncode:
        detail = ''
        if len(args) > 1 and str(args[1]).endswith('.py'):
            detail = '\n' + (result.stdout + result.stderr)[-2400:]
        raise AssertionError(f'{args[0]} command failed (exit {result.returncode}); evidence unavailable{detail}')
    return result.stdout


def kube(*args):
    return run('kubectl', '--request-timeout=30s', *args)


def pod_list(namespace, selector):
    pods = json.loads(kube('-n', namespace, 'get', 'pods', '-l', selector, '-o', 'json'))['items']
    active = [p for p in pods if not p['metadata'].get('deletionTimestamp')]
    if not active:
        raise AssertionError(f'No active pods found for {namespace}/{selector}; evidence unavailable')
    return active


def predicate(expression, host, path, outband=False):
    """Evaluate the supported host/path policy subset, not arbitrary Python/YAML.

This models boolean scope for regression cases. CrowdSec -t separately checks
native config compilation; this helper fails closed on unfamiliar syntax.
"""
    expression = expression.replace('req.Host', 'host').replace('req.URL.Path', 'path')
    expression = re.sub(r'path startsWith ("[^"]*")', r'path.startswith(\1)', expression)
    expression = expression.replace('&&', ' and ').replace('||', ' or ').replace('IsOutBand', 'outband')
    tree = ast.parse(expression, mode='eval')
    allowed = (ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.Compare, ast.In,
               ast.List, ast.Constant, ast.Name, ast.Load, ast.Call, ast.Attribute)
    for node in ast.walk(tree):
        if not isinstance(node, allowed):
            raise AssertionError(f'Unsupported policy syntax: {type(node).__name__}')
        if isinstance(node, ast.Name) and node.id not in ('host', 'path', 'outband'):
            raise AssertionError('Unsupported policy variable')
        if isinstance(node, ast.Attribute) and not (
                isinstance(node.value, ast.Name) and node.value.id == 'path' and node.attr == 'startswith'):
            raise AssertionError('Unsupported policy method')
        if isinstance(node, ast.Call) and (not isinstance(node.func, ast.Attribute) or node.keywords):
            raise AssertionError('Unsupported policy call')
    return eval(compile(tree, '<appsec-scope>', 'eval'), {'__builtins__': {}},
                {'host': host, 'path': path, 'outband': outband})


def assert_scope(test, config):
    paths = ['/api/v1/users/current/heartbeats', '/api/v1/users/current/heartbeats.bulk',
             '/api/v1/users/current/import', '/api/v1/users/current/db/import']
    for stage in ('pre_eval', 'on_match'):
        rules = config[stage]
        test.assertTrue(rules, f'{stage}: expected telemetry exception is missing')
        expressions = [r['filter'] for r in rules]
        for host in ('boomtime.knowledgedump.space', 'dev.boomtime.knowledgedump.space', 'boomtime.talos00'):
            for path in paths:
                test.assertTrue(any(predicate(e, host, path, True) for e in expressions), (stage, host, path))
        for host in ('registry.knowledgedump.space', 'auth.knowledgedump.space',
                     'evil.boomtime.knowledgedump.space', 'boomtime.knowledgedump.space.evil.invalid'):
            for path in paths:
                test.assertFalse(any(predicate(e, host, path, True) for e in expressions),
                                 f'Telemetry bypass PRESENT on unrelated host {host}')
        for path in ('/', '/login', '/api/v1/admin', '/api/v1/users/current/profile'):
            test.assertFalse(any(predicate(e, 'boomtime.knowledgedump.space', path, True) for e in expressions))
        if stage == 'on_match':
            test.assertFalse(any(predicate(e, 'boomtime.knowledgedump.space', paths[0], False) for e in expressions),
                             'In-band alert cancellation must NOT be present')


def assert_no_api_token(test, podspec):
    test.assertIs(podspec.get('automountServiceAccountToken'), False, 'Automatic API token mounting must NOT be enabled')
    for volume in podspec.get('volumes', []):
        test.assertFalse(any('serviceAccountToken' in source for source in volume.get('projected', {}).get('sources', [])),
                         'Projected Kubernetes API token is PRESENT')
    for container in podspec.get('containers', []) + podspec.get('initContainers', []):
        for mount in container.get('volumeMounts', []):
            test.assertNotIn('/var/run/secrets/kubernetes.io/serviceaccount', mount['mountPath'],
                             'API credential mount is PRESENT')


class RepositoryPosture(unittest.TestCase):
    def test_sensitive_headers_not_retained(self):
        docs = list(yaml.safe_load_all((ROOT / 'infrastructure/base/traefik/helmrelease.yaml').read_text()))
        values = next(d for d in docs if d['kind'] == 'HelmRelease')['spec']['values']
        fields = values['accessLog']['fields']
        self.assertEqual(fields['defaultMode'], 'keep', 'Native fields required for parsing must remain')
        headers = fields['headers']
        self.assertEqual(headers['defaultMode'], 'drop', 'Unknown secret headers must NOT be retained')
        self.assertEqual(headers['names'].get('User-Agent'), 'keep')
        for key in ('Cookie', 'Set-Cookie', 'Authorization', 'Proxy-Authorization', 'X-Api-Key'):
            self.assertEqual(headers['names'].get(key, headers['defaultMode']), 'drop', f'{key} logging is PRESENT')

    def test_boomtime_exemption_absent_on_other_hosts(self):
        assert_scope(self, yaml.safe_load(crowdsec_values()['appsec']['configs']['appsec-detect.yaml']))

    def test_honeypot_and_tarpit_have_no_api_token(self):
        for app in ('honeypot', 'iocaine'):
            with self.subTest(app=app):
                assert_no_api_token(self, document(f'infrastructure/base/{app}/deployment.yaml')['spec']['template']['spec'])

    def test_enforcement_has_no_unbounded_fail_open(self):
        plugin = document('infrastructure/base/crowdsec/bouncer-middleware.yaml')['spec']['plugin']['bouncer']
        self.assertGreater(int(plugin['updateMaxFailure']), 0)
        self.assertLessEqual(int(plugin['updateMaxFailure']), 5)
        for key in ('streamStartupBlock', 'crowdsecAppsecUnreachableBlock', 'crowdsecAppsecFailureBlock'):
            self.assertEqual(str(plugin[key]).lower(), 'true', key)

    def test_ha_has_no_single_replica_or_colocation(self):
        for component in ('lapi', 'appsec'):
            config = crowdsec_values()[component]
            self.assertGreaterEqual(config['replicas'], 2)
            self.assertEqual(config['strategy']['rollingUpdate']['maxUnavailable'], 0)
            terms = config['affinity']['podAntiAffinity']['requiredDuringSchedulingIgnoredDuringExecution']
            self.assertTrue(any(t['topologyKey'] == 'kubernetes.io/hostname' and
                                t['labelSelector']['matchLabels'].get('type') == component for t in terms))

    def test_exporter_has_versioned_user_agent(self):
        tree = ast.parse((ROOT / 'infrastructure/base/crowdsec/decision-exporter/exporter.py').read_text())
        agents = [value.value for node in ast.walk(tree) if isinstance(node, ast.Dict)
                  for key, value in zip(node.keys, node.values)
                  if isinstance(key, ast.Constant) and key.value == 'User-Agent' and isinstance(value, ast.Constant)]
        self.assertEqual(len(agents), 1)
        self.assertRegex(agents[0], r'^crowdsec-decision-inventory/[^/\s]+$')

    def test_acquisition_survives_pod_hash_changes(self):
        values = crowdsec_values()['agent']
        for item in values['acquisition']:
            self.assertNotRegex(item['podName'], r'-[0-9a-f]+\*$', 'ReplicaSet hash pinned in log selector')
            self.assertIs(item.get('poll_without_inotify'), True)
        for program, good, bad in (
            ('immich', 'immich-99bd54b7c9-abcde_media-private_immich-server-123.log',
             'immich-99bd54b7c9-abcde_media-private_immich-ml-123.log'),
            ('home-assistant', 'homeassistant-6c4fd7d8b9-abcde_home-automation_homeassistant-123.log',
             'homeassistant-postgres-1_home-automation_postgres-123.log')):
            sources = [x for x in values['additionalAcquisition'] if x.get('labels', {}).get('program') == program]
            self.assertTrue(sources, f'Missing {program} acquisition')
            globs = [f for x in sources for f in x['filenames']]
            self.assertTrue(any(fnmatch.fnmatch('/var/log/containers/' + good, g) for g in globs))
            self.assertFalse(any(fnmatch.fnmatch('/var/log/containers/' + bad, g) for g in globs))

    def test_registration_and_inventory_regressions(self):
        for script in ('check-crowdsec-registration.py', 'test-crowdsec-decision-exporter.py', 'test-crowdsec-vpn.py'):
            with self.subTest(script=script):
                run(sys.executable, str(ROOT / 'scripts/security' / script))


class RunningSystemPosture(unittest.TestCase):
    def setUp(self):
        if not LIVE:
            self.skipTest('requires --live; NOT asserted against running system')

    def test_api_tokens_not_present_in_live_honeypot_or_tarpit(self):
        for namespace, app in (('honeypot', 'cowrie'), ('iocaine', 'iocaine')):
            for pod in pod_list(namespace, f'app={app}'):
                with self.subTest(pod=pod['metadata']['name']):
                    assert_no_api_token(self, pod['spec'])

    def test_live_appsec_exemptions_are_host_scoped(self):
        for pod in pod_list('crowdsec', 'k8s-app=crowdsec,type=appsec'):
            raw = kube('-n', 'crowdsec', 'exec', pod['metadata']['name'], '-c', 'crowdsec-appsec', '--',
                       'cat', '/etc/crowdsec/appsec-configs/appsec-detect.yaml')
            assert_scope(self, yaml.safe_load(raw))

    def test_native_appsec_config_compiles(self):
        kube('-n', 'crowdsec', 'exec', 'deploy/crowdsec-appsec', '-c', 'crowdsec-appsec', '--', 'crowdsec', '-t')

    def test_simulation_matches_actual_runtime_scenario_name(self):
        pod = pod_list('crowdsec', 'k8s-app=crowdsec,type=agent')[0]['metadata']['name']
        scenario = yaml.safe_load(kube('-n', 'crowdsec', 'exec', pod, '-c', 'crowdsec-agent', '--',
                                      'cat', '/etc/crowdsec/scenarios/http-dos-switching-ua.yaml'))
        simulation = yaml.safe_load(kube('-n', 'crowdsec', 'exec', pod, '-c', 'crowdsec-agent', '--',
                                        'cat', '/etc/crowdsec/simulation.yaml'))
        self.assertIs(simulation['simulation'], False, 'Global simulation must NOT be enabled')
        self.assertIn(scenario['name'], simulation['exclusions'], 'Intended simulation is ABSENT for runtime scenario name')
        cowrie = yaml.safe_load(crowdsec_values()['config']['scenarios']['cowrie-activity.yaml'])
        self.assertNotIn(cowrie['name'], simulation['exclusions'], 'Cowrie enforcement must NOT be simulated')

    def test_live_redundancy_and_agent_coverage(self):
        for component in ('lapi', 'appsec'):
            pods = pod_list('crowdsec', f'k8s-app=crowdsec,type={component}')
            ready = [p for p in pods if any(c['type'] == 'Ready' and c['status'] == 'True' for c in p['status'].get('conditions', []))]
            self.assertGreaterEqual(len(ready), 2, f'{component} redundancy is MISSING')
            self.assertGreaterEqual(len({p['spec']['nodeName'] for p in ready}), 2)
        state = json.loads(kube('-n', 'crowdsec', 'get', 'ds', 'crowdsec-agent', '-o', 'json'))['status']
        self.assertGreater(state['desiredNumberScheduled'], 0)
        self.assertEqual(state.get('numberReady'), state['desiredNumberScheduled'], 'Agent coverage is INCOMPLETE')

    def test_inventory_warnings_not_present_and_feed_current(self):
        for pod in pod_list('crowdsec', 'k8s-app=crowdsec,type=lapi'):
            logs = kube('-n', 'crowdsec', 'logs', pod['metadata']['name'], '-c', 'crowdsec-lapi', '--since=2m')
            self.assertFalse(any('bad user agent' in line and 'crowdsec-decision-inventory' in line
                                 for line in logs.splitlines()), 'Inventory User-Agent warning is PRESENT in last 2m')
        raw = kube('-n', 'crowdsec', 'exec', 'deploy/crowdsec-decision-exporter', '--', 'python', '-c',
                   'from urllib.request import urlopen; print(urlopen("http://127.0.0.1:9108/metrics").read().decode())')
        self.assertIn('crowdsec_decision_inventory_success 1\n', raw)
        timestamp = next(float(line.split()[1]) for line in raw.splitlines()
                         if line.startswith('crowdsec_decision_inventory_last_success_timestamp_seconds '))
        self.assertLess(abs(time.time() - timestamp), 90, 'Decision feed is STALE')

    def test_sensitive_headers_not_present_in_actual_access_log(self):
        marker = 'crowdsec-posture-test/' + uuid.uuid4().hex
        headers = {'User-Agent': marker, 'Cookie': 'posture=synthetic',
                   'Authorization': 'Bearer synthetic-posture-test', 'X-Api-Key': 'synthetic-posture-test'}
        request = Request('https://registry.knowledgedump.space/v2/', headers=headers)
        try:
            with build_opener(ProxyHandler({})).open(request, timeout=15) as response:
                status = response.status
        except HTTPError as error:
            status = error.code
        self.assertIn(status, (200, 401), 'Test endpoint unavailable; evidence cannot be generated')
        pods = pod_list('traefik', 'app.kubernetes.io/name=traefik')
        found = []
        for _attempt in range(3):
            for pod in pods:
                logs = kube('-n', 'traefik', 'logs', pod['metadata']['name'], '--since=2m', '--tail=1000')
                for line in logs.splitlines():
                    if marker not in line:
                        continue
                    entry = json.loads(line)
                    if entry.get('request_User-Agent') == marker:
                        found.append(entry)
            if found:
                break
            time.sleep(2)
        self.assertTrue(found, 'No correlated access log found; absence of evidence is NOT a pass')
        for entry in found:
            leaked = [key for key in entry if key.startswith(('request_', 'response_', 'origin_')) and
                      any(secret in key.lower() for secret in ('cookie', 'authorization', 'api-key'))]
            self.assertEqual(leaked, [], 'Sensitive header fields are PRESENT; values intentionally not printed')
            for field in ('ClientHost', 'RequestPath', 'RequestMethod', 'DownstreamStatus', 'request_User-Agent'):
                self.assertIn(field, entry, f'Required CrowdSec field is MISSING: {field}')

    def test_live_cowrie_and_tarpit_parser_regressions(self):
        run(sys.executable, str(ROOT / 'scripts/security/check-crowdsec-parsers.py'), timeout=120)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Assert running-cluster state and emit one synthetic-header registry GET')
    args, remaining = parser.parse_known_args()
    LIVE = args.live
    unittest.main(argv=[sys.argv[0], *remaining], verbosity=2)
