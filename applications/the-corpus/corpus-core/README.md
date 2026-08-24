# corpus-core

Shared ETL infrastructure for the-corpus NER training data pipeline.

## Installation

```bash
pip install -e .

# With LLM support (for entity extraction)
pip install -e ".[llm]"
```

## Components

### Clients (`corpus_core.clients`)

Rate-limited HTTP clients with retry logic:

```python
from corpus_core.clients import BaseAPIClient

class MyAPIClient(BaseAPIClient):
    @property
    def base_url(self) -> str:
        return "https://api.example.com"

    def get_items(self) -> list:
        return self.get("/items")

# With rate limiting and retries
with MyAPIClient(requests_per_hour=1000) as client:
    for item in client.paginate("/items", results_key="data"):
        process(item)
```

### Models (`corpus_core.models`)

Shared Pydantic models:

```python
from corpus_core.models import Document, ExtractedEntity

doc = Document(
    id="doc-1",
    title="Example Document",
    content="This is a test document about ACME Corp.",
    source="example.com",
    document_type="article",
    domain="generic",
)

entity = ExtractedEntity(
    entity_type="ORGANIZATION",
    properties={"name": "ACME Corp"},
    confidence=0.95,
    source_span="ACME Corp",
    domain="generic",
)
```

### Loaders (`corpus_core.loaders`)

Data loaders for various storage backends:

```python
from pathlib import Path
from corpus_core.loaders import ParquetLoader, Neo4jLoader, EmbeddingService

# Parquet (local storage)
loader = ParquetLoader(Path("./datasets"))
loader.write("congress", "bills", bills)
for batch in loader.stream("congress", "bills", batch_size=1000):
    process(batch)

# Neo4j (graph database)
with Neo4jLoader("bolt://localhost:7687", "neo4j", "password") as graph:
    graph.load_entities(entities)
    results = graph.semantic_search("climate legislation", limit=10)

# Embeddings (via Ollama)
embeddings = EmbeddingService("http://localhost:11434")
vector = embeddings.get_embedding("Example text")
```

### Extractors (`corpus_core.extractors`)

LLM-powered entity extraction:

```python
from corpus_core.extractors import BaseEntityExtractor

extractor = BaseEntityExtractor(
    ollama_url="http://localhost:11434",
    model="llama3.2",
    domain="finance",
)

entities = extractor.extract_from_text_sync(text)
```

### Schema (`corpus_core.schema`)

Ontology system for domain modeling:

```python
from corpus_core.schema import (
    Ontology,
    NodeType,
    PropertyDef,
    PropertyType,
    MCPTool,
    create_common_properties,
)
from corpus_core.schema.generators import generate_neo4j_schema

# Define domain ontology
ontology = Ontology("congress", "1.0.0")

bill = NodeType(
    name="Bill",
    domain="congress",
    description="A legislative bill",
    schema_org_type="Legislation",
    properties=[
        *create_common_properties(),
        PropertyDef("number", PropertyType.STRING, required=True, indexed=True),
        PropertyDef("title", PropertyType.TEXT, fulltext=True),
    ],
    mcp_tools=[
        MCPTool(
            name="get_bill",
            description="Get bill by number",
            cypher_template="MATCH (b:Bill {number: $number}) RETURN b",
            parameters={"number": "string"},
        ),
    ],
)
ontology.register_node_type(bill)

# Generate Neo4j schema
cypher = generate_neo4j_schema(ontology)
```

## Package Structure

```
corpus_core/
├── clients/
│   ├── __init__.py
│   └── base_client.py      # Rate-limited HTTP client
├── extractors/
│   ├── __init__.py
│   └── base_extractor.py   # LLM entity extraction
├── loaders/
│   ├── __init__.py
│   ├── parquet_loader.py   # Parquet file storage
│   ├── neo4j_loader.py     # Neo4j graph loader
│   └── embedding_service.py # Ollama embeddings
├── models/
│   ├── __init__.py
│   ├── document.py         # Document model
│   └── entity.py           # Entity model
└── schema/
    ├── __init__.py
    ├── ontology.py         # Ontology definitions
    └── generators/
        ├── __init__.py
        ├── neo4j_schema.py   # Cypher generator
        └── jsonld_context.py # JSON-LD generator
```
