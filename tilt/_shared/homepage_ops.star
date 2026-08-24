# Homepage sync button
load('ext://uibutton', 'cmd_button')

def homepage_sync_button(resource_name, sync_script, namespace='media'):
    cmd_button(
        name='btn-sync-api-keys', resource=resource_name,
        argv=['sh', '-c', '%s && kubectl rollout restart deploy/homepage -n %s && kubectl rollout status deploy/homepage -n %s --timeout=60s' % (sync_script, namespace, namespace)],
        text='Sync API Keys', icon_name='sync'
    )
