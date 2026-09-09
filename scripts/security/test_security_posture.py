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
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

import yaml

ROOT = Path(__file__).resolve().parents[2]
LIVE = False


def document(path):
    return yaml.safe_load((ROOT / path).read_text())


def crowdsec_values():
    return document('infrastructure/base/crowdsec/helmrelease.yaml')['spec']['values']


def traefik_values():
    docs = yaml.safe_load_all((ROOT / 'infrastructure/base/traefik/helmrelease.yaml').read_text())
    return next(d for d in docs if d and d.get('kind') == 'HelmRelease')['spec']['values']


def documents(path):
    return [d for d in yaml.safe_load_all((ROOT / path).read_text()) if d]


def ingressroute(path, name):
    for doc in documents(path):
        if doc.get('kind') == 'IngressRoute' and doc['metadata']['name'] == name:
            return doc
    raise AssertionError(f'IngressRoute {name} not found in {path}')


def route_middleware_names(route):
    """Set of (namespace, name) middleware refs on an IngressRoute route."""
    return {(m.get('namespace'), m['name']) for m in route.get('middlewares', [])}



def qbit_seed_conf_args():
    """The seed-webui-auth initContainer python source that writes qBittorrent.conf."""
    spec = document('applications/arr-stack/base/qbittorrent/deployment.yaml')['spec']['template']['spec']
    for container in spec['initContainers']:
        if container['name'] == 'seed-webui-auth':
            return '\n'.join(container['args'])
    raise AssertionError('seed-webui-auth initContainer not found')


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

    def test_traefik_api_insecure_disabled(self):
        # TALOS-lxz5.1 (5.1.1): --api.insecure exposed the full Traefik API
        # (incl. /api/rawdata) unauthenticated. It must not be present.
        args = traefik_values()['additionalArguments']
        self.assertFalse(any(a.split('=')[0].strip() == '--api.insecure' for a in args),
                         '--api.insecure must NOT be enabled')
        self.assertTrue(any(a.strip() == '--api.dashboard=true' for a in args),
                        '--api.dashboard should remain enabled')

    def test_traefik_dashboard_off_plaintext_and_authenticated(self):
        # TALOS-lxz5.1 (5.1.1): dashboard must not sit on plaintext `web` and must be
        # gated by forward-auth / lan-only.
        dashboard = traefik_values()['ingressRoute']['dashboard']
        self.assertTrue(dashboard.get('enabled'))
        entrypoints = dashboard['entryPoints']
        self.assertNotIn('web', entrypoints, 'Dashboard must NOT be on the plaintext web entrypoint')
        self.assertEqual(entrypoints, ['websecure'], 'Dashboard must be HTTPS-only on websecure')
        mw = {(m['namespace'], m['name']) for m in dashboard.get('middlewares', [])}
        self.assertIn(('authentik', 'authentik'), mw, 'Authentik forward-auth middleware MISSING on dashboard')
        self.assertIn(('traefik', 'lan-only'), mw, 'lan-only middleware MISSING on dashboard')

    def test_traefik_forwarded_trusted_ips_exclude_pod_cidr(self):
        # TALOS-lxz5.1.4: trusting 10.0.0.0/8 let any pod forge X-Forwarded-For.
        trusted = traefik_values()['ports']['web']['forwardedHeaders']['trustedIPs']
        self.assertNotIn('10.0.0.0/8', trusted, 'Pod/service CIDR must NOT be a trusted XFF source')
        self.assertIn('173.245.48.0/20', trusted, 'Cloudflare ranges must remain trusted')
        self.assertNotIn('10.0.0.0/8', traefik_values()['ports']['websecure']['forwardedHeaders']['trustedIPs'])

    def test_crowdsec_bouncer_trusted_ips_exclude_pod_cidr(self):
        # TALOS-lxz5.1.4b: pod CIDR must not spoof client IP nor bypass the bouncer.
        plugin = document('infrastructure/base/crowdsec/bouncer-middleware.yaml')['spec']['plugin']['bouncer']
        self.assertNotIn('10.0.0.0/8', plugin['forwardedHeadersTrustedIPs'])
        self.assertNotIn('10.0.0.0/8', plugin['clientTrustedIPs'])
        self.assertIn('192.168.0.0/16', plugin['clientTrustedIPs'],
                      'LAN admin range must remain so operators are never locked out')

    def test_qbittorrent_has_no_unauthenticated_api_carveout(self):
        # TALOS-lxz5.2 (5.2.2): a priority /api route bypassed forward-auth; combined with
        # the pod-CIDR subnet whitelist that made /api/v2 unauth from the internet. EVERY
        # route on the qbittorrent IngressRoute must now carry the authentik forward-auth
        # middleware (no un-gated carve-out remains).
        routes = ingressroute('applications/arr-stack/base/qbittorrent/ingressroute.yaml', 'qbittorrent')['spec']['routes']
        self.assertTrue(routes)
        for route in routes:
            with self.subTest(match=route['match']):
                self.assertIn(('authentik', 'authentik'), route_middleware_names(route),
                              f'qbittorrent route {route["match"]!r} is NOT gated by authentik forward-auth')

    def test_qbittorrent_subnet_whitelist_is_not_pod_cidr(self):
        # TALOS-lxz5.2 (5.2.2): WebUI\AuthSubnetWhitelist must NOT contain the whole pod
        # CIDR (10.244.0.0/16) — that pre-authenticated any Traefik-forwarded request.
        # Only in-pod localhost may bypass qBittorrent's own login.
        src = qbit_seed_conf_args()
        wl_lines = [l for l in src.splitlines() if 'WL_KEY +' in l and '=' in l]
        self.assertTrue(wl_lines, 'AuthSubnetWhitelist assignment not found in seed script')
        joined = '\n'.join(wl_lines)
        self.assertNotIn('10.244.0.0/16', joined, 'Pod CIDR is STILL whitelisted for qBittorrent auth bypass')
        self.assertNotRegex(joined, r'10\.244\.', 'A pod-CIDR range is STILL whitelisted for qBittorrent auth bypass')
        self.assertIn('127.0.0.1', joined, 'localhost bypass for the in-pod port-sync sidecar is missing')

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

    def test_frigate_api_route_is_ip_restricted(self):
        # TALOS-lxz5.2 (5.2.1): the priority-100 `/api` route on frigate.talos00 had NO
        # middleware, so `curl -H 'X-authentik-username: admin' .../api/config` returned
        # 200 from the internet with camera rtsp creds (Frigate maps that header to a
        # user). The un-authenticated carve-out must now be source-restricted so the
        # internet cannot reach it; HA (in-cluster / LAN) still can via `lan-only`.
        route = next((r for r in ingressroute('applications/scratch/frigate/ingressroute.yaml', 'frigate')['spec']['routes']
                      if 'PathPrefix(`/api`)' in r['match']), None)
        self.assertIsNotNone(route, 'frigate /api route missing')
        mw = route_middleware_names(route)
        self.assertTrue(('traefik', 'lan-only') in mw or ('authentik', 'authentik') in mw,
                        'frigate /api carve-out has NO lan-only/forward-auth middleware — internet-reachable header injection')

    def test_inbound_authentik_headers_are_stripped_at_entrypoint(self):
        # TALOS-lxz5.2 (5.2.3): a headers middleware must CLEAR inbound X-authentik-* so a
        # client cannot forge identity to a header-trusting backend, and it must be wired
        # as a default entrypoint middleware on BOTH web and websecure (runs before any
        # forward-auth / un-gated route).
        mw = next((d for d in documents('infrastructure/base/traefik/middlewares.yaml')
                   if d.get('kind') == 'Middleware' and d['metadata']['name'] == 'strip-authentik-headers'), None)
        self.assertIsNotNone(mw, 'strip-authentik-headers Middleware is MISSING')
        cleared = mw['spec']['headers']['customRequestHeaders']
        for header in ('X-Authentik-Username', 'X-Authentik-Groups', 'X-Authentik-Email',
                       'X-Authentik-Name', 'X-Authentik-Uid', 'X-Authentik-Jwt'):
            self.assertEqual(cleared.get(header, 'MISSING'), '', f'{header} inbound copy is NOT cleared')
        # Only REQUEST headers are touched — must not strip response headers.
        self.assertNotIn('customResponseHeaders', mw['spec']['headers'],
                         'strip middleware must not alter response headers')
        # Wired as a default entrypoint middleware, ordered before the crowdsec bouncer,
        # on both entrypoints (authoritative CLI args override ports.<ep>.middlewares).
        args = traefik_values()['additionalArguments']
        for ep in ('web', 'websecure'):
            flag = next((a for a in args if a.startswith(f'--entrypoints.{ep}.http.middlewares=')), None)
            self.assertIsNotNone(flag, f'entrypoint {ep} has no default middleware chain')
            chain = flag.split('=', 1)[1].split(',')
            self.assertIn('traefik-strip-authentik-headers@kubernetescrd', chain,
                          f'inbound authentik-header strip MISSING on entrypoint {ep}')
            self.assertLess(chain.index('traefik-strip-authentik-headers@kubernetescrd'),
                            chain.index('traefik-bouncer@kubernetescrd') if 'traefik-bouncer@kubernetescrd' in chain else len(chain),
                            'strip must run before the bouncer')

    def test_forward_auth_still_reissues_identity_headers(self):
        # The inbound strip is only safe because the authentik forward-auth middleware
        # re-adds the authenticated identity from the OUTPOST response. That contract must
        # remain intact (TALOS-lxz5.2 / 5.2.3) or gated apps lose their SSO identity.
        mw = next(d for d in documents('infrastructure/base/authentik/middleware.yaml')
                  if d.get('kind') == 'Middleware' and d['metadata']['name'] == 'authentik')
        resp = mw['spec']['forwardAuth']['authResponseHeaders']
        for header in ('X-authentik-username', 'X-authentik-groups', 'X-authentik-email'):
            self.assertIn(header, resp, f'{header} no longer re-issued by forward-auth — SSO identity broken')

    def test_registration_and_inventory_regressions(self):
        for script in ('check-crowdsec-registration.py', 'test-crowdsec-decision-exporter.py', 'test-crowdsec-vpn.py'):
            with self.subTest(script=script):
                run(sys.executable, str(ROOT / 'scripts/security' / script))


