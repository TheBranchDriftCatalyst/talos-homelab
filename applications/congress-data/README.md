# congress-data

Congress.gov data pipeline — standalone Dagster code location registered against the shared platform (`applications/dagster/`).

## Pipeline Stages

| Stage | Asset | Status | Dependencies |
|-------|-------|--------|-------------|
| 1. Extraction | `congress_bills`, `congress_members`, `congress_committees` | Working | Congress.gov API key |
| 2. Documents | `congress_documents` | Working | Stage 1 |
| 3. NER | `congress_entities` | Stubbed | spaCy or Ollama |
| 4. Embeddings | `congress_embeddings` | Stubbed | sentence-transformers |
| 5. Propositions | `congress_propositions` | Stubbed | LLM backend |
| 6. Graph | `congress_graph` | Stubbed | Neo4j |

## Local Development

```bash
pip install -e ".[dev]"
export CONGRESS_API_KEY=your_key_here

# Verify definitions load
python -c "from congress_data import defs; print(defs)"

# Run Dagster dev UI
dagster dev -m congress_data
```

## Docker

```bash
docker build -t congress-data:latest .
docker run --rm -e CONGRESS_API_KEY=your_key congress-data:latest \
  python -c "from congress_data import defs; print('OK')"
```

## Kubernetes

```bash
# Dry run
kubectl apply -k k8s/ --dry-run=client

# Deploy
kubectl apply -k k8s/

# Register with Dagster platform
kubectl apply -f ../../applications/dagster/workspace.yaml
```

Runs in `congress-gov` namespace. Code server on gRPC port 4000.

## Configuration

| Env Var | Description | Default |
|---------|-------------|---------|
| `CONGRESS_API_KEY` | Congress.gov API key (required) | — |
| `OLLAMA_URL` | Ollama endpoint for NER (stage 3) | — |
| `NEO4J_URI` | Neo4j bolt URI (stage 6) | — |

## Architecture

```
core/           Base abstractions (future shared library)
  base_api_client.py   Rate limiting, pagination, retry
  base_entity.py       Pydantic base with source tracking
  document.py          Unified datalake Document model

client.py       CongressAPIClient — Congress.gov v3
entities.py     Bill, Member, Committee domain models
config.py       Dagster Config class

assets/         Pipeline stages (ordered)
  extraction.py    Stage 1: raw API extraction
  documents.py     Stage 2: entity → Document transform
  entities_ner.py  Stage 3: NER (stubbed)
  embeddings.py    Stage 4: embeddings (stubbed)
  propositions.py  Stage 5: S-P-O (stubbed)
  graph.py         Stage 6: Neo4j loading (stubbed)
```
