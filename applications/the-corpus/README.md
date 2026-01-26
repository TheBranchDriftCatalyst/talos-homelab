# The Corpus

Multi-source NER training data pipeline for building named entity recognition models.

## Overview

The Corpus collects and processes text data from multiple sources for NER model training:

- **Congress.gov** - Legislative data (bills, members, committees)
- **SEC EDGAR** - Financial filings (10-K sections)
- **Reddit** - Discourse data (political, finance, science subreddits)

## Architecture

```
the-corpus/
├── corpus-core/        # Shared Python package
│   └── src/corpus_core/
│       ├── clients/    # API client infrastructure
│       ├── loaders/    # Parquet, Neo4j, embeddings
│       ├── models/     # Document, Entity models
│       ├── extractors/ # NER extraction
│       └── schema/     # Ontology system
│
├── pipelines/          # Dagster ETL pipelines
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
├── datasets/           # Local Parquet cache
│   ├── congress/
│   ├── edgar/
│   └── reddit/
│
└── (legacy)
    ├── dagster-congress/   # Previous implementation
    └── memex/              # Future governance layer
```

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

## Data Sources

### Congress.gov API
- **Entities**: Bills, Members, Committees
- **Entity Types**: PERSON, ORG, GPE, DATE, LAW
- **Scale**: ~50K documents per Congress

### SEC EDGAR
- **Entities**: Companies, Filings, Document Sections
- **Entity Types**: ORG, MONEY, PERCENT, DATE, PRODUCT
- **Scale**: ~500K documents (S&P 500 × 5 years)

### Reddit/Pushshift
- **Entities**: Submissions, Comments
- **Entity Types**: PERSON, ORG, GPE (varies by subreddit)
- **Scale**: ~1M documents

## Notebooks

1. **Congress Exploration** - Analyze legislative data patterns
2. **EDGAR Exploration** - Extract financial entities from 10-K filings
3. **Reddit Exploration** - Analyze discourse patterns by subreddit category
4. **NER Training Prep** - Combine datasets, create annotations, export formats

## Package Documentation

- [corpus-core README](./corpus-core/README.md) - Shared infrastructure
- [pipelines README](./pipelines/README.md) - Dagster pipelines

## Deferred Components

The following are scaffolded but not yet implemented:

- **memex/** - Governance layer (The Sorting Hat)
- **frontends/** - Web interfaces (credIT, wiki)
- Neo4j knowledge graph loading
- gRPC/MCP services
