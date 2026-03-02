# Cluster operations nav buttons
load('ext://uibutton', 'cmd_button', 'location', 'choice_input')

def cleanup_nav_button():
    cmd_button(
        name='btn-cleanup',
        argv=['sh', '-c', '''case "$CLEANUP_TYPE" in
            failed) kubectl delete pods --field-selector=status.phase=Failed -A;;
            completed) kubectl delete pods --field-selector=status.phase=Succeeded -A;;
            evicted) kubectl get pods -A -ojson | jq -r '.items[] | select(.status.reason=="Evicted") | .metadata.namespace + " " + .metadata.name' | xargs -rn2 kubectl delete pod -n;;
            all) kubectl delete pods --field-selector=status.phase=Failed -A 2>/dev/null; kubectl delete pods --field-selector=status.phase=Succeeded -A 2>/dev/null;;
        esac'''],
        location=location.NAV, text='Cleanup', icon_name='auto_delete',
        inputs=[choice_input('CLEANUP_TYPE', 'Type', ['all', 'failed', 'completed', 'evicted'])],
        requires_confirmation=True
    )

def health_nav_button():
    cmd_button(
        name='btn-cluster-health',
        argv=['sh', '-c', 'kubectl get nodes -owide; echo; kubectl get pods -A | grep -Ev "Running|Completed|^NAMESPACE" || echo "All healthy"'],
        location=location.NAV, text='Health', icon_name='favorite'
    )

def pods_nav_button(namespaces=['all', 'media', 'monitoring', 'argocd', 'traefik', 'kube-system']):
    cmd_button(
        name='btn-pods',
        argv=['sh', '-c', '[ "$NAMESPACE" = all ] && kubectl get pods -A || kubectl get pods -n "$NAMESPACE"'],
        location=location.NAV, text='Pods', icon_name='view_list',
        inputs=[choice_input('NAMESPACE', 'Namespace', namespaces)]
    )
