# Root Tiltfile - Talos Homelab Ops Dashboard
# Observes Flux-managed cluster, provides ops UI and port-forwards
#
# Usage:
#   tilt up                    # Start dashboard
#   tilt up -- --port-forward  # Start with all port-forwards active
#
# This Tiltfile does NOT deploy anything - Flux manages all deployments.
# It only observes existing resources and provides ops tooling.

# Load Tilt extensions
load('ext://uibutton', 'cmd_button', 'location', 'text_input', 'bool_input', 'choice_input')
load('ext://k8s_attach', 'k8s_attach')

# Load shared modules
load('./tilt/_shared/labels.star', 'LABELS')
load('./tilt/_shared/flux_ops.star', 'flux_nav_button')
load('./tilt/_shared/cluster_ops.star', 'cleanup_nav_button', 'health_nav_button', 'pods_nav_button')
load('./tilt/_shared/kometa_ops.star', 'kometa_buttons')
load('./tilt/_shared/homepage_ops.star', 'homepage_sync_button')

# Configuration
config.define_string('k8s_context', args=False, usage='Kubernetes context to use')
cfg = config.parse()

settings = {
    'k8s_context': cfg.get('k8s_context', 'admin@catalyst-cluster'),
}

# Cluster context
allow_k8s_contexts('admin@catalyst-cluster')

print("""
======================================================================
  Talos Homelab - Ops Dashboard (Observe-Only Mode)
======================================================================
  Context: %s
  Flux: ACTIVE (not suspended - Flux owns all deployments)

  This dashboard observes your cluster and provides:
  - Log streaming for all workloads
  - Port-forwards to services
  - Ops buttons for common tasks
  - Manual job triggers (GPU tests, cleanup, etc.)
======================================================================
""" % settings['k8s_context'])

# ============================================
# LABEL CONSTANTS - From shared module
# ============================================
LABEL_MEDIA = LABELS.MEDIA
LABEL_PLATFORM = LABELS.PLATFORM
LABEL_OBSERVE = LABELS.OBSERVE
LABEL_TOOLS = LABELS.TOOLS
LABEL_OPS = LABELS.OPS

# ============================================
# NAV BUTTONS - From shared modules
# ============================================

flux_nav_button()
health_nav_button()
cleanup_nav_button()
pods_nav_button(['all', 'media', 'monitoring', 'observability', 'argocd', 'traefik', 'kube-system', 'intel-device-plugins', 'gaming', 'home-automation', 'tdarr', 'zipline'])

# ============================================
# OPS - Manual tasks and jobs
# ============================================

local_resource(
    'cluster-status',
    '''echo "CLUSTER STATUS" && echo "=================" && \
       echo "" && echo "Nodes:" && kubectl get nodes -o wide && \
       echo "" && echo "Resource Usage:" && kubectl top nodes 2>/dev/null || echo "(metrics-server not ready)" && \
       echo "" && echo "Problem Pods:" && \
       kubectl get pods -A | grep -v Running | grep -v Completed | grep -v "^NAMESPACE" || echo "All pods healthy"''',
    auto_init=True,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=[LABEL_OPS]
)

local_resource(
    'cluster-events',
    'kubectl get events -A --sort-by=.lastTimestamp | tail -50',
    auto_init=False,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=[LABEL_OPS]
)

local_resource(
    'flux-status',
    'flux get all',
    auto_init=False,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=[LABEL_OPS]
)

local_resource(
    'gpu-test',
    '''kubectl delete job gpu-encode-test -n intel-device-plugins --ignore-not-found && \
       kubectl apply -f infrastructure/base/intel-gpu/gpu-test-job.yaml && \
       echo "Waiting for job to complete..." && \
       kubectl wait --for=condition=complete job/gpu-encode-test -n intel-device-plugins --timeout=120s && \
       kubectl logs job/gpu-encode-test -n intel-device-plugins''',
    auto_init=False,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=[LABEL_OPS]
)

local_resource(
    'gpu-vs-cpu-test',
    './scripts/gpu-vs-cpu-test.sh',
    auto_init=False,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=[LABEL_OPS]
)

local_resource(
    'deploy-stack',
    './scripts/deploy-stack.sh',
    auto_init=False,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=[LABEL_OPS]
)

local_resource(
    'validate-manifests',
    '''echo "Validating kustomizations..." && \
       kubectl apply --dry-run=client -k infrastructure/base/intel-gpu/ && \
       kubectl apply --dry-run=client -k infrastructure/base/monitoring/ && \
       echo "All manifests valid"''',
    auto_init=False,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=[LABEL_OPS]
)

# ============================================
# MEDIA APPS - Observe Flux-managed workloads
# ============================================

