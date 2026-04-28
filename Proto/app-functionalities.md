# App Functionalities — Team Onboarding

## What this app does

A Streamlit prototype for investigating **ghost capacity** in Canadian public funding data. Ghost capacity = an organization that receives ongoing government funding but shows no evidence of being able to deliver what it was funded to do.

It combines two datasets:
- **CRA T3010** — annual charity filings (revenue, expenses, employees, transfers to other charities)
- **FED grants** — federal grants and contributions database (who received what, from which department, over how many years)

The app lets a user go from "find suspicious organizations" → "flag them" → "analyze them" → "generate a report" — all in one workflow.

---

## How to run

```bash
cd Proto/
pip install -r requirements.txt
streamlit run app.py
```

Requires a `.env` file in `Proto/` with:
```
DB_CONNECTION_STRING=...
ANTHROPIC_API_KEY=...
```

---

## Project structure

```
Proto/
├── app.py                  # Entry point — routing only
├── views/
│   ├── general.py          # Shared helpers, session state, Home page, Open Search
│   ├── fetch.py            # Fetch page (Ways 1–4) + Flagged entities page
│   ├── analyze.py          # Analysis page (Batch + Portfolio)
│   └── report.py           # Report page (LLM narrative)
├── agent/
│   └── orchestrator.py     # All run_*() functions — bridges views ↔ tools
├── tools/
│   ├── retrieval.py        # All database queries — returns DataFrames
│   └── analytics.py        # All computation — pure functions, no DB access
├── models/
│   └── schemas.py          # Dataclasses shared across all layers
├── requirements.txt
├── rules.md                # All 10 Way 1 zombie rules documented
├── reporting-objectives.md # Reporting roadmap (Phase 1 non-LLM, Phase 2 LLM)
└── app-functionalities.md  # This file
```

### Layer responsibilities

| Layer | Files | Rule |
|---|---|---|
| Views | `views/*.py` | UI only — reads session state, calls orchestrator, renders results |
| Orchestrator | `agent/orchestrator.py` | Coordination only — calls retrieval + analytics, returns clean objects |
| Retrieval | `tools/retrieval.py` | DB only — one function = one SQL query, returns DataFrame |
| Analytics | `tools/analytics.py` | Computation only — takes DataFrames, returns dataclasses, no DB |
| Schemas | `models/schemas.py` | Data contracts — shared dataclasses used across all layers |

---

## Pages

### Home
Overview of what the app does. Links to Fetch, Analyze, and Report.

### Fetch
The main discovery layer. Four tabs:

**Way 1 — Rule-Based Zombie Scan**
Runs a single SQL query across all FED recipients and flags any that trigger at least one of 10 hardcoded rules. All thresholds are tunable in the UI before running.

| Rule | Signal |
|---|---|
| R1 | Last CRA filing before cutoff year (org went dark) |
| R2 | Stopped filing within N months of last grant |
| R3 | Average government revenue share ≥ threshold |
| R4 | No CRA record at all despite receiving FED grants |
| R5 | Zero private revenue ever |
| R6 | Zero program spend ever |
| R7 | Total compensation exceeds total program spend |
| R8 | Federal grants exceed CRA program spend (funding gap) |
| R9 | First grant arrived within N years of first CRA filing |
| R10 | Revenue in final year dropped below threshold % of prior average |

Results show a histogram, rule breakdown table, and a full entity table with checkboxes. Checked entities can be added to the Flagged List.

**Way 2 — Peer-Relative Anomaly Detection**
ML-based scoring across the full entity universe. No rules — finds statistical outliers.
- Builds a feature table of 13 ML features per entity (ratios, log-scale financials, time features, Way 1 flag count as domain knowledge)
- Scores within peer groups (entity type + funding band) using ECOD, Isolation Forest, or LOF
- Groups smaller than 15 fall back to global scoring
- Adds rule-based explanations to each anomaly
- Results table is sortable; checked entities can be added to the Flagged List

**Way 3 — Open Search**
Natural language search over CRA+FED aggregate metrics. LLM interprets the request into an allowlisted query spec; SQL is generated deterministically. Uses one LLM call.

