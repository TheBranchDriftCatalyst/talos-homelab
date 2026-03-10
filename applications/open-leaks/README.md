# open-leaks — Dagster Code Location

Dagster pipeline for ingesting publicly available leaked and declassified documents for LLM-powered entity extraction, embedding, clustering, and knowledge graph construction.

## Data Sources

| Source | Description | Records | Format | Download |
|--------|-------------|---------|--------|----------|
| [ICIJ Offshore Leaks Database](https://offshoreleaks.icij.org/) | Panama Papers, Paradise Papers, Pandora Papers, Bahamas Leaks, Offshore Leaks | **2,016,523** entities, **3,339,267** relationships | CSV bulk ZIP (~70 MB) | [full-oldb.LATEST.zip](https://offshoreleaks-data.icij.org/offshoreleaks/csv/full-oldb.LATEST.zip) |
| [WikiLeaks Cablegate](https://wikileaks.org/plusd/) | 251K US diplomatic cables (1966–2010), all classification levels | **251,287** cables | CSV (~1.65 GB) | [cables.csv](https://archive.org/download/wikileaks-cables-csv/cables.csv) (Internet Archive) |
| [Epstein Investigation](https://www.epsteininvestigation.org/) | DOJ FOIA releases — FBI 302s, depositions, court filings across 12 datasets | **39,769** documents | REST API (JSON) | [/api/v1/documents](https://www.epsteininvestigation.org/api/v1/documents?page=1&limit=100) |

### Additional References

| Resource | Description |
|----------|-------------|
| [ICIJ Data Packages (GitHub)](https://github.com/ICIJ/offshoreleaks-data-packages) | Official ICIJ data packaging and schema docs |
| [ICIJ Neo4j Dumps](https://offshoreleaks-data.icij.org/offshoreleaks/neo4j/) | Pre-built Neo4j graph database dumps (v4 and v5) |
| [Cablegate on Internet Archive](https://archive.org/details/wikileaks-cables-csv) | Mirror of the full Cablegate CSV with 7z compressed option (351 MB) |
| [anarchivist/cablegate (GitHub)](https://github.com/anarchivist/cablegate) | Python parser for cables.csv → MongoDB/JSON |
| [DOJ Epstein Library](https://www.justice.gov/epstein) | Original DOJ release page (12 dataset ZIPs, ~600 GB total PDFs) |
| [Epstein Files (GitHub)](https://github.com/yung-megafone/Epstein-Files) | Community mirror tracking, hash verification, torrent magnets |
| [Epstein Research Data (GitHub)](https://github.com/rhowardstone/Epstein-research-data) | Structured knowledge graph, entity registry, SQLite full-text corpus |
| [Epstein Docs on Internet Archive](https://archive.org/details/epsteindocs) | 4.6 GB curated collection — flight logs, black book, depositions |

## Pipeline Architecture

```
BRONZE                          SILVER                      GOLD
─────                          ──────                      ────
wikileaks_cables ─────────┐
icij_offshore_entities ───┼──→ leak_documents ──┬──→ leak_embeddings
epstein_court_docs ───────┘         │           └──→ leak_propositions
                                    ↓
                              leak_entities ──────→ leak_graph
                                                      ↑
icij_offshore_relationships ──────────────────────────┘
```

- **Bronze**: Download and parse raw data from each source
- **Silver**: Normalize to unified `Document` model, extract named entities via LLM
- **Gold**: Generate vector embeddings, extract S-P-O propositions, build knowledge graph

## Quick Start

```bash
# Install locally
cd applications/open-leaks
pip install -e .

# Verify definitions load (9 assets)
python -c "from open_leaks import defs; print(len(defs.resolve_all_asset_specs()), 'assets')"

# Validate K8s manifests
kubectl apply -k k8s/ --dry-run=client
```

## Configuration

| Env Var | Default | Description |
|---------|---------|-------------|
| `OPEN_LEAKS_CACHE_DIR` | `/tmp/open-leaks-cache` | Local cache for downloaded archives |
| `ICIJ_BULK_URL` | ICIJ data server | Override ICIJ CSV download URL |
| `CABLEGATE_CSV_URL` | Internet Archive | Override cables.csv download URL |
| `EPSTEIN_API_URL` | epsteininvestigation.org | Override Epstein API base URL |
| `MAX_CABLES` | `0` (unlimited) | Limit cable extraction count |
| `MAX_ICIJ_ENTITIES` | `0` (unlimited) | Limit ICIJ entity extraction count |
| `MAX_ICIJ_RELATIONSHIPS` | `0` (unlimited) | Limit ICIJ relationship extraction count |
| `MAX_EPSTEIN_DOCS` | `0` (unlimited) | Limit Epstein document fetch count |
| `LLM_PROVIDER` | `openai` | LLM backend: `openai` or `ollama` |
| `LLM_MODEL` | `gpt-4o-mini` | Model name for NER/proposition extraction |
| `OPENAI_API_KEY` | — | OpenAI API key (or Ollama placeholder) |
| `OLLAMA_URL` | — | Ollama base URL (e.g. `http://ollama:11434/v1`) |
| `EMBEDDING_PROVIDER` | `sentence-transformers` | Embedding backend: `sentence-transformers` or `openai` |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Embedding model name |
