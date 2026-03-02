# Cluster operations buttons
#
# Usage:
#   load('./tilt/_shared/cluster_ops.star', 'cleanup_nav_button', 'health_nav_button', 'pods_nav_button')
#   cleanup_nav_button()
#   health_nav_button()

load('ext://uibutton', 'cmd_button', 'location', 'choice_input')

def cleanup_nav_button():
    """Add pod cleanup button to nav bar."""
    cmd_button(
        name='btn-cleanup',
        argv=['sh', '-c', '''
            case "$CLEANUP_TYPE" in
                "failed") kubectl delete pods --field-selector=status.phase=Failed -A && echo "Failed pods deleted" ;;
                "completed") kubectl delete pods --field-selector=status.phase=Succeeded -A && echo "Completed pods deleted" ;;
                "evicted") kubectl get pods -A -o json | jq -r ".items[] | select(.status.reason==\"Evicted\") | .metadata.namespace + \" \" + .metadata.name" | xargs -r -n2 sh -c "kubectl delete pod -n \\$0 \\$1" && echo "Evicted pods deleted" ;;
                "all") kubectl delete pods --field-selector=status.phase=Failed -A 2>/dev/null; kubectl delete pods --field-selector=status.phase=Succeeded -A 2>/dev/null; echo "All stale pods deleted" ;;
                *) echo "Unknown cleanup type: $CLEANUP_TYPE" ;;
            esac
        '''],
        location=location.NAV,
        text='Cleanup',
        icon_name='auto_delete',
        inputs=[
            choice_input('CLEANUP_TYPE', 'Type', ['all', 'failed', 'completed', 'evicted'])
        ],
        requires_confirmation=True
    )

def health_nav_button():
    """Add cluster health check button to nav bar."""
    cmd_button(
        name='btn-cluster-health',
        argv=['sh', '-c', '''echo "=== Nodes ===" && kubectl get nodes -o wide && \
            echo "" && echo "=== Problem Pods ===" && \
            kubectl get pods -A | grep -v Running | grep -v Completed | grep -v "^NAMESPACE" || echo "All pods healthy"'''],
        location=location.NAV,
        text='Health',
        icon_name='favorite'
    )

def pods_nav_button(namespaces=['all', 'media', 'monitoring', 'observability', 'argocd', 'traefik', 'kube-system']):
    """
    Add pods list button to nav bar.

    Args:
        namespaces: List of namespace options for the dropdown
    """
    cmd_button(
        name='btn-pods',
        argv=['sh', '-c', '''
            case "$NAMESPACE" in
                "all") kubectl get pods -A ;;
                *) kubectl get pods -n "$NAMESPACE" ;;
            esac
        '''],
        location=location.NAV,
        text='Pods',
        icon_name='view_list',
        inputs=[
            choice_input('NAMESPACE', 'Namespace', namespaces)
        ]
    )
