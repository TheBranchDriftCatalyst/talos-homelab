# Flux GitOps operation buttons
#
# Usage:
#   load('./tilt/_shared/flux_ops.star', 'flux_nav_button')
#   flux_nav_button()

load('ext://uibutton', 'cmd_button', 'location', 'choice_input')

def flux_nav_button():
    """Add Flux operations button to nav bar."""
    cmd_button(
        name='btn-flux',
        argv=['sh', '-c', '''
            case "$FLUX_ACTION" in
                "sync") flux reconcile kustomization flux-system --with-source && echo "Flux synced" ;;
                "suspend") flux suspend kustomization --all && echo "All kustomizations suspended" ;;
                "resume") flux resume kustomization --all && echo "All kustomizations resumed" ;;
                "status") flux get all ;;
                *) echo "Unknown action: $FLUX_ACTION" ;;
            esac
        '''],
        location=location.NAV,
        text='Flux',
        icon_name='sync',
        inputs=[
            choice_input('FLUX_ACTION', 'Action', ['status', 'sync', 'suspend', 'resume'])
        ]
    )

def flux_resource_button(resource_name, kustomization_name):
    """
    Add Flux control buttons to a specific resource.

    Args:
        resource_name: Tilt resource to attach buttons to
        kustomization_name: Name of the Flux kustomization
    """
    cmd_button(
        name='btn-flux-suspend-' + kustomization_name,
        resource=resource_name,
        argv=['sh', '-c', 'flux suspend kustomization ' + kustomization_name + ' && echo "Suspended ' + kustomization_name + '"'],
        text='Suspend Flux',
        icon_name='pause'
    )

    cmd_button(
        name='btn-flux-resume-' + kustomization_name,
        resource=resource_name,
        argv=['sh', '-c', '''
            flux resume kustomization ''' + kustomization_name + ''' && \
            flux reconcile kustomization ''' + kustomization_name + ''' --with-source && \
            echo "Resumed and reconciled ''' + kustomization_name + '''"
        '''],
        text='Resume Flux',
        icon_name='play_arrow'
    )

    cmd_button(
        name='btn-flux-status-' + kustomization_name,
        resource=resource_name,
        argv=['sh', '-c', 'flux get kustomization ' + kustomization_name],
        text='Flux Status',
        icon_name='info'
    )
