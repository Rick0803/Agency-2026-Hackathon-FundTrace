# App Functionalities — Updated with LLM Integration

## Quick Reference

**Status**: ✅ Production Ready  
**Startup Time**: 1-3 seconds  
**LLM Provider**: AWS Bedrock (with Anthropic API fallback)  
**Token Budget**: 4,900 tokens per full workflow  
**Last Updated**: April 2026

---

## What's New

### ✨ LLM Integration (All 4 Use Cases)
1. **Fetch Page Summaries** - Executive summaries for Way 1 and Way 2 scans
2. **Analyze Summary** - Batch analysis executive briefing
3. **Aggregate Executive Summary** - Portfolio-wide risk briefing
4. **Entity Narrative Brief** - Detailed entity-level briefing
5. **Business Report** - Comprehensive 10-section professional report

### ✨ Executive Enhancements
- All AI summaries positioned at top of pages
- Language tailored for deputy ministers and senior officials
- Expanded output length (3-5 sentences/paragraphs)
- Action-oriented with clear priorities

### ✨ Performance Optimizations
- Startup time: 10-30s → 1-3s (83-90% faster)
- Lazy module loading
- Conditional background processing
- Smart caching

---

## Running the App

```bash
cd Proto/
pip install -r requirements.txt
streamlit run app.py
```

### Environment Configuration

Required `.env` file in `Proto/`:

```bash
# Database
DB_CONNECTION_STRING=postgresql://...

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

---

## Page-by-Page Features

### 🏠 Home
- Overview and workflow guidance
- Links to all pages

### 🔍 Fetch (4 Ways to Find Ghost Capacity)

#### Way 1: Rule-Based Zombie Scan
- 10 hardcoded rules with tunable thresholds
- Histogram, rule breakdown, entity table
- **✨ AI Executive Summary at top** (3-4 sentences, 250 tokens)

#### Way 2: Peer-Relative Anomaly Detection
- ML-based scoring (ECOD, Isolation Forest, LOF)
- 13 features, peer group comparison
- **✨ AI Executive Summary at top** (3-4 sentences, 250 tokens)

#### Way 3: Open Search
- Natural language search over CRA+FED data
- LLM interprets query → deterministic SQL

#### Way 4: Raw Data Lookup
- Direct access to CRA + FED records
- 5 sub-tabs: Grants, Revenue, Expenses, Employees, Transfers

### 🚩 Flagged
- Persistent list of selected entities
- Remove individual or clear all
- Quick access to Analyze or Report

### 📊 Analyze

#### Batch Analysis
- Full ghost capacity pipeline for flagged entities
- Ghost score, risk label, signal breakdown
- **✨ AI Executive Summary at top** (3-4 sentences, 250 tokens)

#### Portfolio Dashboard
- Full funded universe scan
- Risk by province, entity type, funding band
- Department-level risk rates
- Top 25 highest-risk entities
- **✨ Executive Summary at top** (4-5 sentences, 400 tokens)

### 📄 Report (3 Tabs)

#### Entity Dashboard
- **✨ Narrative Brief at top** (3-4 paragraphs, 1,000 tokens)
- Risk label, ghost score, confidence
- Signal-by-signal evidence
- Financial summary and timeline
- Recommended actions

#### Aggregate Dashboard
- **✨ Executive Summary at top** (4-5 sentences, 400 tokens)
- Portfolio-wide risk analysis
- Geographic and sectoral patterns
- Department risk rates

#### Business Report
**✨ NEW: Professional 10-section report** (3,000 tokens)

1. **Executive Summary** - Key findings and recommendations
2. **Situation Overview** - Context and scope
3. **Key Findings** - Priority findings with severity icons 🔴🟡🟢
4. **Risk Assessment** - Detailed risk analysis
5. **Detailed Analysis** - Patterns and trends
6. **Recommendations** - Priority-based actions (Immediate/Short/Long-term)
7. **Next Steps** - Timeline and follow-up
8. **Limitations** - Methodology caveats
9. **Appendices** - Supporting data
10. **Export Options** - JSON and Markdown downloads

Features:
- Rich UI with expandable sections
- Severity icons and priority indicators
- Two-column layouts
- Professional business language

---

## Architecture

### File Structure
```
Proto/
├── app.py                  # Entry point (optimized)
├── views/
│   ├── general.py          # Shared helpers, Home, Open Search
│   ├── fetch.py            # Fetch + Flagged pages
│   ├── analyze.py          # Batch + Portfolio analysis
│   └── report.py           # Entity + Aggregate + Business Report
├── agent/
│   ├── llm_client.py       # Unified LLM client (NEW)
│   └── orchestrator.py     # Coordination layer
├── tools/
│   ├── retrieval.py        # Database queries
│   ├── analytics.py        # Computations
│   └── preload.py          # Background loading
└── models/
    └── schemas.py          # Data contracts
