# FundTrace — App Setup Guide

FundTrace is a Streamlit application for detecting ghost capacity in Canadian public-funding recipients. See the [root README](../README.md) for the full project overview.

## Prerequisites

- Python 3.11+
- PostgreSQL 14+ with `pg_trgm` extension enabled (populated with CRA/FED data)
- Anthropic API key — optional; the app runs fully deterministically without one

## Installation

```bash
cd Proto

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

## Configuration

Copy the example and fill in your values:

```bash
cp .env.example .env
```

Required:

```env
DB_CONNECTION_STRING=postgresql://user:password@host:5432/dbname
```

Optional (enables Claude-powered narrative generation):

```env
ANTHROPIC_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-haiku-4-5-20251001
```

## Running the App

```bash
streamlit run app.py
# → http://localhost:8501
```

## Project Structure

```
Proto/
├── app.py                  # Entry point + page routing
├── config.py               # Environment and config loading
├── requirements.txt
│
├── agent/
│   ├── llm_client.py       # Claude API integration
│   └── orchestrator.py     # Coordination layer (entity analysis, report generation)
│
├── models/
│   └── schemas.py          # Shared dataclasses and data contracts
│
├── tools/
│   ├── retrieval.py        # Cross-dataset SQL queries and data fetching
│   ├── analytics.py        # Ghost-capacity scoring and anomaly detection
│   └── preload.py          # Startup cache warming
│
├── views/
│   ├── general.py          # Home page
│   ├── fetch.py            # Step 1 — Search Organizations
│   ├── analyze.py          # Step 3 — Run Analysis
│   └── report.py           # Step 4 — View Report
│
└── assets/
    └── workflow-illustration.png
```

## Workflow

The app gates each step in sequence:

1. **Search Organizations** — run a rule-based scan or AI anomaly detection to discover suspicious entities and add them to the shortlist
2. **Review Shortlist** — include or exclude entities before analysis; elevate the selection to step 3
3. **Run Analysis** — deterministic ghost-capacity scoring with LLM executive narrative
4. **View Report** — entity dashboard or aggregate view; generate a full business report with PDF export

Page 2 unlocks when at least one entity is added to the shortlist. Page 3 unlocks when entities are elevated from page 2. **Start Over** resets workflow state while preserving warmed scan caches.

## Performance

The app warms several expensive data paths on startup (fetch-scan preload, portfolio baseline). Initial load is slow by design — subsequent actions are significantly faster.

## Deployment

A `Dockerfile` and `apprunner.yaml` are included for containerised deployment (e.g. AWS App Runner). Set the same environment variables as above in your deployment environment.
