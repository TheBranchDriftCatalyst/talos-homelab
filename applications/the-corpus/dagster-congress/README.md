# Dagster Congress ETL Pipeline

Domain-driven ETL pipeline for Congress.gov data with knowledge graph storage.

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Congress.gov   │───▶│  Dagster ETL    │───▶│     Neo4j       │
│      API        │    │  (K8s Jobs)     │    │ Knowledge Graph │
└─────────────────┘    └─────────────────┘    └────────┬────────┘
                                                       │
                       ┌─────────────────┐    ┌────────▼────────┐
                       │   gRPC MCP      │◀───│   GraphQL API   │
                       │   Service       │    │  (Apollo + WS)  │
                       └─────────────────┘    └─────────────────┘
```

## Components

### ETL Pipeline (Dagster)
- **congress_bills** - Extract bills from Congress.gov
- **congress_members** - Extract members
- **congress_committees** - Extract committees
- **congress_documents** - Transform to LLM documents
- **congress_entities** - Extract entities via Ollama LLM
- **congress_graph** - Load to Neo4j with embeddings

### Knowledge Graph (Neo4j)
- Bills, Members, Committees nodes
- Relationships: SPONSORS, COSPONSORS, SERVES_ON, REFERRED_TO
- Vector embeddings for semantic search
- JSON-LD annotations for MCP tools

### gRPC MCP Interface
- Tool discovery for MCP servers
- Execute Cypher queries via templates
- Semantic search via embeddings

### GraphQL API
- Auto-generated from Neo4j via @neo4j/introspector
- Custom semantic search queries
- WebSocket subscriptions

## Development with Tilt

```bash
# Start local development
cd applications/scratch/dagster-congress
tilt up

# Access services (port-forwarded)
# Dagster UI: http://localhost:3000
# Neo4j Browser: http://localhost:7474
# GraphQL Playground: http://localhost:4000/graphql
# gRPC (reflection): localhost:50051
```

## Deployment

```bash
# Apply all manifests
kubectl apply -k applications/scratch/dagster-congress/

# Or via Flux
flux reconcile kustomization dagster-congress
```

## Service Endpoints

| Service | Internal URL | External URL |
|---------|-------------|--------------|
| Dagster | dagster-dagster-webserver.scratch:80 | dagster.talos00 |
| Neo4j Bolt | neo4j.scratch:7687 | - |
| Neo4j Browser | neo4j.scratch:7474 | neo4j.talos00 |
| GraphQL | knowledge-graph-graphql.scratch:4000 | kg-graphql.talos00 |
| gRPC | knowledge-graph-grpc.scratch:50051 | kg-grpc.talos00 |

## Environment Variables

### Required
- `CONGRESS_API_KEY` - Congress.gov API key

### Optional
- `NEO4J_URI` - Neo4j connection (default: bolt://neo4j.scratch:7687)
- `OLLAMA_URL` - Ollama LLM URL (default: http://ollama-local.catalyst-llm:11434)
- `S3_ENDPOINT_URL` - MinIO URL (default: http://minio.minio:9000)

## Schema Generation (DRY)

Single source of truth in `src/schema/ontology.py`:

```bash
# Generate Neo4j constraints/indexes
python -m schema.generators.neo4j_schema

# Generate gRPC proto
python -m schema.generators.grpc_proto

# Generate JSON-LD context
python -m schema.generators.jsonld_context
```

## MCP Tools

Available via gRPC `DiscoverTools` RPC:

| Tool | Entity | Description |
|------|--------|-------------|
| get_bill | Bill | Get bill by number |
| find_sponsors | Bill | Find bill sponsors |
| bill_history | Bill | Get legislative history |
| related_bills | Bill | Find related bills |
| get_member | Member | Get member by bioguide ID |
| member_bills | Member | Find sponsored bills |
| get_committee | Committee | Get committee details |
| committee_members | Committee | Find committee members |
