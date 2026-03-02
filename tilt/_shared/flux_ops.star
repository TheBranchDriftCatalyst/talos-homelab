# Flux GitOps nav buttons
load('ext://uibutton', 'cmd_button', 'location', 'choice_input')

def flux_nav_button():
    cmd_button(
        name='btn-flux',
        argv=['sh', '-c', '''case "$FLUX_ACTION" in
            sync) flux reconcile kustomization flux-system --with-source;;
            suspend) flux suspend kustomization --all;;
            resume) flux resume kustomization --all;;
            status) flux get all;;
        esac'''],
        location=location.NAV,
        text='Flux',
        icon_name='sync',
        inputs=[choice_input('FLUX_ACTION', 'Action', ['status', 'sync', 'suspend', 'resume'])]
    )