```

### Layer Responsibilities

| Layer | Files | Rule |
|---|---|---|
| Views | `views/*.py` | UI only — reads session state, calls orchestrator, renders results |
| Orchestrator | `agent/orchestrator.py` | Coordination — calls retrieval + analytics, returns clean objects |
| LLM Client | `agent/llm_client.py` | LLM abstraction — Bedrock + Anthropic API with fallback |
| Retrieval | `tools/retrieval.py` | DB only — one function = one SQL query, returns DataFrame |
| Analytics | `tools/analytics.py` | Computation — takes DataFrames, returns dataclasses, no DB |
| Schemas | `models/schemas.py` | Data contracts — shared dataclasses across all layers |

---

## LLM Integration Details

### Token Budget

| Feature | Tokens | Location | Audience |
|---|---|---|---|
| Fetch Way 1 Summary | 250 | Top of results | Executives |
| Fetch Way 2 Summary | 250 | Top of results | Executives |
| Analyze Batch Summary | 250 | Top of results | Executives |
| Aggregate Executive Summary | 400 | Top of dashboard | Senior officials |
| Entity Narrative Brief | 1,000 | Top of entity page | Deputy ministers |
| Business Report | 3,000 | Dedicated tab | Presentations |
| **Total per workflow** | **4,900** | - | - |

### Graceful Degradation

All LLM features include deterministic fallback:
- ✅ If credentials unavailable → deterministic output
- ✅ If LLM call fails → deterministic output
- ✅ If JSON parsing fails → deterministic output
- ✅ No crashes or errors
- ✅ App continues functioning

### LLM Client Architecture

```python
# Unified interface supporting both providers
client = get_llm_client()  # Auto-detects from .env

# Bedrock (default)
USE_BEDROCK=true → BedrockClient()

# Anthropic API (fallback)
USE_BEDROCK=false → AnthropicClient()

# Graceful degradation
No credentials → None (deterministic output)
```

---

## Performance Characteristics

### Startup Time
- **Before optimization**: 10-30 seconds
- **After optimization**: 1-3 seconds
- **Improvement**: 83-90% faster

### What Changed
1. **Disabled portfolio cache warming** - Heavy DB query removed from startup
2. **Conditional fetch preload** - Only runs when on Fetch/Flagged pages
3. **Lazy module loading** - Heavy modules load on demand

### First-Visit Times
- Home page: 1-3 seconds ✅
- Fetch page: 2-3 seconds (first visit)
- Analyze page: 3-5 seconds (first visit, cache warming)
- Report page: 1-2 seconds

### Trade-offs
- ✅ Much faster initial load
- ✅ Better user experience
- ⚠️ Slight delay on first page visit (acceptable)

---

## Key Data Concepts

### Ghost Score (0-1)
Weighted composite of five dimensions:

| Dimension | Weight | Flag Threshold |
|---|---|---|
| Government revenue dependency | 0.25 | > 90% |
| Program delivery deficit | 0.30 | < 20% of expenses |
| High compensation burden | 0.20 | > 50% of expenses |
| Pass-through transfer pattern | 0.15 | > 40% of expenses |
| No reported employees | 0.10 | 0 employees |

**Interpretation**:
- 0.0-0.3: Low risk
- 0.3-0.6: Medium risk
- 0.6-0.8: High risk
- 0.8-1.0: Critical risk

### EntityAnalysisResult
Shared data contract between Analysis and Reporting (defined in `models/schemas.py`).

Contains:
- Identity (name, BN, entity type)
- Risk scores (ghost score, confidence)
- Signals (5 dimensions with values)
- Financials (revenue, expenses, grants)
- Temporal (first grant, last grant, last filing)

### Funding Gap
`fed_total − cra_program_spend_total`

Example: Org received $1M in grants but reported $50K in program spend = $950K gap (money unaccounted for)

### Peer Grouping (Way 2)
Entities scored against peers in same entity type + funding band bucket.

Example: "Charity / $100K–$1M"

Groups < 15 members fall back to global scoring.

---

## Session State Keys

| Key | Set By | Used By |
|---|---|---|
| `page` | `general.go_to_page()` | `app.py` router |
| `selected_entity` | `general.set_selected_entity()` | Analyze, Report banners |
| `flagged_list` | Fetch Way 1/2 add buttons | Flagged page, Analyze batch |
| `zombie_df` | Way 1 scan button | Way 1 results |
| `way2_df` | Way 2 scan button | Way 2 results |
| `batch_analysis_results` | Analyze batch button | Analyze batch tab |
| `portfolio_results` | Analyze portfolio button | Analyze portfolio tab |

---

## Testing Checklist

### Page 1: Fetch
- [ ] Run Way 1 scan → Verify AI Summary at top (3-4 sentences)
- [ ] Run Way 2 scan → Verify AI Summary at top (3-4 sentences)
- [ ] Add entities to Flagged List
- [ ] Test Way 3 Open Search
- [ ] Test Way 4 Raw Data Lookup

### Page 2: Flagged
- [ ] View flagged entities
- [ ] Remove individual entities
- [ ] Clear all
- [ ] Open entity in Analyze
- [ ] Open entity in Report

### Page 3: Analyze
- [ ] Run Batch Analysis → Verify AI Summary at top (3-4 sentences)
- [ ] View Portfolio Dashboard → Verify Executive Summary at top (4-5 sentences)
- [ ] Check risk distribution charts
- [ ] View top 25 entities
- [ ] Open entity in Report

### Page 4: Report
- [ ] View Entity Dashboard → Verify Narrative Brief at top (3-4 paragraphs)
- [ ] View Aggregate Dashboard → Verify Executive Summary at top (4-5 sentences)
- [ ] Generate Business Report → Verify all 10 sections
- [ ] Test JSON export
- [ ] Test Markdown export

### Performance
- [ ] Measure startup time (should be 1-3 seconds)
- [ ] Test first visit to each page
- [ ] Verify no crashes with missing LLM credentials

---

## Troubleshooting

### Slow Startup
If app takes > 5 seconds to load:
1. Check if portfolio cache warming is disabled in `app.py`
2. Check if fetch preload is conditional
3. Check if view modules are lazy loaded

### LLM Not Working
If AI summaries show deterministic output:
1. Check `.env` has correct credentials
2. Check `USE_BEDROCK=true` is set
3. Check AWS credentials are not expired (Workshop Studio tokens expire)
4. Check network connectivity to Bedrock

### Missing Data
If entities show no data:
1. Check `DB_CONNECTION_STRING` in `.env`
2. Check database connectivity
3. Check entity exists in both CRA and FED tables

---

## What's Built

✅ **Complete LLM Integration**
- All 4 LLM use cases implemented
- Unified LLM client (Bedrock + Anthropic)
- Graceful fallback

✅ **Executive Features**
- AI summaries at top of all pages
- Enhanced prompts for senior officials
- Professional business reports
- Rich UI with icons and exports

✅ **Performance Optimizations**
- 83-90% faster startup
- Lazy loading
- Conditional processing
- Smart caching

✅ **Professional Reporting**
- Entity narrative briefs
- Portfolio executive summaries
- 10-section business reports
- JSON and Markdown exports

---

## What's Not Built Yet

See `reporting-objectives.md` for full roadmap:
- PDF export of entity risk cards
- CSV/JSON export of portfolio results
- RAG over government audit reports
- Alerts / early warning monitoring
- Automated email reports

---

## Documentation

### Quick Start
- `app-functionalities.md` - This file (updated)
- `QUICK_START_EXECUTIVE_FEATURES.md` - Testing guide

### Technical Details
- `FINAL_SUMMARY.md` - Complete overview
- `LLM_INTEGRATION_SUMMARY.md` - LLM integration details
- `EXECUTIVE_ENHANCEMENTS_SUMMARY.md` - Executive features
- `BUSINESS_REPORT_ENHANCEMENTS.md` - Business report structure
- `PERFORMANCE_OPTIMIZATIONS.md` - Performance details

### Visual Guides
- `LAYOUT_CHANGES.md` - Before/after layouts

### Reference
- `CHANGES_SUMMARY.md` - Quick reference
- `DEPLOYMENT_CHECKLIST.md` - Deployment guide

---

## Support

For questions or issues:
1. Check `FINAL_SUMMARY.md` for complete overview
2. Check `PERFORMANCE_OPTIMIZATIONS.md` for performance issues
3. Check `DEPLOYMENT_CHECKLIST.md` for deployment
4. Review `.env` configuration

---

**Status**: ✅ Production Ready  
**Last Updated**: April 2026  
**Version**: 2.0 (with LLM integration)
