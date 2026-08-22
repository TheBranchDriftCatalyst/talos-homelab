# The Corpus

Multi-source NER training data pipeline for building named entity recognition models.

> **Status: local development only.** The Corpus is *not* deployed to the homelab
> cluster — there is no Flux Kustomization or ArgoCD Application referencing it, and
> the `corpus-dev` namespace does not exist on `catalyst-cluster`. It runs locally via
> `dagster dev`, or on a local k3s cluster via Tilt. (This is unrelated to the paused
> Dagster deployment in the `catalyst-data` namespace — see `TALOS-vi1`.)

## Overview

The Corpus collects and processes text data from multiple sources for NER model training:

- **Congress.gov** - Legislative data (bills, members, committees)
- **SEC EDGAR** - Financial filings (10-K sections)
- **Reddit** - Discourse data (political, finance, science, general subreddits)

## Architecture

```
the-corpus/
├── Tiltfile.dev        # Local k3s orchestrator (includes pipelines/ + memex/)
│
├── corpus-core/        # Shared Python package
│   └── src/corpus_core/
│       ├── clients/    # API client infrastructure
│       ├── loaders/    # Parquet, Neo4j, embeddings
│       ├── models/     # Document, Entity models
│       ├── extractors/ # NER extraction
│       └── schema/     # Ontology system
│
├── pipelines/          # Dagster ETL pipelines
│   ├── Dockerfile
│   ├── Tiltfile.dev
│   ├── k8s/dev/        # Dagster + Postgres manifests (namespace: corpus-dev)
│   └── src/
│       └── domains/
│           ├── congress/   # Congress.gov ETL
│           ├── edgar/      # SEC EDGAR ETL
│           └── reddit/     # Reddit/Pushshift ETL
│
├── notebooks/          # Exploration & training prep
│   ├── 01-congress-exploration.ipynb
│   ├── 02-edgar-exploration.ipynb
│   ├── 03-reddit-exploration.ipynb
│   └── 04-ner-training-prep.ipynb
│
├── datasets/           # Local Parquet cache (only .gitkeep is committed;
│                       # congress/ edgar/ reddit/ appear at materialization time)
│
├── memex/              # Legacy Congress-only implementation, kept as the
│   │                   # knowledge-graph roadmap (Neo4j + GraphQL + gRPC MCP)
│   ├── k8s/dev/        # neo4j.yaml + memex.yaml
│   └── src/
│       ├── domains/congressional/  # pre-split congress ETL
│       ├── graphql/                # Apollo API over Neo4j
│       ├── mcp/                    # gRPC MCP service + knowledge_graph.proto
│       ├── schema/, shared/        # pre-corpus-core versions of the same code
│       └── the-sorting-hat/        # governance design notes (todo.md only)
│
├── frontends/          # Scaffolding only (todo.md): credIT, common, devproxy
└── devsauce/           # Shared devx tooling; Nix-derived Dockerfiles
```

> The `dagster-congress/` directory named in earlier revisions of this README no
> longer exists. That implementation is what now lives under `memex/` — its README is
> still titled "Dagster Congress ETL Pipeline".

## Quick Start

```bash
# 1. Install packages
cd corpus-core && pip install -e .
cd ../pipelines && pip install -e ".[dev]"

# 2. Set API key (for Congress.gov)
export CONGRESS_API_KEY=your_api_key  # Get from https://api.congress.gov/sign-up/

# 3. Run Dagster
cd pipelines
dagster dev

# 4. Open Dagster UI and materialize assets
open http://localhost:3000

# 5. Explore data in notebooks
jupyter lab ../notebooks/
```

Alternatively, run the stack on a local k3s cluster with Tilt (expects a registry at
`localhost:5000`, overridable via `K3S_REGISTRY`):

```bash
tilt up -f Tiltfile.dev            # pipelines + memex
tilt up -f Tiltfile.dev pipelines  # pipelines only
```

## Data Sources

Scale figures below are design targets. The shipped defaults are much smaller so the
pipeline can be materialized end-to-end without long API runs.

### Congress.gov API
- **Entities**: Bills, Members, Committees
- **Entity Types**: PERSON, ORG, GPE, DATE, LAW
- **Scale (target)**: ~50K documents per Congress
- **Shipped defaults**: `MAX_BILLS=1000`, `MAX_MEMBERS=600`, `MAX_COMMITTEES=300`

### SEC EDGAR
- **Entities**: Companies, Filings, Document Sections
- **Entity Types**: ORG, MONEY, PERCENT, DATE, PRODUCT
- **Scale (target)**: ~500K documents (S&P 500 × 5 years)
- **Shipped defaults**: `SP500_CIKS` in `edgar/client.py` is a 20-ticker MVP subset;
  `MAX_COMPANIES=20`, `MAX_FILINGS_PER_COMPANY=5`, `MAX_FILINGS_TO_PARSE=20`

### Reddit/Pushshift
- **Entities**: Submissions, Comments
- **Entity Types**: PERSON, ORG, GPE (varies by subreddit)
- **Subreddit categories** (`TARGET_SUBREDDITS` in `reddit/loader.py`): political,
  finance, science, general
- **Scale (target)**: ~1M documents
- **Shipped defaults**: `MAX_REDDIT_SUBMISSIONS=10000`, `MAX_REDDIT_COMMENTS=5000`

## Notebooks

1. **Congress Exploration** - Analyze legislative data patterns
2. **EDGAR Exploration** - Extract financial entities from 10-K filings
3. **Reddit Exploration** - Analyze discourse patterns by subreddit category
4. **NER Training Prep** - Combine datasets, create annotations, export formats

## Package Documentation

- [corpus-core README](./corpus-core/README.md) - Shared infrastructure
- [pipelines README](./pipelines/README.md) - Dagster pipelines
- [memex README](./memex/README.md) - Legacy Congress ETL + knowledge-graph roadmap

## Deferred Components

Scaffolded, partially built, or built but not wired into the active pipeline:

- **`memex/src/the-sorting-hat/`** - Governance layer. Design notes only (`todo.md`),
  no code. The rest of `memex/` is implemented but unwired and undeployed.
- **`frontends/`** - Web interfaces. `credIT`, `common`, and `devproxy` exist as
  `todo.md` placeholders with no code. (There is no `wiki` frontend.)
- **`devsauce/`** - Shared devx tooling. Three Dockerfiles, intended to be derived
  from Nix manifests.
- **Neo4j knowledge graph loading** - `Neo4jLoader` *is* implemented in `corpus-core`,
  but no Dagster asset in `pipelines/` calls it, and the `neo4j` resource in
  `pipelines/Tiltfile.dev` is commented out.
- **gRPC/MCP services** - Implemented under `memex/src/mcp/` against
  `proto/knowledge_graph.proto`, but the protobuf stubs are not generated
  (`memex/src/mcp/generated/` holds only a `.gitkeep`) and nothing is deployed.

---

## Related Issues

<!-- Beads tracking for this doc -->

No beads issues currently track The Corpus — it is not cluster-deployed, so it falls
outside the homelab GitOps trackers.

- `TALOS-vi1` — *unrelated*: the paused Dagster deployment in the `catalyst-data`
  namespace. Listed here only to prevent confusion with this project's local Dagster.
