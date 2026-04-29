# agent/orchestrator.py
# Agentic orchestrator for Ghost Capacity detection.
#
# CHANGES FROM GENERIC VERSION:
# - Removed all AB-related tools (not relevant to ghost capacity).
# - Removed compute_concentration (HHI) — not the ghost signal.
# - Removed detect_duplicate_grants — not relevant here.
# - Added fetch_revenue_sources, fetch_expense_profile, fetch_employee_count,
#   fetch_transfers_out — the four CRA queries that together define ghost capacity.
# - Added fetch_ghost_cohort + detect_ghost_outliers — Isolation Forest path.
# - Added compute_ghost_score — the main composite scorer the LLM calls
#   after collecting all raw data.
# - SYSTEM_PROMPT rewritten to define ghost capacity explicitly and give the
#   LLM a precise investigation sequence to follow.
# - write_brief output schema now includes ghost_score and gap fields.

import json
import os
import time
from decimal import Decimal
from functools import lru_cache
import pandas as pd
import anthropic


class _Encoder(json.JSONEncoder):
    """Handles Decimal (psycopg2), numpy scalars, and pandas Timestamps."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if hasattr(obj, "isoformat"):          # datetime / date / Timestamp
            return obj.isoformat()
        # numpy scalar types (bool_, int64, float64, etc.)
        if hasattr(obj, "item"):
            return obj.item()
        return super().default(obj)

from tools import retrieval, analytics
from models.schemas import ToolResult, RiskBrief, RiskSignal


# ─── Tool registry ─────────────────────────────────────────────────────────────

TOOL_REGISTRY = {
    # Retrieval
    "fetch_entity":          lambda a: retrieval.fetch_entity_by_name(a["name"]),
    "fetch_entity_by_bn":    lambda a: retrieval.fetch_entity_by_bn(a["bn"]),
    "fetch_revenue_sources": lambda a: retrieval.fetch_cra_revenue_sources(a["bn"]),
    "fetch_expense_profile": lambda a: retrieval.fetch_cra_expense_profile(a["bn"]),
    "fetch_employee_count":  lambda a: retrieval.fetch_cra_employee_count(a["bn"]),
    "fetch_transfers_out":   lambda a: retrieval.fetch_cra_transfers_out(a["bn"]),
    "fetch_fed_grants":      lambda a: retrieval.fetch_fed_grants(a["bn"]),
    "fetch_fed_amendments":  lambda a: retrieval.fetch_fed_amendments(a["bn"]),
    # "fetch_ghost_cohort":    lambda a: retrieval.fetch_ghost_training_cohort(a.get("limit", 2000)),
    "fetch_ghost_cohort":    lambda a: retrieval.fetch_ghost_training_cohort(a.get("limit", 50)),


    # Analytics — LLM passes fetched rows back as "df" / "records" args
    "compute_revenue_breakdown": lambda a: analytics.compute_revenue_breakdown(
        pd.DataFrame(a["revenue_records"]), a["bn"]
    ),
    "compute_capacity_profile":  lambda a: analytics.compute_capacity_profile(
        pd.DataFrame(a["expense_records"]),
        pd.DataFrame(a["compensation_records"]),
        pd.DataFrame(a["transfer_records"]),
        a["bn"]
    ),
    "detect_ghost_outliers":     lambda a: analytics.detect_ghost_outliers(
        a["target_ratios"],
        pd.DataFrame(a["cohort_records"])
    ),
    "compute_ghost_score":       lambda a: analytics.compute_ghost_score(
        [type("R", (), r)() for r in a["revenue_profiles"]],   # re-inflate dataclasses
        [type("C", (), c)() for c in a["capacity_profiles"]],
        pd.DataFrame(a["fed_records"]),
        a.get("iso_score", 0.0),
        a.get("regime_change", None),
    ),
    "detect_regime_change":      lambda a: analytics.detect_regime_change(
        [type("R", (), r)() for r in a["revenue_profiles"]]
    ),
    "detect_amendment_creep":    lambda a: analytics.detect_amendment_creep(
        pd.DataFrame(a["amendment_records"])
    ),

    # Terminal
    "write_brief":               lambda a: a,
}


# ─── Tool definitions ──────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "fetch_entity",
        "description": (
            "Look up an organization by name in the golden records. "
            "Returns BN, which datasets it appears in (CRA / FED), and summary profiles. "
            "Call this first. If an org has FED grants but no CRA record, note it immediately."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"]
        },
    },
    {
        "name": "fetch_revenue_sources",
        "description": (
            "Fetch CRA T3010 revenue breakdown by source for each fiscal year. "
            "Returns gov_dependency_ratio (gov_total / total_revenue) per year. "
            "Ghost entities show >90% dependency across multiple years."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"bn": {"type": "string", "description": "9-digit CRA business number"}},
            "required": ["bn"]
        },
    },
    {
        "name": "fetch_expense_profile",
        "description": (
            "Fetch CRA T3010 expense breakdown: program_spend, admin_spend, total_expenses per year. "
            "program_delivery_ratio = program_spend / total_expenses. "
            "A ghost entity has this near 0 despite receiving large grants."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"bn": {"type": "string"}},
            "required": ["bn"]
        },
    },
    {
        "name": "fetch_employee_count",
        "description": (
            "Fetch employee count and estimated total compensation from cra_compensation table. "
            "Zero employees + existing compensation expenses = undisclosed individual payments."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"bn": {"type": "string"}},
            "required": ["bn"]
        },
    },
    {
        "name": "fetch_transfers_out",
        "description": (
            "Fetch gifts this charity made to other charities (qualified donees). "
            "High transfer_ratio means money is forwarded rather than used for programs. "
            "This is the pass-through pattern."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"bn": {"type": "string"}},
            "required": ["bn"]
        },
    },
    {
        "name": "fetch_fed_grants",
        "description": (
            "Fetch all federal grants for this recipient. "
            "Provides total funding received and grant span (first → last year). "
            "Compare fed_grants_total against cra_program_spend to find the funding gap."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"bn": {"type": "string"}},
            "required": ["bn"]
        },
    },
    {
        "name": "fetch_ghost_cohort",
        "description": (
            "Fetch a random sample of CRA-registered orgs that also received FED grants, "
            "with their pre-aggregated financial ratios. Used as the training set for "
            "detect_ghost_outliers (Isolation Forest). Call before detect_ghost_outliers."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "number", "description": "Sample size (default 2000)"}},
            "required": []
        },
    },
    {
        "name": "compute_revenue_breakdown",
        "description": (
            "Compute RevenueBreakdown objects from raw T3010 revenue rows. "
            "Pass the rows returned by fetch_revenue_sources as revenue_records."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "revenue_records": {"type": "array", "description": "Rows from fetch_revenue_sources"},
                "bn": {"type": "string"}
            },
            "required": ["revenue_records", "bn"]
        },
    },
    {
        "name": "compute_capacity_profile",
        "description": (
            "Compute CapacityProfile objects combining expense, compensation, and transfer rows. "
            "Returns program_delivery_ratio, compensation_ratio, transfer_ratio per year."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "expense_records":      {"type": "array", "description": "Rows from fetch_expense_profile"},
                "compensation_records": {"type": "array", "description": "Rows from fetch_employee_count"},
                "transfer_records":     {"type": "array", "description": "Rows from fetch_transfers_out"},
                "bn": {"type": "string"}
            },
            "required": ["expense_records", "compensation_records", "transfer_records", "bn"]
        },
    },
    {
        "name": "detect_ghost_outliers",
        "description": (
            "Run Isolation Forest on the target entity vs the peer cohort. "
            "Returns a normalised anomaly score 0–1. "
            "Pass target_ratios dict and cohort_records from fetch_ghost_cohort."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target_ratios":  {
                    "type": "object",
                    "description": "Dict with avg_gov_dependency, avg_program_ratio, avg_admin_ratio"
                },
                "cohort_records": {"type": "array", "description": "Rows from fetch_ghost_cohort"}
            },
            "required": ["target_ratios", "cohort_records"]
        },
    },
    {
        "name": "compute_ghost_score",
        "description": (
            "Compute the final weighted ghost capacity composite score (0–1) and all GhostSignals. "
            "Call this after detect_ghost_outliers and detect_regime_change. "
            "Pass iso_score from detect_ghost_outliers and regime_change from detect_regime_change."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "revenue_profiles":  {"type": "array", "description": "Output of compute_revenue_breakdown"},
                "capacity_profiles": {"type": "array", "description": "Output of compute_capacity_profile"},
                "fed_records":       {"type": "array", "description": "Rows from fetch_fed_grants"},
                "iso_score":         {"type": "number", "description": "From detect_ghost_outliers / ECOD (default 0)"},
                "regime_change":     {"type": "object", "description": "From detect_regime_change (optional)"},
            },
            "required": ["revenue_profiles", "capacity_profiles", "fed_records"]
        },
    },
    {
        "name": "detect_regime_change",
        "description": (
            "Use ruptures change-point detection to find the fiscal year when government "
            "dependency shifted into the ghost zone. "
            "Pass revenue_profiles from compute_revenue_breakdown. "
            "Returns regime_change_year, pre/post averages, and a plain-English note. "
            "A clean single breakpoint with a large jump (e.g. 30% → 95%) is strong evidence "
            "the org deliberately restructured its funding, not just grew."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "revenue_profiles": {"type": "array", "description": "Output of compute_revenue_breakdown"}
            },
            "required": ["revenue_profiles"]
        },
    },
    {
        "name": "detect_amendment_creep",
        "description": (
            "Detect federal grants amended upward 3+ times. "
            "Ghost entities are often re-funded indefinitely through amendments. "
            "Fetch amendments first with fetch_fed_amendments."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "amendment_records": {"type": "array", "description": "Rows from fetch_fed_amendments"}
            },
            "required": ["amendment_records"]
        },
    },
    {
        "name": "write_brief",
        "description": (
            "Write the final ghost capacity risk brief. "
            "Call ONLY after compute_ghost_score has been called and you have specific evidence. "
            "Include ghost_score, funding_gap, and which signals were flagged."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "entity":              {"type": "string"},
                "overall_risk":        {"type": "string", "enum": ["CRITICAL","HIGH","MEDIUM","LOW","INSUFFICIENT DATA"]},
                "confidence":          {"type": "string", "enum": ["High","Medium","Low"]},
                "summary":             {"type": "string"},
                "signals": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label":    {"type": "string"},
                            "severity": {"type": "string"},
                            "evidence": {"type": "string"},
                            "source":   {"type": "string"}
                        }
                    }
                },
                "recommended_actions": {"type": "array", "items": {"type": "string"}},
                "datasets_checked":    {"type": "array", "items": {"type": "string"}},
                "limitations":         {"type": "string"}
            },
            "required": ["entity","overall_risk","confidence","summary","signals","recommended_actions"]
        },
    },
]


# ─── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """
You are a government accountability analyst investigating ghost capacity entities in Canadian public funding data.

