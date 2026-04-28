# models/schemas.py
# Shared data structures for the Ghost Capacity detection system.
# Covers CRA (T3010 charity filings) + FED (federal grants) only.
#
# CHANGE FROM GENERIC VERSION:
# - Replaced generic FinancialSummary with RevenueBreakdown and CapacityProfile
#   which track the specific dimensions that define ghost capacity.
# - Added GhostSignal: carries threshold + interpretation so the LLM can cite
#   exactly which threshold was crossed, not just a raw number.
# - Added GhostCapacityProfile as the main composite output replacing AnomalyResult.
# - Removed ConcentrationResult (HHI/Gini) — not the core ghost signal.
# - Kept RiskBrief and RiskSignal unchanged — still the final LLM output.

from dataclasses import dataclass, field
from typing import Any, Optional


# ─── Input ────────────────────────────────────────────────────────────────────

@dataclass
class AnalysisRequest:
    raw_query:   str
    entity_name: Optional[str]   # extracted from natural language query
    bn:          Optional[str]   # 9-digit CRA business number if known
    datasets:    list[str]       # always ["cra", "fed"] for this problem


# ─── Tool outputs ─────────────────────────────────────────────────────────────

@dataclass
class EntityProfile:
    """
    From general.entity_golden_records.
    Tells the LLM whether the entity appears in CRA, FED, or both.
    An org with large FED grants but minimal CRA footprint is an early ghost signal.
    """
    canonical_name: str
    bn:             Optional[str]
    datasets:       list[str]        # ["cra"] | ["fed"] | ["cra", "fed"]
    cra_profile:    Optional[dict]   # designation, category, registration date, status
    fed_profile:    Optional[dict]   # total_grants_value, grant_count, top_departments


@dataclass
class RevenueBreakdown:
    """
    CRA T3010 revenue split by source for one fiscal year.
    Government dependency ratio = gov_total / total_revenue.
    A ghost entity's ratio is typically > 0.90 across multiple years.

    FIELD MAPPING (verify against CRA/docs/DATA_DICTIONARY.md on event day):
      field_4500 → federal_grants       (T3010 line 4500: federal govt grants)
      field_4510 → provincial_grants    (T3010 line 4510: provincial govt grants)
      field_4520 → municipal_grants     (T3010 line 4520: municipal govt grants)
      field_3060 → private_donations    (T3010 line 3060: non-receipted donations)
      field_3070 → receipted_donations  (T3010 line 3070: receipted donations)
      field_3050 → total_revenue        (T3010 line 3050: total revenue)
    Confirm exact field numbers from DATA_DICTIONARY.md before running.
    """
    bn:                  str
    fpe:                 str          # fiscal period end (e.g. "2023-12-31")
    federal_grants:      float        # from government of Canada
    provincial_grants:   float        # from provincial governments
    municipal_grants:    float        # from municipal governments
    gov_total:           float        # federal + provincial + municipal
    private_donations:   float        # individual/corporate donors
    other_revenue:       float        # membership, fees for service, etc.
    total_revenue:       float
    gov_dependency_ratio: float       # gov_total / total_revenue (0–1)


@dataclass
class CapacityProfile:
    """
    CRA T3010 expense side — shows whether money is going to programs
    or to compensation and transfers.

    The ghost pattern is:
      program_delivery_ratio → near 0     (nothing spent on actual programs)
      compensation_ratio     → high       (most money goes to a few people)
      transfer_ratio         → high       (rest is passed to other entities)

    FIELD MAPPING (verify against DATA_DICTIONARY.md):
      field_4100 → admin_spend           (T3010 line 4100: management/admin)
      field_4110 → fundraising_spend     (T3010 line 4110: fundraising)
      field_4120 → program_spend         (T3010 line 4120: charitable programs)
      field_4950 → total_expenses        (T3010 line 4950: total expenses)
      cra_compensation table → employee salary ranges and counts
      cra_qualified_donees table → gifts made to other charities (transfers out)
    """
    bn:                     str
    fpe:                    str
    program_spend:          float        # money spent on actual charitable programs
    admin_spend:            float        # management and administration
    fundraising_spend:      float        # fundraising costs
    total_expenses:         float
    compensation_total:     float        # total from cra_compensation table
    transfers_out:          float        # total gifts made to other charities (QD table)
    employee_count:         int          # number of staff reported (0 is a red flag)
    program_delivery_ratio: float        # program_spend / total_expenses
    compensation_ratio:     float        # compensation_total / total_expenses
    transfer_ratio:         float        # transfers_out / total_expenses


