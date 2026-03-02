# Ollama model management buttons
#
# Usage:
#   load('./tilt/_shared/ollama_ops.star', 'ollama_buttons')
#   ollama_buttons('ollama', 'catalyst-llm')

load('ext://uibutton', 'cmd_button', 'text_input')

def ollama_buttons(resource_name, namespace='catalyst-llm'):
    """
    Add Ollama model management buttons to a resource.

    Args:
        resource_name: Tilt resource to attach buttons to
        namespace: Kubernetes namespace where Ollama runs
    """
    cmd_button(
        name='btn-ollama-list',
        resource=resource_name,
        argv=['sh', '-c', 'kubectl exec -n ' + namespace + ' deploy/ollama -- ollama list'],
        text='List Models',
        icon_name='list'
    )

    cmd_button(
        name='btn-ollama-ps',
        resource=resource_name,
        argv=['sh', '-c', 'kubectl exec -n ' + namespace + ' deploy/ollama -- ollama ps'],
        text='Running Models',
        icon_name='memory'
    )

    cmd_button(
        name='btn-pull-model',
        resource=resource_name,
        argv=['sh', '-c', '''
            if [ -z "$MODEL_NAME" ]; then
                echo "Error: Please enter a model name"
                exit 1
            fi
            echo "Pulling model: $MODEL_NAME" && \
            kubectl exec -n ''' + namespace + ''' deploy/ollama -- ollama pull "$MODEL_NAME" && \
            echo "Model $MODEL_NAME pulled successfully"
        '''],
        text='Pull Model',
        icon_name='download',
        inputs=[
            text_input('MODEL_NAME', 'Model name (e.g., llama3.2, qwen2.5-coder:7b, mistral)')
        ]
    )

    cmd_button(
        name='btn-delete-model',
        resource=resource_name,
        argv=['sh', '-c', '''
            if [ -z "$MODEL_NAME" ]; then
                echo "Error: Please enter a model name"
                exit 1
            fi
            echo "Deleting model: $MODEL_NAME" && \
            kubectl exec -n ''' + namespace + ''' deploy/ollama -- ollama rm "$MODEL_NAME" && \
            echo "Model $MODEL_NAME deleted"
        '''],
        text='Delete Model',
        icon_name='delete',
        inputs=[
            text_input('MODEL_NAME', 'Model to delete')
        ]
    )