DEFINITION — Ghost Capacity:
An organization that receives ongoing government funding but shows no evidence of being able to deliver
what it was funded to do. Key characteristics:
  - Revenue is almost entirely government transfers (no earned income, no donations)
  - Expenses flow to compensation for a small number of individuals OR to transfers to other entities
  - Zero or near-zero employees despite receiving grants large enough to require staff
  - This pattern persists across multiple fiscal years — they are not startups or winding down
  - They are NOT zombie entities (ceased activity) — they remain registered and keep receiving money

INVESTIGATION SEQUENCE (follow this order):
1. fetch_entity              → confirm BN, check CRA + FED presence
   If org has FED grants but NO CRA record: flag immediately as unverifiable ghost
2. fetch_fed_grants           → how much federal money, which departments, over how many years
3. fetch_revenue_sources      → gov_dependency_ratio per year (ghost flag: >90%)
4. fetch_expense_profile      → program_delivery_ratio per year (ghost flag: <20%)
5. fetch_employee_count       → are there any employees? (ghost flag: 0 employees)
6. fetch_transfers_out        → is money forwarded to other entities? (ghost flag: >40% of expenses)
7. compute_revenue_breakdown  → pass revenue rows, get structured profiles
8. compute_capacity_profile   → pass expense + compensation + transfer rows, get profiles
9. fetch_ghost_cohort         → get peer training set for ECOD anomaly detection
10. detect_ghost_outliers      → ECOD score vs peers (parameter-free)
11. detect_regime_change       → find the year gov dependency first crossed into ghost zone
12. compute_ghost_score        → composite score from all dimensions (pass regime_change output)
13. detect_amendment_creep     → is the funding being silently extended? (optional)
14. write_brief                → produce the final assessment