@dataclass
class GhostSignal:
    """
    One observable dimension of ghost capacity — includes the threshold
    so the LLM can cite it precisely in the brief.
    """
    dimension:      str     # e.g. "gov_dependency_ratio"
    label:          str     # human label: "Government Revenue Dependency"
    value:          float   # observed value (e.g. 0.97)
    threshold:      float   # flagging threshold (e.g. 0.90)
    flagged:        bool    # value crosses threshold
    severity:       str     # "CRITICAL" | "HIGH" | "MEDIUM"
    interpretation: str     # e.g. "97% of revenue from government (threshold: >90%)"


@dataclass
class GhostCapacityProfile:
    """
    Composite ghost capacity result — aggregates all dimensions into one object
    that the LLM receives and reasons over.

    ghost_score: weighted composite 0–1
      0.0–0.3 → not a ghost
      0.3–0.6 → possible ghost, needs more review
      0.6–0.8 → probable ghost
      0.8–1.0 → strong ghost capacity signal

    isolation_forest_score: how anomalous this entity is vs the peer cohort
    (trained on all CRA-registered orgs that also received FED grants)
    """
    bn:                     str
    entity_name:            str
    years_analyzed:         int
    ghost_score:            float        # composite 0–1
    isolation_forest_score: float        # 0–1, trained on peer cohort (now ECOD)
    signals:                list[GhostSignal]
    fed_grants_total:       float        # total federal funding received
    cra_program_spend_total: float       # total program spend across analyzed years
    funding_to_program_gap:  float       # fed_grants_total - cra_program_spend_total
    persistence:            str          # "Persistent (4+ yrs)" | "Recent (1–2 yrs)"
    regime_change_year:     Optional[str]  # first year gov dependency shifted (from ruptures)
    regime_change_note:     Optional[str]  # human-readable description of the change
    notes:                  str          # e.g. "No CRA record found despite FED grants"


@dataclass
class AnomalyResult:
    """Return type for detect_amendment_creep and similar supporting signals."""
    anomaly_type: str
    detected:     bool
    score:        float        # 0–1
    evidence:     list[dict]   # top rows driving the signal
    peer_context: Optional[str]


@dataclass
class ToolResult:
    """Wrapper for every tool call result — passed back to the LLM as JSON."""
    tool_name: str
    success:   bool
    data:      Any
    error:     Optional[str] = None


# ─── Output ───────────────────────────────────────────────────────────────────

@dataclass
class RiskSignal:
    label:    str
    severity: str     # "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"
    evidence: str     # one-sentence data fact with numbers
    source:   str     # which tool produced this


@dataclass
class RiskBrief:
    """Final LLM-authored output rendered in Streamlit."""
    entity:              str
    overall_risk:        str          # "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INSUFFICIENT DATA"
    confidence:          str          # "High" | "Medium" | "Low"
    summary:             str          # 3–4 sentence narrative
    signals:             list[RiskSignal]
    recommended_actions: list[str]
    datasets_checked:    list[str]
    limitations:         str


@dataclass
class EntityAnalysisResult:
    """
    Bridge between deterministic analysis and reporting.
    Produced by analyze_entity_from_data — no LLM involved.
    """
    # Identity
    canonical_name: str
    bn_root: str
    entity_type: str
    province: str
    # Risk
    ghost_score: float          # 0–1 composite from compute_ghost_score
    anomaly_score: float        # from Way 2 if available, else 0.0
    rules_triggered: int        # count of Way 1 flags
    overall_risk: str           # CRITICAL / HIGH / MEDIUM / LOW
    confidence: str             # High / Medium / Low
    # Evidence
    signals: list               # list of GhostSignal (from compute_ghost_score)
    explanation: str            # short rule-based text summary
    top_flags: list             # names of triggered signals
    # Financials
    fed_total: float
    funding_gap: float
    avg_gov_dependency: float
    avg_program_ratio: float
    total_employees: int
    transfers_out_total: float
    total_compensation: float
    # Temporal
    first_grant_date: Optional[str]
    last_grant_date: Optional[str]
    last_cra_filing: Optional[str]
    cra_years: int
    persistence: str
    # Data availability
    has_cra_data: bool
    has_fed_data: bool
    analysis_notes: str