**Way 4 — Raw Data Lookup**
Pick any organization from the entity registry and pull its raw CRA + FED records directly. No scoring — just the source data in five sub-tabs (Federal Grants, Revenue Sources, Expense Profile, Employees, Transfers Out).

### Flagged
Persistent list of organizations the user selected from Way 1 or Way 2. Survives page navigation via `st.session_state["flagged_list"]`.
- Remove individual entries or clear all
- Select one entity to open directly in Analyze or Report

### Analyze
Two tabs — both fully deterministic, no LLM.

**Batch Analysis**
Runs the full ghost capacity pipeline for every entity in the Flagged List.
For each entity: fetches 5 data sources (revenue, expenses, employees, transfers, grants), computes ghost score using the weighted composite scorer, returns an `EntityAnalysisResult`.

Results are ranked by ghost score. Each entity shows:
- Overall risk label (CRITICAL / HIGH / MEDIUM / LOW), ghost score, confidence
- Signal-by-signal breakdown with values vs. thresholds
- Temporal info (first grant, last grant, last CRA filing)
- "Open in Report" to pass the entity directly to the Report page

**Portfolio Dashboard**
Scans the full funded universe without any flagging step.
- Aggregates risk by province, entity type, and funding band
- Shows department-level risk rates (which departments fund the most risky organizations)
- Top 25 highest-risk entities ranked by rules triggered
- "Open in Report" from any entry in the top entities list

### Report
LLM-powered narrative investigation. The LLM follows a fixed investigation sequence (14 steps), calling tools to fetch and compute data, then writes a structured risk brief.

Output includes: overall risk label, confidence, 3–4 sentence narrative summary, per-signal evidence, recommended actions, and limitations. Downloadable as JSON.

The selected entity from Analyze or Flagged is pre-filled into the query box.

---

## Key data concepts

**Ghost score (0–1)**
Weighted composite of five dimensions:
| Dimension | Weight | Flag threshold |
|---|---|---|
| Government revenue dependency | 0.25 | > 90% |
| Program delivery deficit | 0.30 | < 20% of expenses |
| High compensation burden | 0.20 | > 50% of expenses |
| Pass-through transfer pattern | 0.15 | > 40% of expenses |
| No reported employees | 0.10 | 0 employees |

Interpretation: 0.0–0.3 low, 0.3–0.6 medium, 0.6–0.8 high, 0.8–1.0 critical.

**EntityAnalysisResult**
The shared data contract between Analysis and Reporting (defined in `models/schemas.py`). Contains identity, risk scores, signals, financials, and temporal fields. Every report format — UI card, PDF, LLM brief — consumes this object. Analysis produces it; reporting renders it.

**Funding gap**
`fed_total − cra_program_spend_total`. An org that received $1M in grants but reported $50K in program spend has a $950K gap — money unaccounted for.

**Peer grouping (Way 2)**
Entities are scored against peers in the same entity type + funding band bucket (e.g. "Charity / $100K–$1M"). Groups with fewer than 15 members fall back to global scoring. This prevents large, well-resourced organizations from making small ones look normal.

---

## Session state keys

| Key | Set by | Used by |
|---|---|---|
| `page` | `general.go_to_page()` | `app.py` router |
| `selected_entity` | `general.set_selected_entity()` | Analyze, Report banners |
| `flagged_list` | Fetch Way 1 / Way 2 add buttons | Flagged page, Analyze batch tab |
| `zombie_df` | Way 1 scan button | Way 1 results (persists across checkbox clicks) |
| `way2_df` | Way 2 scan button | Way 2 results |
| `batch_analysis_results` | Analyze batch run button | Analyze batch tab |
| `portfolio_results` | Analyze portfolio run button | Analyze portfolio tab |

---

## What is not built yet

See `reporting-objectives.md` for the full roadmap. Short version:
- PDF export of entity risk cards
- CSV/JSON export of portfolio results
- LLM narrative brief from pre-computed `EntityAnalysisResult` (cheaper than current Report flow)
- RAG over government audit reports
- Alerts / early warning monitoring list