GHOST SCORE INTERPRETATION:
  0.0–0.3  Not a ghost
  0.3–0.6  Possible ghost — note as medium concern
  0.6–0.8  Probable ghost — high concern
  0.8–1.0  Strong ghost signal — CRITICAL

EVIDENCE REQUIREMENTS for write_brief:
  - State ghost_score from compute_ghost_score
  - State funding_gap (FED grants received minus CRA program spend)
  - Cite at least two specific data facts (e.g. "97% gov dependency for 4 consecutive years")
  - Note which signals were flagged vs not flagged
  - If CRA data is missing, state it explicitly as a limitation
""".strip()


# ─── Analysis-only tool definitions and prompt (Mode 2) ───────────────────────

ANALYSIS_TOOL_DEFINITIONS = [t for t in TOOL_DEFINITIONS if t["name"] != "write_brief"]

ANALYSIS_SYSTEM_PROMPT = """
You are a government accountability analyst investigating ghost capacity entities in Canadian public funding data.

DEFINITION — Ghost Capacity:
An organization that receives ongoing government funding but shows no evidence of being able to deliver
what it was funded to do. Key characteristics:
  - Revenue is almost entirely government transfers (no earned income, no donations)
  - Expenses flow to compensation for a small number of individuals OR to transfers to other entities
  - Zero or near-zero employees despite receiving grants large enough to require staff
  - This pattern persists across multiple fiscal years

ANALYSIS SEQUENCE (follow this order, then stop):
1. fetch_entity              → confirm BN, check CRA + FED presence
2. fetch_fed_grants          → total federal funding, departments, span
3. fetch_revenue_sources     → gov_dependency_ratio per year
4. fetch_expense_profile     → program_delivery_ratio per year
5. fetch_employee_count      → headcount and compensation
6. fetch_transfers_out       → pass-through pattern
7. compute_revenue_breakdown → structured revenue profiles
8. compute_capacity_profile  → structured capacity profiles
9. fetch_ghost_cohort        → peer cohort for anomaly detection
10. detect_ghost_outliers    → ECOD score vs peers
11. detect_regime_change     → when did the pattern start?
12. compute_ghost_score      → final composite score

