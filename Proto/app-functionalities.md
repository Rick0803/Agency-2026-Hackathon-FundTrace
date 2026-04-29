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

# AWS Bedrock (recommended)
USE_BEDROCK=true
AWS_DEFAULT_REGION=us-west-2
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_SESSION_TOKEN=...
BEDROCK_MODEL=anthropic.claude-opus-4-5-20251101-v1:0

# OR Anthropic API (alternative)
ANTHROPIC_API_KEY=...
CLAUDE_MODEL=claude-sonnet-4-6
```

**Note:** The app now uses AWS Bedrock by default for all LLM features. All LLM features include graceful fallback to deterministic output if credentials are unavailable.

---

## Project structure

```
Proto/
├── app.py                  # Entry point — routing only (optimized for fast startup)
├── views/
│   ├── general.py          # Shared helpers, session state, Home page, Open Search
│   ├── fetch.py            # Fetch page (Ways 1–4) + Flagged entities page
│   ├── analyze.py          # Analysis page (Batch + Portfolio)
│   └── report.py           # Report page (Entity + Aggregate + Business Report)
├── agent/
│   ├── llm_client.py       # Unified LLM client (Bedrock + Anthropic API)
│   └── orchestrator.py     # All run_*() functions — bridges views ↔ tools
├── tools/
│   ├── retrieval.py        # All database queries — returns DataFrames
│   ├── analytics.py        # All computation — pure functions, no DB access
│   └── preload.py          # Background preloading for Fetch page
├── models/
│   └── schemas.py          # Dataclasses shared across all layers
├── requirements.txt
├── rules.md                # All 10 Way 1 zombie rules documented
├── reporting-objectives.md # Reporting roadmap (Phase 1 non-LLM, Phase 2 LLM)
├── app-functionalities.md  # This file
└── FINAL_SUMMARY.md        # Complete overview of all enhancements
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

**✨ NEW: AI Executive Summary** - LLM-generated 3-4 sentence summary appears at the top of results, suitable for deputy ministers and senior officials. Covers severity, key findings, systemic patterns, and recommended actions.

**Way 2 — Peer-Relative Anomaly Detection**
ML-based scoring across the full entity universe. No rules — finds statistical outliers.
- Builds a feature table of 13 ML features per entity (ratios, log-scale financials, time features, Way 1 flag count as domain knowledge)
- Scores within peer groups (entity type + funding band) using ECOD, Isolation Forest, or LOF
- Groups smaller than 15 fall back to global scoring
- Adds rule-based explanations to each anomaly
- Results table is sortable; checked entities can be added to the Flagged List

**✨ NEW: AI Executive Summary** - LLM-generated 3-4 sentence summary appears at the top of results, providing executive-level context on anomaly patterns and risk distribution.

**Way 3 — Open Search**
Natural language search over CRA+FED aggregate metrics. LLM interprets the request into an allowlisted query spec; SQL is generated deterministically. Uses one LLM call.

**Way 4 — Raw Data Lookup**
Pick any organization from the entity registry and pull its raw CRA + FED records directly. No scoring — just the source data in five sub-tabs (Federal Grants, Revenue Sources, Expense Profile, Employees, Transfers Out).

### Flagged
Persistent list of organizations the user selected from Way 1 or Way 2. Survives page navigation via `st.session_state["flagged_list"]`.
- Remove individual entries or clear all
- Select one entity to open directly in Analyze or Report

### Analyze
Two tabs with enhanced executive summaries.

**Batch Analysis**
Runs the full ghost capacity pipeline for every entity in the Flagged List.
For each entity: fetches 5 data sources (revenue, expenses, employees, transfers, grants), computes ghost score using the weighted composite scorer, returns an `EntityAnalysisResult`.

Results are ranked by ghost score. Each entity shows:
- Overall risk label (CRITICAL / HIGH / MEDIUM / LOW), ghost score, confidence
- Signal-by-signal breakdown with values vs. thresholds
- Temporal info (first grant, last grant, last CRA filing)
- "Open in Report" to pass the entity directly to the Report page

**✨ NEW: AI Executive Summary** - LLM-generated 3-4 sentence summary at the top provides executive-level overview of batch analysis findings, risk distribution, and priority actions.

**Portfolio Dashboard**
Scans the full funded universe without any flagging step.
- Aggregates risk by province, entity type, and funding band
- Shows department-level risk rates (which departments fund the most risky organizations)
- Top 25 highest-risk entities ranked by rules triggered
- "Open in Report" from any entry in the top entities list

**✨ NEW: Executive Summary** - LLM-generated 4-5 sentence summary at the top of the aggregate dashboard provides senior officials with immediate context on portfolio-wide risk patterns.

### Report
Three tabs for comprehensive reporting:

**Entity Dashboard**
Detailed risk assessment for a specific organization.
- **✨ NEW: Narrative Brief at Top** - LLM-generated 3-4 paragraph executive briefing appears immediately after the header, suitable for deputy ministers
- Overall risk label, ghost score, and confidence
- Signal-by-signal breakdown with evidence
- Financial summary and temporal timeline
- Recommended actions and limitations

