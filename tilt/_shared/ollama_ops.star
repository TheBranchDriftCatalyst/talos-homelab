# Ollama model management buttons
load('ext://uibutton', 'cmd_button', 'text_input')

def ollama_buttons(resource_name, namespace='catalyst-llm'):
    base = 'kubectl exec -n %s deploy/ollama -- ollama' % namespace
    cmd_button(name='btn-ollama-list', resource=resource_name,
               argv=['sh', '-c', base + ' list'], text='List', icon_name='list')
    cmd_button(name='btn-ollama-ps', resource=resource_name,
               argv=['sh', '-c', base + ' ps'], text='Running', icon_name='memory')
    cmd_button(name='btn-pull-model', resource=resource_name,
               argv=['sh', '-c', base + ' pull "${MODEL_NAME:?Enter model name}"'],
               text='Pull', icon_name='download',
               inputs=[text_input('MODEL_NAME', 'Model (e.g. llama3.2)')])
    cmd_button(name='btn-delete-model', resource=resource_name,
               argv=['sh', '-c', base + ' rm "${MODEL_NAME:?Enter model name}"'],
               text='Delete', icon_name='delete',
               inputs=[text_input('MODEL_NAME', 'Model to delete')])