After calling compute_ghost_score, you are done. Do NOT call write_brief.
Stop and let the system display the computed scores and signals.
""".strip()


# ─── Tool execution ─────────────────────────────────────────────────────────────

def execute_tool(name: str, args: dict) -> ToolResult:
    if name not in TOOL_REGISTRY:
        return ToolResult(tool_name=name, success=False, data=None, error=f"Unknown tool: {name}")
    try:
        result = TOOL_REGISTRY[name](args)
        if hasattr(result, "__dataclass_fields__"):
            from dataclasses import asdict
            result = asdict(result)
        elif isinstance(result, list) and result and hasattr(result[0], "__dataclass_fields__"):
            from dataclasses import asdict
            result = [asdict(r) for r in result]
        elif hasattr(result, "to_dict"):
            result = result.to_dict("records")
        return ToolResult(tool_name=name, success=True, data=result)
    except Exception as e:
        return ToolResult(tool_name=name, success=False, data=None, error=str(e))


# ─── Agent loop ─────────────────────────────────────────────────────────────────

def run_investigation(user_query: str, max_iterations: int = 25) -> RiskBrief:
    """
    Runs the ghost capacity investigation for a given query.
    The LLM follows the INVESTIGATION SEQUENCE in SYSTEM_PROMPT,
    calling tools iteratively until it produces a write_brief.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    messages   = [{"role": "user", "content": user_query}]
    brief_data = None

    for _ in range(max_iterations):
        for attempt in range(5):
            try:
                # Switch to claude-sonnet-4-6 for the actual hackathon.
                # Haiku has higher rate limits for local testing on a new key.
                model = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
                response = client.messages.create(
                    model      = model,
                    max_tokens = 4096,
                    system     = SYSTEM_PROMPT,
                    tools      = TOOL_DEFINITIONS,
                    messages   = messages,
                )
                break
            except anthropic.RateLimitError:
                if attempt == 4:
                    raise
                wait = 60 * (attempt + 1)
                print(f"Rate limited — waiting {wait}s before retry {attempt + 2}/5...")
                time.sleep(wait)
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            break

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            result = execute_tool(block.name, block.input)
            if block.name == "write_brief" and result.success:
                brief_data = result.data
            tool_results.append({
                "type":        "tool_result",
                "tool_use_id": block.id,
                "content":     json.dumps(result.data or {"error": result.error}, cls=_Encoder),
            })

        messages.append({"role": "user", "content": tool_results})

        if brief_data:
            break

    if not brief_data:
        return RiskBrief(
            entity="Unknown", overall_risk="INSUFFICIENT DATA", confidence="Low",
            summary="Investigation did not complete within the iteration limit.",
            signals=[], recommended_actions=["Retry with a known BN."],
            datasets_checked=[], limitations="Agent hit max_iterations."
        )

    return RiskBrief(
        entity               = brief_data.get("entity", "Unknown"),
        overall_risk         = brief_data.get("overall_risk", "INSUFFICIENT DATA"),
        confidence           = brief_data.get("confidence", "Low"),
        summary              = brief_data.get("summary", ""),
        signals              = [RiskSignal(**s) for s in brief_data.get("signals", [])],
        recommended_actions  = brief_data.get("recommended_actions", []),
        datasets_checked     = brief_data.get("datasets_checked", []),
        limitations          = brief_data.get("limitations", ""),
    )


NARRATIVE_REPORT_SYSTEM_PROMPT = """
You write concise public-funding risk briefs from already-computed structured analysis.

Rules:
- Use only the JSON supplied by the user. Do not invent numbers, dates, datasets, or missing evidence.
- Do not call tools. The analysis has already been computed deterministically.
- Keep the summary to 3-5 short paragraphs suitable for an investigator or audit reviewer.
- Explain what the strongest signals mean in plain English.
- Mention limitations when CRA or FED data is missing, confidence is low, or analysis_notes are present.
- Return JSON only with this shape:
{
  "entity": "name",
  "overall_risk": "CRITICAL|HIGH|MEDIUM|LOW|INSUFFICIENT DATA",
  "confidence": "High|Medium|Low",
  "summary": "3-5 paragraphs",
  "signals": [
    {"label": "signal label", "severity": "severity", "evidence": "specific evidence", "source": "EntityAnalysisResult"}
  ],
  "recommended_actions": ["action"],
  "datasets_checked": ["CRA", "FED"],
  "limitations": "limitations"
}
""".strip()


BUSINESS_REPORT_SYSTEM_PROMPT = """
You are a Senior Executive Policy Analyst for the Government of Alberta.
Use ONLY the data provided. Do not invent numbers or facts.
Write in plain language. Be concise, objective, and politically neutral.
Focus on impacts, risks, and actionable recommendations.
Return JSON only with this exact shape:
{
  "document_classification": "FOR INFORMATION|ADVICE TO MINISTER|CONFIDENTIAL",
  "ar_number": "AR-2026-XXXX",
  "topic": "1-2 line title",
  "purpose": "FOR INFORMATION|BACKGROUNDER|DECISION REQUIRED",
  "issue": "1-2 sentence issue statement",
  "recommendation_advice": ["bullet 1", "bullet 2"],
  "background": ["bullet 1", "bullet 2"],
  "current_status_key_considerations": ["bullet 1", "bullet 2", "bullet 3"],
  "communications": ["bullet 1"],
  "attachments": ["attachment 1"],
  "contact": "placeholder or provided contact",
  "reviewed_approved_by": "placeholder or provided approver"
}
If a section cannot be supported from the data, return "N/A based on provided data." for that field or as the only bullet in that section.
""".strip()


