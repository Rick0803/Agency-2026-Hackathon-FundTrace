# Reporting Objectives

## Scope

Two reporting levels — pick one if time is short:

- **Micro** — entity-level breakdown for a single organization
- **Macro** — program/system-level insights across the full funded universe

---

## Phase 1: Non-LLM (deterministic)

All outputs derived directly from `EntityAnalysisResult` and portfolio aggregations already computed in the Analysis layer. No API calls, no latency.

### Micro (entity-level)

- [ ] **Structured risk card** — one-page summary per entity: ghost score, overall risk label, signal breakdown table (label, severity, value vs. threshold), funding gap, key dates
- [ ] **PDF export** — render the risk card to PDF using `reportlab` or `weasyprint`; file named `risk-{bn_root}.pdf`
- [ ] **Fill-out format** — map `EntityAnalysisResult` fields to a standard audit template (e.g. government referral form); export as filled PDF or CSV

### Macro (portfolio/system-level)

- [ ] **Dashboard** — ranked lists and charts already built in the Portfolio Dashboard (Analyze tab); extend with drill-through links to micro reports
- [ ] **Department risk report** — table of departments sorted by risk rate with total funding at risk; exportable as CSV
- [ ] **Alerts / monitoring** — flag currently-active orgs where `avg_gov_dependency > 0.80` as early-warning candidates; show as a ranked list with a "days since last CRA filing" column

---

## Phase 2: LLM-assisted

Build on top of Phase 1 outputs — LLM receives the structured `EntityAnalysisResult` as JSON context, not raw data. This keeps LLM calls cheap (no DB fetching) and the output auditable.

### Micro

- [ ] **Narrative brief** — LLM writes a 3–5 paragraph human-readable risk brief from the structured result; replaces the current Analyze → Report LLM pipeline with a faster, cheaper single-call version
- [ ] **Q&A interface** — user asks follow-up questions about a specific entity; LLM answers grounded in the structured result (no hallucination risk on numbers)

### Macro

- [ ] **RAG — retrieve government reports** — embed public audit reports and Auditor General findings; retrieve relevant passages when writing macro briefs to ground LLM claims in published sources
- [ ] **Macro narrative** — LLM writes a program- or department-level summary ("Department X funded 47 organizations, 30% show ghost capacity signals, concentrated in the Y program stream") from the portfolio aggregation output

---

## Delivery priority

| Output | Phase | Effort | Value |
|---|---|---|---|
| Structured risk card (UI) | 1 | Low | High |
| CSV / JSON export | 1 | Low | High |
| PDF export | 1 | Medium | High |
| Department dashboard | 1 | Low | High |
| Alerts / early warning list | 1 | Low | Medium |
| Narrative brief (LLM) | 2 | Medium | High |
| Q&A interface | 2 | Medium | Medium |
| RAG | 2 | High | Medium |
| Fill-out format | 1–2 | High | Medium |

---

## Bridge from Analysis to Reporting

### The data contract

`EntityAnalysisResult` (in `models/schemas.py`) is the single handoff object between analysis and reporting. Analysis always produces it; reporting always consumes it. Neither side needs to know how the other works.

For portfolio-level reporting, the handoff is the dict returned by `run_portfolio_analysis()` — containing `by_province`, `by_entity_type`, `by_funding_band`, `risk_distribution`, `top_entities`, and `departments`.

### How the handoff works in practice

```
Fetch (Way 1 / Way 2)
    → user flags entities
        → Flagged list (session state)
            → Analyze: Batch tab runs deterministic pipeline
                → EntityAnalysisResult (one per entity)
                    → Phase 1: render risk card, export PDF/CSV
                    → Phase 2: pass as JSON context to LLM → narrative brief
```

```
Analyze: Portfolio tab runs full universe scan
    → portfolio aggregations (by province, dept, funding band)
        → Phase 1: dashboard, department report, alerts
        → Phase 2: LLM receives aggregations as JSON → macro narrative
```

### Why this works without rework

- **Analysis is pure computation.** It fetches data and returns structured objects. It does not know or care what report format will consume them.
- **Reporting is pure rendering.** It receives `EntityAnalysisResult` or the portfolio dict and renders — to UI, PDF, CSV, or LLM prompt. It does not touch the database.
- **LLM is isolated to Phase 2.** When added, LLM calls take `EntityAnalysisResult` as a JSON string in the system prompt. Numbers are already computed and auditable — the LLM only writes prose, it does not fetch or calculate.
- **The Report page already follows this pattern.** The existing `run_investigation()` in `orchestrator.py` outputs `RiskBrief`, which `views/report.py` renders. Phase 2 micro reporting replaces `run_investigation()` with a cheaper single-call version that narrates a pre-computed `EntityAnalysisResult` instead of fetching data itself.

### Fields every report format needs

These are always present on `EntityAnalysisResult` and safe to depend on:

| Field | Used by |
|---|---|
| `canonical_name`, `bn_root`, `province`, `entity_type` | All formats |
| `ghost_score`, `overall_risk`, `confidence` | Risk card, PDF, narrative |
| `signals` (list of GhostSignal) | Risk card, PDF, Q&A |
| `explanation`, `top_flags` | Risk card, alert, narrative |
| `fed_total`, `funding_gap`, `avg_gov_dependency`, `avg_program_ratio` | All formats |
| `first_grant_date`, `last_grant_date`, `last_cra_filing`, `persistence` | Timeline section, PDF |
| `has_cra_data`, `has_fed_data`, `analysis_notes` | Confidence section, limitations |