**Aggregate Dashboard**
Portfolio-wide risk analysis across all funded entities.
- **✨ NEW: Executive Summary at Top** - LLM-generated 4-5 sentence briefing for senior officials
- Risk distribution by province, entity type, and funding band
- Department-level risk rates
- Top 25 highest-risk entities
- Geographic and sectoral patterns

**Business Report**
**✨ NEW: Professional 10-section business report** suitable for executive presentations and briefings.

Comprehensive structure includes:
1. **Executive Summary** - High-level overview with key findings and recommendations
2. **Situation Overview** - Context and scope of the analysis
3. **Key Findings** - Priority findings with severity indicators (🔴🟡🟢)
4. **Risk Assessment** - Detailed risk analysis by category
5. **Detailed Analysis** - In-depth examination of patterns and trends
6. **Recommendations** - Priority-based action items (Immediate/Short-term/Long-term)
7. **Next Steps** - Timeline and follow-up actions
8. **Limitations** - Methodology caveats and data constraints
9. **Appendices** - Supporting data and methodology details
10. **Export Options** - Download as JSON or Markdown

Features:
- Rich UI with expandable sections
- Severity icons and priority indicators
- Two-column layouts for readability
- Professional business language
- Suitable for presentations to senior officials

The selected entity from Analyze or Flagged is pre-filled into the query box.

---

## LLM Features

The app now includes comprehensive LLM integration for executive-level reporting:

### Token Budget (per full workflow)
| Feature | Tokens | Purpose |
|---|---|---|
| Fetch Way 1 Summary | 250 | Executive summary of zombie scan results |
| Fetch Way 2 Summary | 250 | Executive summary of anomaly detection |
| Analyze Batch Summary | 250 | Executive summary of batch analysis |
| Aggregate Executive Summary | 400 | Portfolio-wide risk briefing |
| Entity Narrative Brief | 1,000 | Detailed entity-level briefing |
| Business Report | 3,000 | Comprehensive professional report |
| **Total** | **4,900** | Complete workflow |

### Graceful Degradation
All LLM features include deterministic fallback:
- If AWS Bedrock credentials unavailable → deterministic output
- If LLM call fails → deterministic output
- If JSON parsing fails → deterministic output
- No crashes or errors — app continues functioning

### Executive Language
All LLM outputs are tailored for:
- Deputy ministers and senior government officials
- Policy analysts briefing executives
- Professional business presentations
- Action-oriented with clear priorities

---

## Performance Optimizations

The app has been optimized for fast startup:

### Startup Time
- **Before**: 10-30 seconds (heavy database queries on load)
- **After**: 1-3 seconds (lazy loading and conditional processing)

### Optimizations Applied
1. **Lazy Module Loading** - Heavy view modules (fetch, analyze, report) load only when accessed
2. **Conditional Preload** - Background queries run only when on Fetch/Flagged pages
3. **Disabled Cache Warming** - Portfolio cache warms naturally on first Analyze page visit

### Trade-offs
- First visit to Analyze page may take 3-5 seconds (cache warming)
- First visit to Fetch page may take 2-3 seconds (module loading)
- Overall user experience is much better with fast initial load

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

## What has been built

✅ **Complete LLM Integration**
- All 4 LLM use cases implemented with AWS Bedrock
- Unified LLM client supporting both Bedrock and Anthropic API
- Graceful fallback to deterministic output

✅ **Executive-Level Features**
- AI summaries positioned at top of all pages
- Enhanced prompts for senior officials and deputy ministers
- Comprehensive 10-section professional business reports
- Rich UI with severity icons, expandable sections, and exports

✅ **Performance Optimizations**
- Startup time reduced from 10-30 seconds to 1-3 seconds
- Lazy loading of heavy modules
- Conditional background processing
- Smart caching strategy

✅ **Professional Reporting**
- Entity-level narrative briefs (3-4 paragraphs)
- Portfolio-wide executive summaries (4-5 sentences)
- Comprehensive business reports (10 sections)
- JSON and Markdown export options

---

## What is not built yet

See `reporting-objectives.md` for the full roadmap. Short version:
- PDF export of entity risk cards
- CSV/JSON export of portfolio results
- RAG over government audit reports
- Alerts / early warning monitoring list
- Automated email reports

---

## Documentation

For more details, see:
- `FINAL_SUMMARY.md` - Complete overview of all enhancements
- `PERFORMANCE_OPTIMIZATIONS.md` - Performance optimization details
- `BUSINESS_REPORT_ENHANCEMENTS.md` - Business report structure
- `EXECUTIVE_ENHANCEMENTS_SUMMARY.md` - Executive features
- `DEPLOYMENT_CHECKLIST.md` - Deployment guide
- `QUICK_START_EXECUTIVE_FEATURES.md` - Testing guide