def _build_report_context(batch_results: list, portfolio_result: dict) -> dict:
    """Builds the compact input context passed to the LLM (or used by the stub)."""
    total      = len(batch_results)
    critical   = sum(1 for r in batch_results if r.overall_risk == "CRITICAL")
    high       = sum(1 for r in batch_results if r.overall_risk == "HIGH")
    avg_score  = sum(r.ghost_score for r in batch_results) / max(total, 1)
    total_fed  = sum(r.fed_total for r in batch_results)
    total_gap  = sum(r.funding_gap for r in batch_results)

    stats      = portfolio_result.get("portfolio", {})
    by_prov    = stats.get("by_province", pd.DataFrame())
    univ_total = portfolio_result.get("total_entities", 0)
    univ_risky = int(by_prov["risky_count"].sum()) if not by_prov.empty and "risky_count" in by_prov.columns else 0

    sorted_results = sorted(batch_results, key=lambda r: r.ghost_score, reverse=True)
    entity_lines = [
        f"{r.overall_risk}|{r.canonical_name}|score {r.ghost_score:.2f}|{','.join(r.top_flags or [])}|{r.province}"
        for r in sorted_results
    ]

    return {
        "aggregate": {
            "total_analyzed":    total,
            "critical":          critical,
            "high":              high,
            "avg_ghost_score":   round(avg_score, 3),
            "total_fed_funding": round(total_fed, 0),
            "total_funding_gap": round(total_gap, 0),
            "universe_total":    univ_total,
            "universe_risky":    univ_risky,
        },
        "entities": entity_lines,
    }


def run_business_report(batch_results: list, portfolio_result: dict) -> dict:
    """
    Returns a placeholder executive briefing note payload matching the
    future LLM-ready structure for macro reporting.

    STUB — deterministic output until API credentials are available.
    To activate the LLM, replace the body below with:

        client = anthropic.Anthropic()
        context = _build_report_context(batch_results, portfolio_result)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            system=BUSINESS_REPORT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": json.dumps(context, cls=_Encoder)}],
        )
        return _parse_json_object(_extract_text(response))
    """
    total     = len(batch_results)
    critical  = sum(1 for r in batch_results if r.overall_risk == "CRITICAL")
    high      = sum(1 for r in batch_results if r.overall_risk == "HIGH")
    top       = max(batch_results, key=lambda r: r.ghost_score) if batch_results else None
    total_gap = sum(r.funding_gap for r in batch_results)
    total_fed = sum(r.fed_total for r in batch_results)
    top_name = top.canonical_name if top else "N/A based on provided data."
    purpose = "FOR INFORMATION"

    if critical or high:
        topic = "Risk review of shortlisted public-funding recipients with elevated ghost-capacity indicators"
    else:
        topic = "Summary of shortlisted public-funding recipient review"

    if critical:
        issue = (
            f"{critical} of {total} reviewed organization{'s' if total > 1 else ''} "
            "show CRITICAL ghost-capacity indicators based on the provided analysis."
        )
    elif high:
        issue = (
            f"{high} of {total} reviewed organization{'s' if total > 1 else ''} "
            "show HIGH-risk ghost-capacity patterns based on the provided analysis."
        )
    else:
        issue = (
            f"The reviewed set of {total} organization{'s' if total > 1 else ''} "
            "does not currently cross the high-risk threshold based on the provided analysis."
        )

    if critical or high:
        recommendation_advice = [
            f"Prioritize follow-up review of {top_name} as the highest-risk entity in the analyzed set.",
            "Review CRITICAL and HIGH-rated entities before the next funding decision point.",
        ]
    else:
        recommendation_advice = ["None required - For information only."]

    background = [
        f"A total of {total} shortlisted organization{'s' if total > 1 else ''} were analyzed using linked CRA and federal funding records.",
        f"The analysis considered ghost score, risk indicators, funding exposure, and filing-related signals using the provided data.",
    ]

    current_status = [
        f"{critical} entity(ies) are rated CRITICAL and {high} entity(ies) are rated HIGH in the current review set.",
        f"Total federal funding across the reviewed set is ${total_fed:,.0f}.",
        (
            f"Combined funding gap across the reviewed set is ${total_gap:,.0f}."
            if total_gap > 0 else "No positive combined funding gap was identified in the reviewed set."
        ),
        (
            f"{top_name} is currently the highest-risk organization based on ghost score."
            if top else "N/A based on provided data."
        ),
    ]

    communications = [
        "None identified."
    ]

    attachments = [
        "Entity analysis dashboard export",
        "Aggregate risk dashboard export",
    ]

    return {
        "document_classification": "FOR INFORMATION",
        "ar_number": "AR-2026-XXXX",
        "topic": topic,
        "purpose": purpose,
        "issue": issue,
        "recommendation_advice": recommendation_advice,
        "background": background,
        "current_status_key_considerations": current_status,
        "communications": communications,
        "attachments": attachments,
        "contact": "N/A based on provided data.",
        "reviewed_approved_by": "N/A based on provided data.",
    }