k8s_attach('sonarr', 'deployment/sonarr', namespace='media',
           port_forwards=['8989:8989'], labels=[LABEL_MEDIA])
k8s_attach('radarr', 'deployment/radarr', namespace='media',
           port_forwards=['7878:7878'], labels=[LABEL_MEDIA])
k8s_attach('prowlarr', 'deployment/prowlarr', namespace='media',
           port_forwards=['9696:9696'], labels=[LABEL_MEDIA])
k8s_attach('overseerr', 'deployment/overseerr', namespace='media',
           port_forwards=['5055:5055'], labels=[LABEL_MEDIA])
k8s_attach('plex', 'deployment/plex', namespace='media',
           port_forwards=['32400:32400'], labels=[LABEL_MEDIA])
k8s_attach('jellyfin', 'deployment/jellyfin', namespace='media',
           port_forwards=['8096:8096'], labels=[LABEL_MEDIA])
k8s_attach('tdarr', 'deployment/tdarr-server', namespace='tdarr',
           port_forwards=['8265:8265'], labels=[LABEL_MEDIA])
k8s_attach('homepage', 'deployment/homepage', namespace='media',
           port_forwards=['3001:3000'], labels=[LABEL_MEDIA])
k8s_attach('kometa', 'deployment/kometa', namespace='media', labels=[LABEL_MEDIA])
k8s_attach('posterizarr', 'deployment/posterizarr', namespace='media',
           port_forwards=['8000:8000'], labels=[LABEL_MEDIA])
k8s_attach('tautulli', 'deployment/tautulli', namespace='media',
           port_forwards=['8181:8181'], labels=[LABEL_MEDIA])
k8s_attach('posterr', 'deployment/posterr', namespace='media',
           port_forwards=['3002:3000'], labels=[LABEL_MEDIA])

# Kometa ops buttons (from shared module)
kometa_buttons('kometa', 'media')

# Homepage sync button (from shared module)
homepage_sync_button('homepage', './applications/arr-stack/scripts/sync-api-keys.sh')

# ============================================
# PLATFORM - Core infrastructure
# ============================================

# ArgoCD
k8s_attach('argocd-server', 'deployment/argocd-server', namespace='argocd',
           port_forwards=['8443:8080'], labels=[LABEL_PLATFORM])
k8s_attach('argocd-repo', 'deployment/argocd-repo-server', namespace='argocd', labels=[LABEL_PLATFORM])
k8s_attach('argocd-ctrl', 'statefulset/argocd-application-controller', namespace='argocd', labels=[LABEL_PLATFORM])

cmd_button(
    name='btn-argocd-password',
    resource='argocd-server',
    argv=['sh', '-c', 'kubectl get secret -n argocd argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d && echo'],
    text='Get Password',
    icon_name='password'
)

# Traefik (DaemonSet, not Deployment)
k8s_attach('traefik', 'daemonset/traefik', namespace='traefik',
           port_forwards=['9000:9000'], labels=[LABEL_PLATFORM])

# Registry
k8s_attach('registry', 'deployment/docker-registry', namespace='registry',
           port_forwards=['5000:5000'], labels=[LABEL_PLATFORM])

# External Secrets
k8s_attach('external-secrets', 'deployment/external-secrets', namespace='external-secrets', labels=[LABEL_PLATFORM])
k8s_attach('1password-connect', 'deployment/onepassword-connect', namespace='external-secrets', labels=[LABEL_PLATFORM])

# ============================================
# OBSERVABILITY - Monitoring & Logging
# ============================================

# Grafana Stack (grafana-operator managed)
k8s_attach('grafana', 'deployment/grafana-deployment', namespace='monitoring',
           port_forwards=['3000:3000'], labels=[LABEL_OBSERVE])
k8s_attach('mimir', 'deployment/mimir-nginx', namespace='monitoring',
           port_forwards=['9009:80'], labels=[LABEL_OBSERVE])
k8s_attach('loki', 'statefulset/loki', namespace='monitoring', labels=[LABEL_OBSERVE])
k8s_attach('tempo', 'statefulset/tempo', namespace='monitoring', labels=[LABEL_OBSERVE])
k8s_attach('alloy', 'deployment/alloy', namespace='monitoring', labels=[LABEL_OBSERVE])

cmd_button(
    name='btn-grafana-credentials',
    resource='grafana',
    argv=['sh', '-c', '''echo "=== Grafana Credentials ===" && \
        echo "Username: $(kubectl get secret -n monitoring grafana-admin-credentials -o jsonpath='{.data.GF_SECURITY_ADMIN_USER}' | base64 -d)" && \
        echo "Password: $(kubectl get secret -n monitoring grafana-admin-credentials -o jsonpath='{.data.GF_SECURITY_ADMIN_PASSWORD}' | base64 -d)"'''],
    text='Get Credentials',
    icon_name='password'
)

