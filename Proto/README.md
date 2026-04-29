# FundTrace

FundTrace is a Streamlit prototype for finding, analyzing, and reporting suspicious public-funding recipients in Canada.

The app links:

- CRA T3010 charity filings
- federal grants and contributions data

Its main use case is surfacing "zombie recipients": organizations that continue receiving public funding while showing weak signs of operational capacity, delivery activity, or financial consistency.

## What the app does

FundTrace follows a linear investigation workflow:

1. Search organizations
2. Review shortlist
3. Run analysis
4. View report

The app supports two discovery methods on the search page:

- `User-Defined Rules`: a configurable heuristic scan using 10 zombie-recipient rules
- `Anomaly Detection (AI)`: peer-relative anomaly scoring using ECOD, Isolation Forest, or LOF

From there, users can shortlist entities, run deterministic entity analysis, and generate dashboard/report views for individual or aggregate review.

## Main functionalities

### 1. Search Organizations

The Fetch page is the discovery layer.

#### User-Defined Rules

Runs a rule-based scan over matched CRA + FED entities and flags organizations that trigger one or more zombie-recipient signals, including:

- went dark after grants
- stopped filing soon after funding
- high government dependency
- no CRA record
- zero private revenue
- zero program spend
- compensation greater than program spend
- funding gap
- early grant with little track record
- revenue cliff

The page includes:

- adjustable rule thresholds
- coverage metrics
- rule breakdowns
- charts
- a results table with shortlist selection
- an LLM-ready placeholder scan summary block

#### Anomaly Detection (AI)

Builds an entity-level feature table and scores organizations against comparable peers using:

- Empirical CDF Outlier Detection (ECOD)
- Isolation Forest
- Local Outlier Factor (LOF)

The page includes:

- model and peer-group configuration
- score distribution charts
- top-anomaly review table
- shortlist selection
- an LLM-ready placeholder scan summary block

### 2. Review Shortlist

The shortlist page lets users:

- review all entities added from either discovery method
- include or exclude entities for analysis
- clear the shortlist
- elevate the selected entities into the Analyze step

### 3. Run Analysis

The Analyze page runs deterministic entity scoring across the selected shortlist.

For each entity, FundTrace computes:

- ghost score
- overall risk label
- confidence
- signal-level evidence
- core financial and temporal indicators

The page also shows:

- ranked shortlist results
- top-risk highlights
- portfolio context
- an LLM-ready placeholder analysis summary

### 4. View Report

The Report page supports both entity-level and aggregate reporting.

#### Dashboard

For a selected entity, the dashboard shows:

- KPIs
- charts
- key ideas
- signal details
- exports
- an LLM-ready placeholder Narrative Brief

For aggregate scope, it shows:

- whole-set KPIs
- risk distribution
- top-risk entities
- aggregate exposure
- common triggered signals
- aggregate signal details
- exports

#### Business Report

This is the macro reporting view across the analyzed set. It combines deterministic findings with placeholder scaffolding for future LLM-written sections such as:

- executive summary
- recommended actions

## LLM-ready areas

The current app is mostly deterministic, but it already includes placeholder hooks for future LLM usage:

- Fetch-page scan summary advisor
- Analyze summary
- Narrative Brief on the entity dashboard
- Business Report macro summary

These placeholders currently use deterministic fallback text, but the prompt-building structure is already in place so real model calls can be added later without changing the UI flow.

## Project structure

```text
Proto/
├── app.py
├── agent/
│   ├── __init__.py
│   └── orchestrator.py
├── assets/
├── models/
│   └── schemas.py
├── tools/
│   ├── analytics.py
│   ├── preload.py
│   └── retrieval.py
├── views/
│   ├── analyze.py
│   ├── fetch.py
│   ├── general.py
│   └── report.py
├── requirements.txt
└── README.md
```

### Layer responsibilities

- `views/`: Streamlit UI and workflow rendering
- `agent/orchestrator.py`: coordination layer between UI, retrieval, and analytics
- `tools/retrieval.py`: database access and SQL
- `tools/analytics.py`: deterministic scoring and feature computation
- `models/schemas.py`: shared data contracts

## Installation

### Prerequisites

- Python 3.11+ recommended
- access to the backing PostgreSQL database used by the CRA/FED queries

### 1. Create and activate a virtual environment

```bash
cd agency-26-hackathon/Proto
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Create `Proto/.env`

At minimum:

```env
DB_CONNECTION_STRING=postgresql://...
```

Optional, only needed when enabling the real Anthropic-powered flows:

```env
ANTHROPIC_API_KEY=...
CLAUDE_MODEL=claude-haiku-4-5-20251001
```

## Running the app

From the `Proto/` directory:

```bash
streamlit run app.py
```

Streamlit will print a local URL, usually:

```text
http://localhost:8501
```

## Performance notes

FundTrace intentionally warms some expensive data paths on startup to improve demo-time responsiveness.

Current behavior includes:

- fetch-scan preload on app start
- portfolio baseline warmup
- reuse of cached/shared feature-table work where possible
- workflow reset that preserves warmed scan data

Because of that, the app may feel slow during initial startup, but later actions should be noticeably faster.

## Important session behavior

- The workflow is intentionally gated.
- Page 2 unlocks when at least one entity is added to the shortlist.
- Page 3 unlocks when shortlisted entities are elevated from page 2.
- `Start Over` resets the workflow state but preserves warmed scan results and caches where possible.

## Troubleshooting

### `DB_CONNECTION_STRING not set`

Make sure `Proto/.env` exists and includes:

```env
DB_CONNECTION_STRING=...
```

### App starts slowly

This is expected to some degree because preload runs on startup. The app is warming fetch and analysis-related state for later steps.

### Buttons feel inconsistent after state-heavy actions

The app uses Streamlit reruns and session state heavily. If the UI looks stale after a large workflow action, refreshing the page usually clears the visual mismatch.

## Notes for future development

- The app currently prioritizes deterministic scoring with LLM-ready reporting hooks.
- The Natural Language Search / Open Search flow exists conceptually but is not part of the active workflow right now.
- Narrative and macro-report writing can be upgraded later by replacing the placeholder summary functions with real model calls.

## Related docs

- [app-functionalities.md](./app-functionalities.md)
- [reporting-objectives.md](./reporting-objectives.md)
- [reports-optimize.md](./reports-optimize.md)
- [rules.md](./rules.md)