def run_narrative_report_from_analysis(analysis_result: dict) -> RiskBrief:
    """
    Phase 2 reporting — one cheap LLM call from an EntityAnalysisResult dict.
    The LLM writes prose only; it does not fetch or calculate.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    model = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
    response = client.messages.create(
        model=model,
        max_tokens=2048,
        system=NARRATIVE_REPORT_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": json.dumps(analysis_result, indent=2, cls=_Encoder),
        }],
    )
    brief_data = _parse_json_object(_extract_text(response))
    return RiskBrief(
        entity=brief_data.get("entity", analysis_result.get("canonical_name", "Unknown")),
        overall_risk=brief_data.get("overall_risk", analysis_result.get("overall_risk", "INSUFFICIENT DATA")),
        confidence=brief_data.get("confidence", analysis_result.get("confidence", "Low")),
        summary=brief_data.get("summary", ""),
        signals=[RiskSignal(**s) for s in brief_data.get("signals", [])],
        recommended_actions=brief_data.get("recommended_actions", []),
        datasets_checked=brief_data.get("datasets_checked", []),
        limitations=brief_data.get("limitations", ""),
    )


# ─── Mode 1: Fetch (no LLM) ────────────────────────────────────────────────────

OPEN_SEARCH_SYSTEM_PROMPT = """
You convert natural-language Open Search requests into a safe JSON query specification.

The app searches aggregate CRA + federal funding metrics for ghost-capacity investigation.
Do not write SQL. Choose only from the allowed fields below.

Allowed metrics:
- prefilter_score: blended ghost-capacity heuristic
- transfers_out_total: total CRA transfers/gifts out to other donees
- fed_total: total federal funding
- funding_to_program_gap: federal funding minus CRA program spend
- avg_gov_dependency: government revenue share
- avg_program_ratio: program spend share of expenses
- total_employees: CRA-reported total employees
- total_compensation: CRA compensation total
- avg_admin_ratio: admin spend share of expenses
- cra_years: number of CRA filing years
- fed_agreement_count: number of federal agreements

Allowed filters:
- province: string, e.g. "ON"
- city: string
- entity_type: string
- min_fed_total: number
- max_fed_total: number
- min_transfers_out: number
- min_gov_dependency: ratio 0-1
- max_program_ratio: ratio 0-1
- min_funding_gap: number
- min_cra_years: number
- zero_employees: boolean

Return JSON only:
{
  "metric": "allowed metric",
  "sort": "desc|asc",
  "limit": 10,
  "filters": {},
  "explanation": "brief plain-English interpretation"
}

Defaults:
- If user asks for "most suspicious", use metric "prefilter_score", sort "desc".
- If user asks for "top transfers out", use "transfers_out_total", sort "desc".
- If user asks for "lowest program spend", use "avg_program_ratio", sort "asc".
- Limit must be 1-100. Default to 10 if unspecified.
""".strip()


OPEN_SEARCH_ALLOWED_METRICS = {
    "prefilter_score",
    "transfers_out_total",
    "fed_total",
    "funding_to_program_gap",
    "avg_gov_dependency",
    "avg_program_ratio",
    "total_employees",
    "total_compensation",
    "avg_admin_ratio",
    "cra_years",
    "fed_agreement_count",
}

OPEN_SEARCH_ALLOWED_FILTERS = {
    "province",
    "city",
    "entity_type",
    "min_fed_total",
    "max_fed_total",
    "min_transfers_out",
    "min_gov_dependency",
    "max_program_ratio",
    "min_funding_gap",
    "min_cra_years",
    "zero_employees",
}


def _extract_text(response) -> str:
    chunks = []
    for block in response.content:
        if getattr(block, "type", None) == "text":
            chunks.append(block.text)
    return "\n".join(chunks).strip()


def _parse_json_object(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


def sanitize_open_search_spec(spec: dict, default_limit: int = 10) -> dict:
    metric = spec.get("metric", "prefilter_score")
    if metric not in OPEN_SEARCH_ALLOWED_METRICS:
        metric = "prefilter_score"

    sort = spec.get("sort", "desc")
    sort = "asc" if sort == "asc" else "desc"

    try:
        limit = int(spec.get("limit", default_limit))
    except (TypeError, ValueError):
        limit = default_limit
    limit = max(1, min(limit, 100))

    raw_filters = spec.get("filters", {}) or {}
    filters = {
        key: value
        for key, value in raw_filters.items()
        if key in OPEN_SEARCH_ALLOWED_FILTERS and value not in (None, "")
    }

    return {
        "metric": metric,
        "sort": sort,
        "limit": limit,
        "filters": filters,
        "explanation": spec.get("explanation", ""),
    }


def interpret_open_search_query(query: str, default_limit: int = 10) -> dict:
    """Use the LLM to convert natural language into a safe Open Search spec."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    model = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=OPEN_SEARCH_SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": query,
        }],
    )
    parsed = _parse_json_object(_extract_text(response))
    return sanitize_open_search_spec(parsed, default_limit)


def run_open_search(query: str, default_limit: int = 10) -> dict:
    """
    Open Search — natural language to safe query spec, then allowlisted DB query.
    The LLM interprets intent only; SQL is generated by retrieval.py.
    """
    spec = interpret_open_search_query(query, default_limit)
    results_df = retrieval.fetch_open_search_candidates(
        limit=spec["limit"],
        metric=spec["metric"],
        sort=spec["sort"],
        filters=spec["filters"],
    )
    return {
        "spec": spec,
        "results": results_df.to_dict("records"),
    }


