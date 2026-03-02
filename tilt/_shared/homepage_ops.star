# Homepage API sync button
#
# Usage:
#   load('./tilt/_shared/homepage_ops.star', 'homepage_sync_button')
#   homepage_sync_button('homepage', './applications/arr-stack/scripts/sync-api-keys.sh')

load('ext://uibutton', 'cmd_button')

def homepage_sync_button(resource_name, sync_script_path, namespace='media'):
    """
    Add Homepage API key sync button to a resource.

    Args:
        resource_name: Tilt resource to attach button to
        sync_script_path: Path to the sync-api-keys.sh script
        namespace: Kubernetes namespace where Homepage runs
    """
    cmd_button(
        name='btn-sync-api-keys',
        resource=resource_name,
        argv=['sh', '-c', sync_script_path + ''' && \
            kubectl rollout restart deployment homepage -n ''' + namespace + ''' && \
            kubectl rollout status deployment homepage -n ''' + namespace + ''' --timeout=60s && \
            echo "" && echo "Homepage restarted with updated API keys"'''],
        text='Sync API Keys',
        icon_name='sync'
    )
