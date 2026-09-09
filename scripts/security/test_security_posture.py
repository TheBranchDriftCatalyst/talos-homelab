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


def cilium_policy(path, name):
    for doc in documents(path):
        if doc.get('kind') == 'CiliumNetworkPolicy' and doc['metadata']['name'] == name:
            return doc
    raise AssertionError(f'CiliumNetworkPolicy {name} not found in {path}')


def ingress_pod_namespaces(policy):
    """Namespaces of every fromEndpoints (pod) source across all ingress rules."""
    namespaces = set()
    for rule in policy['spec'].get('ingress', []):
        for selector in rule.get('fromEndpoints', []):
            namespaces.add(selector.get('matchLabels', {}).get('k8s:io.kubernetes.pod.namespace'))
    return namespaces


def ingress_entities(policy):
    """Union of every fromEntities entity across all ingress rules."""
    entities = set()
    for rule in policy['spec'].get('ingress', []):
        entities.update(rule.get('fromEntities', []))
    return entities


def assert_no_wan_or_cidr_ingress(test, policy):
    """No ingress rule may admit the internet (`world`) or a raw CIDR block."""
    for rule in policy['spec'].get('ingress', []):
        test.assertNotIn('fromCIDR', rule, 'raw-CIDR ingress opens an east-west hole')
        test.assertNotIn('fromCIDRSet', rule, 'raw-CIDR ingress opens an east-west hole')
    test.assertNotIn('world', ingress_entities(policy), 'internet (world) ingress must NOT be allowed')
    # Only node-level entities are acceptable (kubelet probes / cilium health).
    test.assertTrue(ingress_entities(policy) <= {'host', 'remote-node', 'health'},
                    'only host/remote-node/health entities may be admitted')



def qbit_seed_conf_args():
    """The seed-webui-auth initContainer python source that writes qBittorrent.conf."""
    spec = document('applications/arr-stack/base/qbittorrent/deployment.yaml')['spec']['template']['spec']
    for container in spec['initContainers']:
        if container['name'] == 'seed-webui-auth':
            return '\n'.join(container['args'])
    raise AssertionError('seed-webui-auth initContainer not found')


def middleware(path, name):
    for doc in documents(path):
        if doc.get('kind') == 'Middleware' and doc['metadata']['name'] == name:
            return doc
    raise AssertionError(f'Middleware {name} not found in {path}')


def clusterpolicy(path, name):
    for doc in documents(path):
        if doc.get('kind') == 'ClusterPolicy' and doc['metadata']['name'] == name:
            return doc
    raise AssertionError(f'ClusterPolicy {name} not found in {path}')


def zipline_container_image():
    spec = document('applications/zipline/deployment.yaml')['spec']['template']['spec']
    return next(c['image'] for c in spec['containers'] if c['name'] == 'zipline')


class AuthentikTag:
    """Opaque stand-in for authentik's blueprint tags (!Env/!Find/!KeyOf).

    The blueprint YAML embedded in the authentik ConfigMaps uses application
    custom tags that PyYAML's SafeLoader cannot resolve. We register them as
    opaque so the surrounding structure (providers, redirect_uris, flows) still
    parses; `.tag` is the suffix ('Env'/'Find'/'KeyOf'), `.value` the raw arg.
    """

    def __init__(self, tag, value):
        self.tag = tag
        self.value = value

    def __repr__(self):
        return f'AuthentikTag({self.tag!r}, {self.value!r})'


def _blueprint_loader():
    class Loader(yaml.SafeLoader):
        pass

    def opaque(loader, tag_suffix, node):
        if isinstance(node, yaml.ScalarNode):
            return AuthentikTag(tag_suffix, loader.construct_scalar(node))
        if isinstance(node, yaml.SequenceNode):
            return AuthentikTag(tag_suffix, loader.construct_sequence(node, deep=True))
        return AuthentikTag(tag_suffix, loader.construct_mapping(node, deep=True))

    Loader.add_multi_constructor('!', opaque)
    return Loader