def run_open_search_prefilter(
    candidate_limit: int = 50,
    min_fed_total: float = 0,
    metric: str = "prefilter_score",
    sort: str = "desc",
    filters: dict = None,
) -> pd.DataFrame:
    """Open Search helper — deterministic preview without an LLM call."""
    return retrieval.fetch_open_search_candidates(candidate_limit, min_fed_total, metric, sort, filters)


def run_entity_filter_options() -> dict:
    """Mode 1 helper — dropdown values for the Fetch-mode picker."""
    return retrieval.fetch_entity_filter_options()


def count_entity_picker_options(search: str = "", filters: dict = None) -> int:
    """Mode 1 helper — count matching entities for the Fetch-mode picker."""
    return retrieval.count_entity_picker_options(search, filters)


def run_entity_picker_options(search: str = "", limit: int = 100, filters: dict = None) -> pd.DataFrame:
    """Mode 1 helper — lightweight entity list for the Fetch-mode picker."""
    return retrieval.fetch_entity_picker_options(search, limit, filters)


@lru_cache(maxsize=1)
def run_fed_entity_count() -> int:
    return retrieval.fetch_fed_entity_count()


@lru_cache(maxsize=12)
def _run_way2_scan_cached(
    min_fed_total: float = 0,
    model_name: str = "ECOD",
    peer_grouping: str = "By entity type + funding band",
) -> pd.DataFrame:
    """
    Way 2 — unsupervised anomaly detection. No LLM.
    Fetches the full entity feature table, engineers ML features, scores anomalies
    within peer groups, and adds human-readable explanations.
    Returns a DataFrame sorted by anomaly_score descending.
    """
    feature_df = retrieval.fetch_way2_feature_table_fast(min_fed_total=min_fed_total)
    if feature_df.empty:
        return feature_df
    scored_df = analytics.score_way2_anomalies(feature_df, model_name, peer_grouping)
    explained_df = analytics.explain_way2_results(scored_df)
    return explained_df.sort_values("anomaly_score", ascending=False).reset_index(drop=True)


def run_way2_scan(
    min_fed_total: float = 0,
    model_name: str = "ECOD",
    peer_grouping: str = "By entity type + funding band",
) -> pd.DataFrame:
    return _run_way2_scan_cached(float(min_fed_total), model_name, peer_grouping).copy()


@lru_cache(maxsize=24)
def _run_zombie_heuristics_cached(
    gov_dependency_threshold: float = 0.70,
    min_fed_total: float = 0,
    revenue_cliff_threshold: float = 0.50,
    ceased_cutoff_year: int = 2023,
    filing_window_days: int = 365,
    young_org_years: int = 2,
) -> pd.DataFrame:
    """Way 1 — rule-based zombie recipient scan. No LLM."""
    return retrieval.fetch_zombie_heuristics_fast(
        gov_dependency_threshold,
        min_fed_total,
        revenue_cliff_threshold,
        ceased_cutoff_year,
        filing_window_days,
        young_org_years,
    )


def run_zombie_heuristics(
    gov_dependency_threshold: float = 0.70,
    min_fed_total: float = 0,
    revenue_cliff_threshold: float = 0.50,
    ceased_cutoff_year: int = 2023,
    filing_window_days: int = 365,
    young_org_years: int = 2,
) -> pd.DataFrame:
    return _run_zombie_heuristics_cached(
        float(gov_dependency_threshold),
        float(min_fed_total),
        float(revenue_cliff_threshold),
        int(ceased_cutoff_year),
        int(filing_window_days),
        int(young_org_years),
    ).copy()


def run_fetch(entity_name: str) -> dict:
    """
    Mode 1 — pure DB retrieval, no LLM.
    Looks up the entity then fetches all six raw DataFrames.
    Returns a dict the app can display directly as tables.
    """
    entity = retrieval.fetch_entity_by_name(entity_name)
    if not entity:
        return {"error": f"No entity found matching '{entity_name}'"}

    bn = entity.get("bn_root", "")
    if not bn:
        return {"error": "Entity found but has no CRA business number (BN)."}

    return {
        "entity":           entity,
        "fed_grants":       retrieval.fetch_fed_grants(bn),
        "revenue_sources":  retrieval.fetch_cra_revenue_sources(bn),
        "expense_profile":  retrieval.fetch_cra_expense_profile(bn),
        "employee_count":   retrieval.fetch_cra_employee_count(bn),
        "transfers_out":    retrieval.fetch_cra_transfers_out(bn),
    }


# ─── Mode 2: Analysis (LLM, no report) ────────────────────────────────────────