class RunningSystemPosture(unittest.TestCase):
    def setUp(self):
        if not LIVE:
            self.skipTest('requires --live; NOT asserted against running system')

    def test_live_traefik_dashboard_api_not_unauthenticated(self):
        # TALOS-lxz5.1 (5.1.1): the confirmed exploit was unauthenticated GET /api/rawdata
        # -> 200 on plaintext web. Assert it is no longer reachable unauthenticated.
        if not LIVE:
            self.skipTest('requires --live; NOT asserted against running system')
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        checked = 0
        for url in ('http://traefik.talos00/api/rawdata',
                    'https://traefik.talos00/api/rawdata',
                    'https://traefik.talos00/dashboard/'):
            request = Request(url, headers={'User-Agent': 'crowdsec-posture-test'})
            opener = build_opener(HTTPSHandler(context=ctx), ProxyHandler({}))
            try:
                with opener.open(request, timeout=15) as response:
                    status = response.status
            except HTTPError as error:
                status = error.code
            except OSError:
                continue
            checked += 1
            self.assertNotEqual(status, 200, f'Traefik API/dashboard served unauthenticated at {url}')
            self.assertIn(status, (301, 302, 401, 403, 404), f'Unexpected status {status} at {url}')
        self.assertGreater(checked, 0, 'Traefik endpoint unreachable; evidence cannot be generated')

    def test_live_traefik_dashboard_login_reachable(self):
        # TALOS-lxz5.1.5: after gating the dashboard behind authentik, the outpost must
        # actually recognize traefik.talos00 (an app/provider exists) so login redirects
        # (302) rather than 404ing. Pairs with the lockdown test above.
        if not LIVE:
            self.skipTest('requires --live; NOT asserted against running system')
        import ssl
        ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
        request = Request('https://traefik.talos00/', headers={'User-Agent': 'crowdsec-posture-test'})
        opener = build_opener(HTTPSHandler(context=ctx), ProxyHandler({}))
        try:
            with opener.open(request, timeout=15) as response:
                status = response.status
        except HTTPError as error:
            status = error.code
        except OSError:
            self.skipTest('traefik.talos00 unreachable from here (LAN-only)')
        self.assertNotEqual(status, 404, 'Dashboard host not registered in authentik (outpost 404) — login cannot complete')
        self.assertIn(status, (302, 200), f'Expected auth redirect/app, got {status}')

    def _status(self, url, headers=None):
        # Read-only GET returning the HTTP status (or None if unreachable, e.g. LAN-only).
        import ssl
        ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
        request = Request(url, headers={'User-Agent': 'crowdsec-posture-test', **(headers or {})})
        opener = build_opener(HTTPSHandler(context=ctx), ProxyHandler({}))
        try:
            with opener.open(request, timeout=15) as response:
                return response.status
        except HTTPError as error:
            return error.code
        except OSError:
            return None

    def test_live_frigate_forged_identity_header_does_not_bypass_auth(self):
        # TALOS-lxz5.2 (5.2.1/5.2.3): a forged X-authentik-username must NOT authenticate.
        # On the gated default route it must redirect to Authentik (not 200). On the /api
        # carve-out the entrypoint strip removes the forged header so Frigate cannot map it
        # to a user — the request must not come back as an impersonated 200.
        gated = self._status('https://frigate.talos00/', {'X-authentik-username': 'admin'})
        if gated is not None:
            self.assertNotEqual(gated, 200, 'Forged identity header bypassed Frigate forward-auth on the default route')
            self.assertIn(gated, (301, 302, 401, 403), f'Unexpected status {gated} on frigate default route')
        api = self._status('https://frigate.talos00/api/config', {'X-authentik-username': 'admin'})
        if api is not None:
            self.assertNotEqual(api, 200, 'Forged X-authentik-username still yields 200 on frigate /api (impersonation)')

    def test_live_qbittorrent_api_not_unauthenticated(self):
        # TALOS-lxz5.2 (5.2.2): the confirmed exploit was GET /api/v2/torrents/info -> 200
        # with NO auth (unauth /api carve-out + pod-CIDR subnet bypass). It must now be
        # forward-auth gated — including when a client forges the identity header.
        checked = 0
        for headers in (None, {'X-authentik-username': 'admin'}):
            status = self._status('https://qbittorrent.talos00/api/v2/torrents/info', headers)
            if status is None:
                continue
            checked += 1
            self.assertNotEqual(status, 200, f'qBittorrent API served unauthenticated (headers={headers})')
            self.assertIn(status, (301, 302, 401, 403, 404), f'Unexpected status {status} on qBittorrent /api/v2')
        self.assertGreater(checked, 0, 'qbittorrent.talos00 unreachable; evidence cannot be generated')

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
