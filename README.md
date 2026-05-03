# FundTrace

> AI-powered ghost capacity detection for Canadian public funding

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://python.org)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.30+-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io)
[![Claude AI](https://img.shields.io/badge/Claude_AI-Anthropic-6B4EFF)](https://anthropic.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-14+-336791?logo=postgresql&logoColor=white)](https://postgresql.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Hackathon](https://img.shields.io/badge/Agency_2026-AI_For_Accountability-orange)](https://github.com/Rick0803/Agency-2026-Hackathon-FundTrace)

---

Canada distributes tens of billions in annual grants and contributions to hundreds of thousands of organizations. Detecting **ghost capacity** — recipients that continue receiving public money while showing weak signs of operational activity, delivery, or financial health — requires cross-referencing filing histories, spending patterns, employee counts, and revenue sources across multiple disconnected government datasets. That's exactly what FundTrace automates.

Built at the **Agency 2026 AI For Accountability Hackathon** (April 29, 2026).

---

## Demo

[![FundTrace Demo](https://img.youtube.com/vi/XFqNo-ySUmI/maxresdefault.jpg)](https://www.youtube.com/watch?v=XFqNo-ySUmI)

*Click the thumbnail above to watch a full walkthrough of the project.*

---

## The Investigation Workflow

```
┌─────────────────────┐    ┌──────────────────┐    ┌─────────────────┐    ┌──────────────────┐
│  1. Search Orgs     │───▶│  2. Shortlist     │───▶│  3. Analyze     │───▶│  4. Report       │
│                     │    │                  │    │                 │    │                  │
│  User-Defined Rules │    │  Include/exclude  │    │  Ghost scoring  │    │  Dashboard       │
│  Anomaly Detection  │    │  Curate & review  │    │  Risk labels    │    │  Business Report │
│  AI scan summary    │    │  Elevate to step 3│    │  AI narrative   │    │  PDF export      │
└─────────────────────┘    └──────────────────┘    └─────────────────┘    └──────────────────┘
```

---

## Key Features

### 🔍 Dual Discovery Methods

| Method | Approach |
|--------|----------|
| **User-Defined Rules** | 10 configurable heuristic rules with adjustable thresholds — went dark after grants, stopped filing within 12 months, zero employees, funding gap, revenue cliff, and more |
| **Anomaly Detection (AI)** | Peer-relative unsupervised ML (ECOD, Isolation Forest, LOF) scores each entity against organizations in the same funding band and entity type — surfaces patterns rules miss |

### 📊 Ghost Capacity Scoring

Five-dimension composite score (0–1) per entity:

| Dimension | Weight |
|-----------|--------|
| Program delivery deficit | 30% |
| Government revenue dependency | 25% |
| Compensation burden | 20% |
| Pass-through transfers | 15% |
| Zero reported employees | 10% |

Every score comes with a risk label (CRITICAL / HIGH / MEDIUM / LOW), a confidence rating, signal-level evidence, and interpretations grounded in the actual data.

### 🤖 Claude-Powered Narratives

LLM integration at every reporting stage:

- **Scan summary** — executive briefing on scan coverage and top findings
- **Analysis narrative** — 200-word executive paragraph for decision-makers
- **Entity narrative brief** — 3–4 paragraph dossier on the highest-risk findings
- **Business Report** — full structured briefing note with situation overview, key findings, risk assessment, and recommendations

### 📄 Audit-Ready Exports

- Per-entity JSON and CSV
- Aggregate signal CSVs
- Full business report in JSON and **PDF** (formatted, paginated, ready to file)

---

## Data Scale

| Dataset | Rows | Coverage |
|---------|------|----------|
| CRA T3010 Charity Filings | ~8.76M | 2020–2024, ~85K registered charities |
| Federal Grants & Contributions | ~1.275M | 51+ departments, 422K+ recipients |
| Alberta Open Data (grants, contracts, sole-source, non-profits) | ~2.61M | 2014–2026 |
| **Unified golden records** | **~851K canonical organizations** | Cross-dataset entity resolution |

### Entity Resolution Pipeline

The same organization can appear under dozens of name variants across three datasets with multiple Business Number suffix variants. FundTrace reconciles them into one canonical golden record per real-world organization using:

1. **Deterministic matching** — BN anchoring + exact/normalized name + trade-name extraction
2. **Probabilistic record linkage** via [Splink](https://moj-analytical-services.github.io/splink/) (UK MoJ's Fellegi-Sunter implementation)
3. **LLM-confirmed merges** — Claude decides SAME / RELATED / DIFFERENT per candidate pair and authors the canonical golden record

Result: **~851K golden records**, ~5.2M source links, ~67K LLM-confirmed merges.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| UI Framework | Streamlit |
| AI / LLM | Claude API (Anthropic SDK) |
| Anomaly Detection | PyOD — ECOD, Isolation Forest, LOF |
| Entity Resolution | Splink (probabilistic record linkage) |
| Database | PostgreSQL 14+ with `pg_trgm` |
| Data Processing | pandas, NumPy, SciPy |
| Visualization | Altair |
| PDF Generation | fpdf2 |
| Data Pipelines | Node.js (per-dataset ETL modules) |

---

## Repository Structure

```
FundTrace/
├── Proto/                      # Streamlit application — main deliverable
│   ├── app.py                  # Entry point + page routing
│   ├── agent/
│   │   ├── llm_client.py       # Claude API integration
│   │   └── orchestrator.py     # Agentic coordination layer
│   ├── tools/
│   │   ├── retrieval.py        # Cross-dataset SQL + query builder
│   │   ├── analytics.py        # Ghost-capacity scoring + anomaly detection
│   │   └── preload.py          # Startup cache warming
│   ├── views/
│   │   ├── general.py          # Home page
│   │   ├── fetch.py            # Step 1 — Search Organizations
│   │   ├── analyze.py          # Step 3 — Run Analysis
│   │   └── report.py           # Step 4 — View Report
│   ├── models/schemas.py       # Shared data contracts
│   └── requirements.txt
│
├── CRA/                        # CRA T3010 ETL + 18 analysis scripts
├── FED/                        # Federal grants ETL + 10 analysis scripts
├── AB/                         # Alberta open data ETL + 6 analysis scripts
├── general/                    # Cross-dataset entity resolution pipeline
│   └── splink/                 # Python probabilistic record linkage stage
├── .local-db/                  # Local database recreation kit (DDL + import/export)
├── ATTRIBUTIONS.md             # Data source citations + third-party credits
└── LICENSE                     # MIT (source code only — data follows original licences)
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 14+ with `pg_trgm` extension enabled
- An Anthropic API key (optional — app runs deterministically without one)

### Setup

```bash
git clone https://github.com/Rick0803/Agency-2026-Hackathon-FundTrace.git
cd Agency-2026-Hackathon-FundTrace/Proto

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# Set DB_CONNECTION_STRING and optionally ANTHROPIC_API_KEY in .env
```

### Run

```bash
streamlit run app.py
# → http://localhost:8501
```

See [Proto/README.md](Proto/README.md) for full setup details, environment variables, and deployment options.

---

## License

Source code: **MIT** — see [LICENSE](LICENSE).

Data: redistributed under the original open-government licences — [Open Government Licence – Canada](https://open.canada.ca/en/open-government-licence-canada) (CRA and federal data) and [Open Government Licence – Alberta](https://open.alberta.ca/licence) (Alberta data). The MIT licence covers source code only and does not relicense the underlying datasets. See [ATTRIBUTIONS.md](ATTRIBUTIONS.md) for full source attribution and third-party library credits.