def run_analysis(user_query: str, max_iterations: int = 25) -> dict:
    """
    Mode 2 — LLM runs steps 1–12 (fetch + compute), stops before write_brief.
    Returns the raw GhostCapacityProfile dict from compute_ghost_score so the
    app can display scores and signals without a narrative report.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    messages      = [{"role": "user", "content": user_query}]
    ghost_profile = None

    for _ in range(max_iterations):
        for attempt in range(5):
            try:
                model = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
                response = client.messages.create(
                    model      = model,
                    max_tokens = 4096,
                    system     = ANALYSIS_SYSTEM_PROMPT,
                    tools      = ANALYSIS_TOOL_DEFINITIONS,
                    messages   = messages,
                )
                break
            except anthropic.RateLimitError:
                if attempt == 4:
                    raise
                wait = 60 * (attempt + 1)
                print(f"Rate limited — waiting {wait}s before retry {attempt + 2}/5...")
                time.sleep(wait)

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            break

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            result = execute_tool(block.name, block.input)
            if block.name == "compute_ghost_score" and result.success:
                ghost_profile = result.data
            tool_results.append({
                "type":        "tool_result",
                "tool_use_id": block.id,
                "content":     json.dumps(result.data or {"error": result.error}, cls=_Encoder),
            })

        messages.append({"role": "user", "content": tool_results})

        if ghost_profile and response.stop_reason == "end_turn":
            break

    return ghost_profile or {"error": "Analysis did not produce a ghost score within the iteration limit."}


# ─── Deterministic analysis (no LLM) ──────────────────────────────────────────

@lru_cache(maxsize=256)
def _run_single_entity_analysis_cached(
    bn: str,
    entity_name: str,
    entity_type: str,
    province: str,
    fed_total: float,
    rules_triggered: int,
):
    """
    Cached single-entity analysis for the Analyze step.

    Keyed by stable entity attributes so repeated elevation of the same shortlist
    can reuse prior work instead of refetching all five data sources.
    """
    from models.schemas import EntityAnalysisResult

    try:
        revenue_df   = retrieval.fetch_cra_revenue_sources(bn)
        expense_df   = retrieval.fetch_cra_expense_profile(bn)
        employee_df  = retrieval.fetch_cra_employee_count(bn)
        transfers_df = retrieval.fetch_cra_transfers_out(bn)
        grants_df    = retrieval.fetch_fed_grants(bn)

        return analytics.analyze_entity_from_data(
            bn           = bn,
            entity_name  = entity_name,
            entity_type  = entity_type,
            province     = province,
            revenue_df   = revenue_df,
            expense_df   = expense_df,
            employee_df  = employee_df,
            transfers_df = transfers_df,
            grants_df    = grants_df,
        )
    except Exception as e:
        return EntityAnalysisResult(
            canonical_name      = entity_name,
            bn_root             = bn,
            entity_type         = entity_type,
            province            = province,
            ghost_score         = 0.0,
            anomaly_score       = 0.0,
            rules_triggered     = int(rules_triggered),
            overall_risk        = "HIGH",
            confidence          = "Low",
            signals             = [],
            explanation         = "Data retrieval failed.",
            top_flags           = [],
            fed_total           = float(fed_total),
            funding_gap         = 0.0,
            avg_gov_dependency  = 0.0,
            avg_program_ratio   = 0.0,
            total_employees     = 0,
            transfers_out_total = 0.0,
            total_compensation  = 0.0,
            first_grant_date    = None,
            last_grant_date     = None,
            last_cra_filing     = None,
            cra_years           = 0,
            persistence         = "Unknown",
            has_cra_data        = False,
            has_fed_data        = False,
            analysis_notes      = str(e),
        )


def run_single_entity_analysis(entity_dict: dict):
    """
    Takes one dict from flagged_list (canonical_name, bn_root, entity_type,
    province, fed_total, rules_triggered). Fetches all 5 data sources and calls
    analytics.analyze_entity_from_data. Returns EntityAnalysisResult.
    """
    return _run_single_entity_analysis_cached(
        str(entity_dict.get("bn_root", "")),
        str(entity_dict.get("canonical_name", "")),
        str(entity_dict.get("entity_type", "")),
        str(entity_dict.get("province", "")),
        float(entity_dict.get("fed_total", 0) or 0),
        int(entity_dict.get("rules_triggered", 0) or 0),
    )


def run_entity_batch_analysis(flagged_list: list) -> list:
    """
    Iterates over flagged_list, skips entries with no bn_root,
    and calls run_single_entity_analysis for each.
    Returns list[EntityAnalysisResult].
    """
    results = []
    for entity_dict in flagged_list:
        if not entity_dict.get("bn_root"):
            continue
        result = run_single_entity_analysis(entity_dict)
        results.append(result)
    return results


def run_portfolio_analysis(min_fed_total: float = 0) -> dict:
    """
    Fast portfolio analysis — uses slim SQL table (flags pre-computed in SQL)
    and skips ML scoring entirely. department stats run as a separate aggregation query.
    Returns dict: {"portfolio": portfolio_stats, "departments": dept_df,
                   "total_entities": int}
    """
    summary_df      = retrieval.fetch_portfolio_summary_table(min_fed_total=min_fed_total)
    portfolio_stats = analytics.compute_portfolio_stats_from_flags(summary_df)
    dept_df         = retrieval.fetch_department_stats()
    return {
        "portfolio":      portfolio_stats,
        "departments":    dept_df,
        "total_entities": len(summary_df),
    }