def blueprint_entries(path):
    """Every blueprint entry across all embedded data values of a blueprint ConfigMap."""
    cm = document(path)
    loader = _blueprint_loader()
    entries = []
    for value in (cm.get('data') or {}).values():
        parsed = yaml.load(value, Loader=loader)
        if isinstance(parsed, dict):
            entries.extend(parsed.get('entries') or [])
    return entries


def oauth2_providers(path):
    return [e for e in blueprint_entries(path)
            if e.get('model') == 'authentik_providers_oauth2.oauth2provider']


def oauth2_provider(path, name):
    for provider in oauth2_providers(path):
        if provider.get('attrs', {}).get('name') == name:
            return provider
    raise AssertionError(f'OAuth2Provider {name} not found in {path}')


def authorization_flow_slug(provider):
    """The slug of a provider's authorization_flow !Find tag."""
    flow = provider['attrs']['authorization_flow']
    # !Find [authentik_flows.flow, [slug, <slug>]] -> value == ['authentik_flows.flow', ['slug', <slug>]]
    return flow.value[1][1] if isinstance(flow, AuthentikTag) else flow


ALL_BLUEPRINTS = sorted((ROOT / 'infrastructure/base/authentik').glob('*-blueprint.yaml'))


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

    def test_ingressroute_combined_entrypoints_denied(self):
        # TALOS-lxz5.6.2 (finding 014): a validating policy must deny web+websecure on one router
        # (the tls-default mutate would then break the plaintext :80 path silently).
        pol = clusterpolicy('infrastructure/base/kyverno-policies/ingressroute-no-combined-entrypoints.yaml', 'ingressroute-no-combined-entrypoints')
        self.assertEqual(pol['spec'].get('failurePolicy'), 'Ignore', 'guardrail must fail-open, not block all IngressRoute admission')
        rule = pol['spec']['rules'][0]
        self.assertEqual(rule['validate'].get('failureAction'), 'Enforce', 'policy must Enforce (prevent the broken state)')
        conds = rule['validate']['deny']['conditions']['all']
        keys = ' '.join(c['key'] for c in conds)
        self.assertIn("'web'", keys); self.assertIn("'websecure'", keys)

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

    def test_guacamole_ingress_restricted_to_traefik(self):
        # TALOS-lxz5.3.2 (finding 003): guacamole trusts X-authentik-username for
        # auto-login, so any pod could POST to guacamole.gaming.svc:8080 with a
        # forged header. A CiliumNetworkPolicy must select the guacamole webapp and
        # admit :8080 ingress ONLY from Traefik (the ingress path) — no other pod
        # namespace, no world, no raw CIDR. The guacd/postgres/DNS egress the app
        # needs must remain, so the lockdown does not break the RDP/VNC stack.
        policy = cilium_policy('applications/gaming/base/kubevirt/guacamole-network-policy.yaml', 'guacamole')
        self.assertEqual(policy['spec']['endpointSelector']['matchLabels'], {'app': 'guacamole'},
                         'policy must select the guacamole webapp endpoints')
        self.assertEqual(ingress_pod_namespaces(policy), {'traefik'},
                         'only Traefik pods may reach guacamole east-west (found other/forgeable sources)')
        assert_no_wan_or_cidr_ingress(self, policy)
        # The one pod-ingress rule must be scoped to :8080/TCP.
        traefik_rule = next(r for r in policy['spec']['ingress'] if r.get('fromEndpoints'))
        ports = {(p['port'], p['protocol']) for tp in traefik_rule['toPorts'] for p in tp['ports']}
        self.assertEqual(ports, {('8080', 'TCP')}, 'Traefik ingress must be limited to :8080/TCP')
        # Egress the webapp legitimately needs must remain (guacd, postgres, DNS) —
        # otherwise the lockdown would sever the working remote-desktop path.
        egress = policy['spec'].get('egress', [])
        selectors = [s.get('matchLabels', {}) for rule in egress for s in rule.get('toEndpoints', [])]
        self.assertTrue(any(s.get('app') == 'guacd' for s in selectors), 'guacd egress (:4822) MISSING')
        self.assertTrue(any(s.get('cnpg.io/cluster') == 'guacamole-postgres' for s in selectors),
                        'postgres egress (:5432) MISSING')
        self.assertTrue(any(s.get('k8s-app') == 'kube-dns' for s in selectors), 'DNS egress MISSING')

    def test_authentik_cache_ingress_restricted_to_authentik(self):
        # TALOS-lxz5.3.3 (finding 017): the authentik-cache Dragonfly runs with no
        # password, so anything that can reach :6379 can use the cache. A
        # CiliumNetworkPolicy must select the cache and admit :6379 ingress from the
        # Authentik server + worker (its clients) and the monitoring exporter only —
        # no world, no raw CIDR.
        policy = cilium_policy('infrastructure/base/authentik/dragonfly-network-policy.yaml', 'authentik-cache')
        self.assertEqual(policy['spec']['endpointSelector']['matchLabels'], {'app': 'authentik-cache'},
                         'policy must select the authentik-cache Dragonfly endpoints')
        assert_no_wan_or_cidr_ingress(self, policy)
        self.assertEqual(ingress_pod_namespaces(policy), {'authentik', 'monitoring'},
                         'cache ingress must come only from authentik (server/worker) + monitoring')
        # Server and worker must each be admitted on :6379.
        wanted = {'server', 'worker'}
        found = set()
        for rule in policy['spec'].get('ingress', []):
            for selector in rule.get('fromEndpoints', []):
                labels = selector.get('matchLabels', {})
                if labels.get('app.kubernetes.io/name') == 'authentik':
                    ports = {(p['port'], p['protocol']) for tp in rule.get('toPorts', []) for p in tp['ports']}
                    self.assertEqual(ports, {('6379', 'TCP')}, 'authentik client ingress must be :6379/TCP')
                    found.add(labels.get('app.kubernetes.io/component'))
        self.assertEqual(found, wanted, 'both authentik server and worker must be admitted to the cache')

    def test_authentik_cache_password_status_is_documented(self):
        # TALOS-lxz5.3.3 part (a): the Dragonfly password is a coordinated two-sided
        # rollout and was intentionally DEFERRED (documented, not half-applied). This
        # asserts the state stays coherent: either dragonfly.yaml still carries the
        # explicit passwordless rationale (deferred), or a real password is wired via
        # spec.authentication. It fails only if the file goes silently inconsistent.
        dragonfly = document('infrastructure/base/authentik/dragonfly.yaml')
        has_auth = 'authentication' in dragonfly['spec']
        text = (ROOT / 'infrastructure/base/authentik/dragonfly.yaml').read_text()
        documented = 'NO password' in text or 'no-auth' in text
        self.assertTrue(has_auth or documented,
                        'cache password is neither configured nor its deferral documented')

    def test_public_rate_limit_and_body_cap_middlewares_exist(self):
        # TALOS-lxz5.4.2 (finding 009): there was NO rateLimit / inFlightReq /
        # body-cap Middleware anywhere in the repo, so every public route was
        # unthrottled at the proxy. A conservative per-source rateLimit and a
        # request body-size cap must now exist in the traefik namespace.
        path = 'infrastructure/base/traefik/middlewares.yaml'
        rl = middleware(path, 'rate-limit')['spec']['rateLimit']
        self.assertGreater(int(rl['average']), 0, 'rateLimit average must throttle')
        self.assertGreaterEqual(int(rl['burst']), int(rl['average']), 'burst should be >= average')
        buf = middleware(path, 'request-body-limit')['spec']['buffering']
        self.assertGreater(int(buf['maxRequestBodyBytes']), 0, 'body cap must be bounded')

    def test_zipline_public_route_is_rate_limited_body_capped_and_pinned(self):
        # TALOS-lxz5.4.1 (findings 009 & 007): zipline.amberdark.net was the ONLY
        # routed public amberdark app and carried ONLY security-headers — no
        # throttle, no body cap — on a mutable :latest image. It must now keep
        # security-headers AND carry the rate-limit + body-cap middlewares, and
        # the image must be pinned to an immutable digest (not the floating tag).
        route = next(r for r in ingressroute('applications/zipline/ingressroute.yaml', 'zipline-priv-domain')['spec']['routes']
                     if 'zipline.amberdark.net' in r['match'])
        mw = route_middleware_names(route)
        for name in ('security-headers', 'rate-limit', 'request-body-limit'):
            self.assertIn(('traefik', name), mw, f'zipline public route missing {name} middleware')
        image = zipline_container_image()
        self.assertIn('@sha256:', image, 'zipline image is NOT pinned to an immutable digest')
        self.assertNotRegex(image, r':latest(@|$)', 'zipline image still rides the mutable :latest tag')

    def test_public_routes_carry_rate_limit(self):
        # TALOS-lxz5.4.2 (finding 009): the unthrottled public login/upload/clone
        # surfaces (auth, forge, registry) must each carry the rate-limit
        # middleware on their public IngressRoute route.
        for path, name, host in (
            ('infrastructure/base/authentik/ingressroute.yaml', 'authentik', 'auth.knowledgedump.space'),
            ('infrastructure/base/forgejo/ingressroute.yaml', 'forgejo-public', 'forge.knowledgedump.space'),
            ('infrastructure/base/registry/zot/ingressroute.yaml', 'zot-public', 'registry.knowledgedump.space'),
        ):
            with self.subTest(host=host):
                route = next(r for r in ingressroute(path, name)['spec']['routes'] if host in r['match'])
                self.assertIn(('traefik', 'rate-limit'), route_middleware_names(route),
                              f'{host} public route is NOT rate-limited')

    def test_amberdark_hostname_claim_policy_restricts_namespaces(self):
        # TALOS-lxz5.4.3 (finding 012): auth.amberdark.net is a dangling,
        # pre-trusted hostname and allowCrossNamespace=true lets any namespace
        # claim it (or any *.amberdark.net) under the valid wildcard cert. A
        # validating Kyverno policy must ENFORCE that only allowlisted namespaces
        # may create an IngressRoute referencing an amberdark.net host.
        policy = clusterpolicy('infrastructure/base/kyverno-policies/restrict-public-hostname-claims.yaml',
                               'restrict-public-hostname-claims')
        rule = next(r for r in policy['spec']['rules'] if 'validate' in r)
        self.assertEqual(rule['validate']['failureAction'], 'Enforce',
                         'hostname-claim policy must ENFORCE, not merely Audit')
        conditions = rule['validate']['deny']['conditions']['all']
        # One condition keys on amberdark.net; one restricts the namespace.
        self.assertTrue(any('amberdark.net' in str(c.get('key', '')) for c in conditions),
                        'policy does not key on amberdark.net hosts')
        ns_cond = next(c for c in conditions if str(c.get('key', '')).strip() == '{{ request.namespace }}')
        self.assertIn(ns_cond['operator'], ('AnyNotIn', 'NotIn'), 'namespace guard must be a not-in-allowlist check')
        self.assertIn('media-private', ns_cond['value'], 'zipline namespace must stay allowlisted (no self-lockout)')

    def test_no_oidc_provider_defaults_to_empty_client_secret(self):
        # TALOS-lxz5.5.2 (finding 013): a two-arg `client_secret: !Env [VAR, ""]` default
        # mints a CONFIDENTIAL OAuth2 client with an EMPTY secret whenever the env var is
        # unset (the worker envs are optional:true) — anyone who learns client_id could
        # then complete the confidential flow. Bare `!Env VAR` instead resolves to null
        # when unset and the serializer REJECTS the entry, so a missing secret fails
        # loudly. No provider in any blueprint may keep the empty-string fallback.
        offenders = []
        for path in ALL_BLUEPRINTS:
            rel = path.relative_to(ROOT)
            for provider in oauth2_providers(rel):
                secret = provider['attrs'].get('client_secret')
                if (isinstance(secret, AuthentikTag) and secret.tag == 'Env'
                        and isinstance(secret.value, list) and len(secret.value) > 1
                        and secret.value[1] == ''):
                    offenders.append(f"{rel}:{provider['attrs'].get('name')}")
        self.assertEqual(offenders, [],
                         f'client_secret with an empty !Env default remains: {offenders}')

    def test_https_capable_oidc_providers_have_no_http_redirect(self):
        # TALOS-lxz5.5.3 (finding 015): a confidential OIDC client that registers an
        # http:// redirect_uri accepts the authorization code / token over plaintext. Every
        # provider that IS reachable over HTTPS (it registers a public https:// callback)
        # must register ONLY https:// redirect_uris. The three below were audited against
        # their IngressRoutes as HTTPS-capable and had their stale http:// LAN variants
        # dropped.
        #
        # Deliberately NOT asserted (documented http-only exceptions, verified against
        # their IngressRoutes): grafana + minio serve ONLY the plaintext `web` entrypoint
        # (no TLS/websecure route exists to redirect to); litellm's route lives in the
        # catalyst-llm SISTER repo and cannot be verified offline (its http/https variants
        # are the same host, so http isn't redundant to a public HTTPS host). Switching
        # those to https:// would break login — see the blueprint comments.
        for name, blueprint in (
            ('zot', 'infrastructure/base/authentik/zot-blueprint.yaml'),
            ('forgejo', 'infrastructure/base/authentik/forgejo-blueprint.yaml'),
            ('boomtime', 'infrastructure/base/authentik/boomtime-blueprint.yaml'),
        ):
            with self.subTest(provider=name):
                provider = oauth2_provider(blueprint, name)
                urls = [r['url'] for r in provider['attrs']['redirect_uris']]
                self.assertTrue(urls, f'{name} has no redirect_uris')
                for url in urls:
                    self.assertTrue(url.startswith('https://'),
                                    f'{name} still registers a non-HTTPS redirect_uri: {url}')

    def test_minio_scope_mapping_has_no_blanket_readonly(self):
        # TALOS-lxz5.5.4 (finding 016): the MinIO `policy` ScopeMapping ended with a
        # blanket `return {"policy": "readonly"}`, so EVERY authenticated authentik user
        # was granted read access to all MinIO buckets (only the app PolicyBinding gated
        # it). Admins must still get consoleAdmin; everyone else must get NO policy claim
        # (MinIO then grants no access) so access requires explicit group membership.
        mapping = next((e for e in blueprint_entries('infrastructure/base/authentik/minio-blueprint.yaml')
                        if e.get('model') == 'authentik_providers_oauth2.scopemapping'
                        and e.get('identifiers', {}).get('scope_name') == 'minio'), None)
        self.assertIsNotNone(mapping, 'minio policy ScopeMapping not found')
        expression = mapping['attrs']['expression']
        # Assert on executable code only — the rationale comment legitimately names the
        # retired blanket default.
        code = '\n'.join(l for l in expression.splitlines() if not l.strip().startswith('#'))
        self.assertIn('consoleAdmin', code, 'admin consoleAdmin path must remain')
        self.assertNotIn('readonly', code,
                         'blanket readonly policy default is STILL present — every authenticated user gets read access')

    def test_high_value_oidc_providers_require_explicit_consent(self):
        # TALOS-lxz5.5.5 (finding 018): providers on the implicit-consent authorization
        # flow complete silently, so a replayed/stolen authorization request never surfaces
        # to the user. The higher-value providers must use the explicit-consent flow so the
        # user has to approve each authorization. (Low-value first-party apps stay implicit.)
        explicit = 'default-provider-authorization-explicit-consent'
        for name, blueprint in (
            ('grafana', 'infrastructure/base/authentik/grafana-blueprint.yaml'),
            ('minio', 'infrastructure/base/authentik/minio-blueprint.yaml'),
            ('forgejo', 'infrastructure/base/authentik/forgejo-blueprint.yaml'),
        ):
            with self.subTest(provider=name):
                slug = authorization_flow_slug(oauth2_provider(blueprint, name))
                self.assertEqual(slug, explicit,
                                 f'{name} must use the explicit-consent authorization flow (got {slug})')

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