# Grafana Dashboard Sync - bidirectional sync between UI and JSON files
local_resource(
    'grafana-dashboards',
    './infrastructure/base/monitoring/grafana-dashboards/scripts/grafana-sync.sh status',
    deps=['./infrastructure/base/monitoring/grafana-dashboards/json'],
    auto_init=True,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=[LABEL_OBSERVE]
)

cmd_button(
    name='btn-dashboards-pull',
    resource='grafana-dashboards',
    argv=['./infrastructure/base/monitoring/grafana-dashboards/scripts/grafana-sync.sh', 'pull'],
    text='Pull from Grafana',
    icon_name='cloud_download'
)

cmd_button(
    name='btn-dashboards-push',
    resource='grafana-dashboards',
    argv=['./infrastructure/base/monitoring/grafana-dashboards/scripts/grafana-sync.sh', 'push'],
    text='Push to Cluster',
    icon_name='cloud_upload'
)

cmd_button(
    name='btn-dashboards-list',
    resource='grafana-dashboards',
    argv=['./infrastructure/base/monitoring/grafana-dashboards/scripts/grafana-sync.sh', 'list'],
    text='List Dashboards',
    icon_name='list'
)

# Legacy observability (scaled to 0, uncomment if running)
# k8s_attach('graylog', 'statefulset/graylog', namespace='observability', labels=[LABEL_OBSERVE])
# k8s_attach('opensearch', 'statefulset/opensearch-cluster-master', namespace='observability', labels=[LABEL_OBSERVE])

# ============================================
# TOOLS - Infrastructure testing UIs
# ============================================
# NOTE: infra-testing namespace doesn't exist yet. Uncomment when deployed.

# k8s_attach('headlamp', 'deployment/headlamp', namespace='infra-testing',
#            port_forwards=['8080:4466'], labels=[LABEL_TOOLS])
# k8s_attach('kubeview', 'deployment/kubeview', namespace='infra-testing',
#            port_forwards=['8081:8000'], labels=[LABEL_TOOLS])
# k8s_attach('kube-ops-view', 'deployment/kube-ops-view', namespace='infra-testing',
#            port_forwards=['8082:8080'], labels=[LABEL_TOOLS])
# k8s_attach('goldilocks', 'deployment/goldilocks-dashboard', namespace='infra-testing',
#            port_forwards=['8083:8080'], labels=[LABEL_TOOLS])

# cmd_button(
#     name='btn-headlamp-token',
#     resource='headlamp',
#     argv=['sh', '-c', 'kubectl get secret -n infra-testing headlamp-admin -o jsonpath="{.data.token}" | base64 -d && echo'],
#     text='Get Token',
#     icon_name='key'
# )

# ============================================
# VPN GATEWAY - Include vpn-gateway module
# ============================================

include('./infrastructure/base/vpn-gateway/Tiltfile')

# ============================================
# CATALYST LLM - Hybrid LLM infrastructure
# ============================================

include('./applications/catalyst-llm/Tiltfile')

# ============================================
# GAMING - KubeVirt VMs, Guacamole
# ============================================

include('./applications/gaming/Tiltfile')

# ============================================
# HOME AUTOMATION - Home Assistant, Linkwarden
# ============================================

include('./applications/home-automation/Tiltfile')

# ============================================
# TDARR - Distributed transcoding
# ============================================

include('./applications/tdarr/Tiltfile')

# ============================================
# ZIPLINE - Image/file sharing
# ============================================

include('./applications/zipline/Tiltfile')

# ============================================
# HONEYPOT - Cowrie SSH/Telnet honeypot
# ============================================

include('./infrastructure/base/honeypot/Tiltfile')

# ============================================
# CONFIGURATION
# ============================================

update_settings(
    max_parallel_updates=3,
    k8s_upsert_timeout_secs=300,
    suppress_unused_image_warnings=None
)

print("""
Ready! UI Groups:
  1-apps-media     - Sonarr, Radarr, Plex, Jellyfin, Tdarr, Zipline
  1-apps-home      - Home Assistant, Linkwarden, Omnitools
  1-apps-gaming    - Windows VM, Guacamole
  2-infra-platform - ArgoCD, Traefik, Registry, External Secrets
  3-infra-observe  - Grafana, Mimir, Loki, Tempo, Alloy
  4-security       - Cowrie Honeypot (SSH/Telnet)
  5-ops            - Cluster status, GPU tests, deployments
  6-vpn-gateway    - Gluetun, SecureXNG, VPN rotation
  7-catalyst-llm   - LLM Scaler, Ollama, Open WebUI, SillyTavern

Note: Some resources may show 'pending' if not yet deployed.
      Flux manages all deployments - Tilt only observes.
""")
