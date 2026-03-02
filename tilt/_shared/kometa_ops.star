# Kometa operation buttons
#
# Usage:
#   load('./tilt/_shared/kometa_ops.star', 'kometa_buttons')
#   kometa_buttons('kometa', 'media')

load('ext://uibutton', 'cmd_button')

def kometa_buttons(resource_name, namespace='media'):
    """
    Add Kometa operation buttons to a resource.

    Args:
        resource_name: Tilt resource to attach buttons to
        namespace: Kubernetes namespace where Kometa runs
    """
    cmd_button(
        name='btn-kometa-run',
        resource=resource_name,
        argv=['sh', '-c', '''
            echo "Starting Kometa run..." && \
            kubectl exec -n ''' + namespace + ''' deploy/kometa -c kometa -- python kometa.py --run && \
            echo "Kometa run complete"
        '''],
        text='Run Now',
        icon_name='play_arrow'
    )

    cmd_button(
        name='btn-kometa-overlays',
        resource=resource_name,
        argv=['sh', '-c', '''
            echo "Running Kometa overlays only..." && \
            kubectl exec -n ''' + namespace + ''' deploy/kometa -c kometa -- python kometa.py --run --overlays-only && \
            echo "Overlays complete"
        '''],
        text='Overlays Only',
        icon_name='layers'
    )

    cmd_button(
        name='btn-kometa-collections',
        resource=resource_name,
        argv=['sh', '-c', '''
            echo "Running Kometa collections only..." && \
            kubectl exec -n ''' + namespace + ''' deploy/kometa -c kometa -- python kometa.py --run --collections-only && \
            echo "Collections complete"
        '''],
        text='Collections Only',
        icon_name='folder_special'
    )
