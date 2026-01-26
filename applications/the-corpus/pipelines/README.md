# corpus-pipelines

Dagster ETL pipelines for NER training data collection.

## Installation

```bash
# Install corpus-core first
cd ../corpus-core
pip install -e .

# Install pipelines
cd ../pipelines
pip install -e ".[dev]"
```

## Running the Pipelines

```bash
# Start Dagster dev server
cd pipelines
dagster dev

# Open http://localhost:3000
```

## Domains

### Congress

Extract data from Congress.gov API.

**Environment Variables:**
- `CONGRESS_API_KEY` - Required. Get from https://api.congress.gov/sign-up/
- `CONGRESS_NUMBER` - Congress number (default: 118)
- `MAX_BILLS` - Max bills to extract (default: 1000)
- `MAX_MEMBERS` - Max members to extract (default: 600)

**Assets:**
- `congress_bills` - Extract bills from Congress.gov
- `congress_members` - Extract members of Congress
- `congress_committees` - Extract committees
- `congress_documents` - Transform to training documents

### EDGAR

Extract data from SEC EDGAR (no API key required).

**Environment Variables:**
- `MAX_COMPANIES` - Max companies (default: 20)
- `MAX_FILINGS_PER_COMPANY` - 10-K filings per company (default: 5)
- `MAX_FILINGS_TO_PARSE` - Filings to parse sections (default: 20)

**Assets:**
- `edgar_companies` - Extract S&P 500 company info
- `edgar_filings` - Extract 10-K filings
- `edgar_sections` - Parse filing sections (Item 1, 1A, 7, etc.)
- `edgar_documents` - Transform to training documents

### Reddit

Extract data from Pushshift archives via HuggingFace.

**Environment Variables:**
- `MAX_REDDIT_SUBMISSIONS` - Max submissions (default: 10000)
- `MAX_REDDIT_COMMENTS` - Max comments (default: 5000)

**Assets:**
- `reddit_submissions` - Extract Reddit posts
- `reddit_comments` - Extract comments
- `reddit_documents` - Transform to training documents

## Project Structure

```
pipelines/
├── src/
│   ├── definitions.py      # Dagster entry point
│   ├── resources/          # Shared resources
│   │   └── __init__.py     # ParquetIOManager
│   └── domains/
│       ├── congress/       # Congress.gov domain
│       │   ├── client.py
│       │   ├── entities.py
│       │   └── assets.py
│       ├── edgar/          # SEC EDGAR domain
│       │   ├── client.py
│       │   ├── entities.py
│       │   └── assets.py
│       └── reddit/         # Reddit domain
│           ├── loader.py
│           ├── entities.py
│           └── assets.py
├── pyproject.toml
└── README.md
```

## Output

Data is stored in `../datasets/` as Parquet files:

```
datasets/
├── congress/
│   ├── congress_bills.parquet
│   ├── congress_members.parquet
│   ├── congress_committees.parquet
│   └── congress_documents.parquet
├── edgar/
│   ├── edgar_companies.parquet
│   ├── edgar_filings.parquet
│   ├── edgar_sections.parquet
│   └── edgar_documents.parquet
└── reddit/
    ├── reddit_submissions.parquet
    ├── reddit_comments.parquet
    └── reddit_documents.parquet
```
