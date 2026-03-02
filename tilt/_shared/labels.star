# Centralized label constants for Tilt UI grouping
#
# Usage:
#   load('./tilt/_shared/labels.star', 'LABELS')
#   k8s_attach('sonarr', ..., labels=[LABELS.MEDIA])

# Label struct - access via LABELS.MEDIA, LABELS.PLATFORM, etc.
LABELS = struct(
    # Application groups
    MEDIA = '1-apps-media',
    HOME = '1-apps-home',
    GAMING = '1-apps-gaming',

    # Infrastructure groups
    PLATFORM = '2-infra-platform',
    OBSERVE = '3-infra-observe',

    # Utility groups
    TOOLS = '4-tools',
    OPS = '5-ops',

    # Specialized stacks
    VPN = '6-vpn-gateway',
    LLM = '7-catalyst-llm',
    LOCAL = '8-local-dev',
)
