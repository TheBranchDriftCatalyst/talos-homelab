# Kometa operation buttons
load('ext://uibutton', 'cmd_button')

def kometa_buttons(resource_name, namespace='media'):
    base = 'kubectl exec -n %s deploy/kometa -c kometa -- python kometa.py --run' % namespace
    cmd_button(name='btn-kometa-run', resource=resource_name,
               argv=['sh', '-c', base], text='Run Now', icon_name='play_arrow')
    cmd_button(name='btn-kometa-overlays', resource=resource_name,
               argv=['sh', '-c', base + ' --overlays-only'], text='Overlays', icon_name='layers')
    cmd_button(name='btn-kometa-collections', resource=resource_name,
               argv=['sh', '-c', base + ' --collections-only'], text='Collections', icon_name='folder_special')
