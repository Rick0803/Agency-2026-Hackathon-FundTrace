# tools/analytics.py
# DS/DA analytical layer for Ghost Capacity detection.
#
# CHANGES FROM GENERIC VERSION:
# - Removed compute_funding_concentration (HHI/Gini) — not the ghost signal.
# - Removed detect_duplicate_grants — not relevant here.
# - Added compute_revenue_breakdown: builds RevenueBreakdown from raw T3010 rows.
# - Added compute_capacity_profile: builds CapacityProfile from expense + compensation rows.
# - Added compute_pass_through_ratio: measures what fraction of expenses are
#   transfers to other entities rather than direct program delivery.
# - Refocused Isolation Forest (detect_ghost_outliers) to use ghost-specific
#   features: gov_dependency, program_ratio, admin_ratio, transfer_ratio.
#   Training cohort is now fetched from retrieval.fetch_ghost_training_cohort().
# - Added compute_ghost_score: weighted composite of all ghost dimensions.
#   This is the primary output the LLM reasons over.
# - Kept detect_amendment_creep — ghost entities are frequently re-funded
#   with growing amendments, so this remains a supporting signal.

import pandas as pd
import numpy as np
import ruptures as rpt
from scipy.stats import percentileofscore

from models.schemas import (
    RevenueBreakdown, CapacityProfile,
    GhostSignal, GhostCapacityProfile, AnomalyResult,
    EntityAnalysisResult,
)


# ─── Revenue breakdown ─────────────────────────────────────────────────────────

def compute_revenue_breakdown(revenue_df: pd.DataFrame, bn: str) -> list[RevenueBreakdown]:
    """
    Converts raw T3010 revenue rows into RevenueBreakdown objects.
    One object per fiscal year — the LLM can check trend across years.

    gov_dependency_ratio = gov_total / total_revenue
    Computed per year so the LLM can see whether the dependency is new
    (started getting government money recently) or persistent (years of it).
    """
    results = []
    for _, row in revenue_df.iterrows():
        total = float(row.get("total_revenue", 0) or 0)
        gov   = float(row.get("gov_total", 0) or 0)
        results.append(RevenueBreakdown(
            bn                   = bn,
            fpe                  = str(row.get("fpe", "")),
            federal_grants       = float(row.get("federal_grants", 0) or 0),
            provincial_grants    = float(row.get("provincial_grants", 0) or 0),
            municipal_grants     = float(row.get("municipal_grants", 0) or 0),
            gov_total            = gov,
            private_donations    = float(row.get("private_donations", 0) or 0),
            other_revenue        = max(total - gov - float(row.get("private_donations", 0) or 0), 0),
            total_revenue        = total,
            gov_dependency_ratio = round(gov / total, 3) if total > 0 else 0.0,
        ))
    return results


# ─── Capacity profile ──────────────────────────────────────────────────────────

def compute_capacity_profile(
    expense_df:      pd.DataFrame,
    compensation_df: pd.DataFrame,
    transfers_df:    pd.DataFrame,
    bn:              str,
) -> list[CapacityProfile]:
    """
    Builds CapacityProfile per fiscal year from three DataFrames.

    Three ratios are the core of ghost capacity on the expense side:
      program_delivery_ratio = program_spend / total_expenses
        → Near 0: money received but not used for programs
      compensation_ratio     = compensation_total / total_expenses
        → High: money going to individuals, not services
      transfer_ratio         = transfers_out / total_expenses
        → High: money forwarded to other entities, not spent internally

    The ghost pattern is one (or both) of:
      (a) high compensation_ratio + near-zero program_delivery_ratio
          → a few people are paid but nothing is delivered
      (b) high transfer_ratio + near-zero program_delivery_ratio
          → money is passed through, never touched by the org itself
    """
    # Aggregate compensation and transfers by fiscal year
    comp_by_year = (
        compensation_df
        .groupby("fpe")[["total_employees", "total_compensation"]]
        .sum()
        .reset_index()
        if not compensation_df.empty else pd.DataFrame(columns=["fpe","total_employees","total_compensation"])
    )
    transfers_by_year = (
        transfers_df
        .groupby("fpe")["amount"]
        .sum()
        .reset_index()
        .rename(columns={"amount": "transfers_out"})
        if not transfers_df.empty else pd.DataFrame(columns=["fpe","transfers_out"])
    )

    results = []
    for _, row in expense_df.iterrows():
        fpe       = str(row.get("fpe", ""))
        total_exp = float(row.get("total_expenses", 0) or 0)
        prog      = float(row.get("program_spend", 0) or 0)
        admin     = float(row.get("admin_spend", 0) or 0)

        comp_row   = comp_by_year[comp_by_year["fpe"] == fpe]
        trans_row  = transfers_by_year[transfers_by_year["fpe"] == fpe]

        comp_total   = float(comp_row["total_compensation"].iloc[0]) if not comp_row.empty else 0.0
        emp_count    = int(comp_row["total_employees"].iloc[0])           if not comp_row.empty else 0
        trans_total  = float(trans_row["transfers_out"].iloc[0])          if not trans_row.empty else 0.0

        results.append(CapacityProfile(
            bn                     = bn,
            fpe                    = fpe,
            program_spend          = prog,
            admin_spend            = admin,
            fundraising_spend      = float(row.get("fundraising_spend", 0) or 0),
            total_expenses         = total_exp,
            compensation_total     = comp_total,
            transfers_out          = trans_total,
            employee_count         = emp_count,
            program_delivery_ratio = round(prog / total_exp, 3) if total_exp > 0 else 0.0,
            compensation_ratio     = round(comp_total / total_exp, 3) if total_exp > 0 else 0.0,
            transfer_ratio         = round(trans_total / total_exp, 3) if total_exp > 0 else 0.0,
        ))
    return results


# ─── Ghost capacity composite scorer ──────────────────────────────────────────

def compute_ghost_score(
    revenue_profiles:   list[RevenueBreakdown],
    capacity_profiles:  list[CapacityProfile],
    fed_grants_df:      pd.DataFrame,
    iso_score:          float = 0.0,   # from detect_ghost_outliers (ECOD)
    regime_change:      dict  = None,  # from detect_regime_change (ruptures)
) -> GhostCapacityProfile:
    """
    Combines all dimensions into a single GhostCapacityProfile.

    SCORING WEIGHTS (chosen to reflect definition severity):
      gov_dependency   0.25  — no revenue beyond government transfers
      program_deficit  0.30  — nothing actually delivered  ← highest weight
      compensation     0.20  — money going to individuals
      transfer_passthru 0.15 — money forwarded elsewhere
      no_employees     0.10  — structural inability to deliver

    Each dimension is normalised 0–1 against its threshold before weighting.
    iso_score (Isolation Forest) is used as a secondary signal — it tells the LLM
    how unusual this combination is relative to peer organisations.
    """
    rc = regime_change or {}
    if not revenue_profiles or not capacity_profiles:
        return GhostCapacityProfile(
            bn="", entity_name="", years_analyzed=0, ghost_score=0.0,
            isolation_forest_score=iso_score, signals=[],
            fed_grants_total=0, cra_program_spend_total=0,
            funding_to_program_gap=0, persistence="Unknown",
            regime_change_year=rc.get("regime_change_year"),
            regime_change_note=rc.get("note"),
            notes="Insufficient CRA data",
        )

    bn = revenue_profiles[0].bn

    # Average each ratio across available years (persistence signal baked in)
    avg_gov_dep   = np.mean([r.gov_dependency_ratio     for r in revenue_profiles])
    avg_prog_del  = np.mean([c.program_delivery_ratio   for c in capacity_profiles])
    avg_comp      = np.mean([c.compensation_ratio       for c in capacity_profiles])
    avg_transfer  = np.mean([c.transfer_ratio           for c in capacity_profiles])
    total_emp     = sum(c.employee_count                for c in capacity_profiles)
    years         = len(capacity_profiles)

    fed_total     = float(fed_grants_df["agreement_value"].sum()) if not fed_grants_df.empty else 0.0
    prog_total    = sum(c.program_spend for c in capacity_profiles)
    gap           = fed_total - prog_total

    # ── Thresholds and signals ────────────────────────────────────────────────
    # Each threshold was chosen to flag clearly anomalous behaviour while
    # avoiding false positives from genuinely small or startup charities.

    THRESHOLDS = {
        "gov_dependency":  (avg_gov_dep,  0.90, "CRITICAL", "Government Revenue Dependency",
                            f"{avg_gov_dep*100:.1f}% of revenue from government (flag: >90%)"),
        "program_deficit": (1 - avg_prog_del, 0.80, "CRITICAL", "Program Delivery Deficit",
                            f"Only {avg_prog_del*100:.1f}% of expenses go to programs (flag: <20%)"),
        "compensation":    (avg_comp, 0.50, "HIGH", "High Compensation Burden",
                            f"{avg_comp*100:.1f}% of expenses are compensation (flag: >50%)"),
        "transfer":        (avg_transfer, 0.40, "HIGH", "Pass-Through Transfer Pattern",
                            f"{avg_transfer*100:.1f}% of expenses transferred to other entities (flag: >40%)"),
        "no_employees":    (1.0 if total_emp == 0 else 0.0, 0.5, "HIGH", "No Reported Employees",
                            f"Total employees across {years} years: {total_emp}"),
    }

    WEIGHTS = {
        "gov_dependency":  0.25,
        "program_deficit": 0.30,
        "compensation":    0.20,
        "transfer":        0.15,
        "no_employees":    0.10,
    }

    signals = []
    weighted_sum = 0.0

    for key, (value, threshold, severity, label, interpretation) in THRESHOLDS.items():
        flagged = value >= threshold
        # Normalised contribution: how far above threshold (capped at 1)
        norm = min(value / (threshold + 1e-9), 1.0)
        weighted_sum += WEIGHTS[key] * norm

        signals.append(GhostSignal(
            dimension      = key,
            label          = label,
            value          = round(float(value), 3),
            threshold      = threshold,
            flagged        = flagged,
            severity       = severity if flagged else "LOW",
            interpretation = interpretation,
        ))

    ghost_score = round(float(np.clip(weighted_sum, 0, 1)), 3)

    # Persistence label
    if years >= 4:
        persistence = f"Persistent ({years} years of data)"
    elif years >= 2:
        persistence = f"Recent ({years} years of data)"
    else:
        persistence = "Insufficient history (1 year)"

    return GhostCapacityProfile(
        bn                      = bn,
        entity_name             = "",   # filled in by orchestrator from entity lookup
        years_analyzed          = years,
        ghost_score             = ghost_score,
        isolation_forest_score  = round(iso_score, 3),
        signals                 = signals,
        fed_grants_total        = round(fed_total, 2),
        cra_program_spend_total = round(prog_total, 2),
        funding_to_program_gap  = round(gap, 2),
        persistence             = persistence,
        regime_change_year      = rc.get("regime_change_year"),
        regime_change_note      = rc.get("note"),
        notes                   = "",
    )


# ─── ECOD-style: peer-relative anomaly detection ──────────────────────────────

def _ecod_scores(X_train: np.ndarray, X_target: np.ndarray) -> tuple[np.ndarray, float]:
    """
    Lightweight ECOD (Empirical Cumulative distribution-based Outlier Detection)
    implemented directly with scipy — avoids the numba/llvmlite dependency.

    Algorithm (per-feature, then summed):
      1. Compute empirical CDF value p for each observation.
      2. Take the minimum of the left and right tail: min(p, 1-p).
         This is highest for median values and lowest for extreme values.
      3. Score = sum over features of -log(tail_prob).
         Extreme observations in any feature accumulate high scores.

    This is exactly ECOD's marginal scoring step. The copula correction (third
    term in the original paper) is omitted — not needed for 3 features.
    """
    n, d = X_train.shape
    train_scores = np.zeros(n)
    target_score = 0.0

    for j in range(d):
        col = X_train[:, j]

        # Empirical CDF for each training point
        ecdf_train = np.array([percentileofscore(col, x, kind="rank") / 100.0 for x in col])
        tail_train  = np.minimum(ecdf_train, 1.0 - ecdf_train)
        train_scores += -np.log(tail_train + 1e-10)

        # CDF for the target point scored against the training distribution
        p_target    = percentileofscore(col, X_target[0, j], kind="rank") / 100.0
        tail_target = min(p_target, 1.0 - p_target)
        target_score += -np.log(tail_target + 1e-10)

    return train_scores, target_score


def detect_ghost_outliers(
    target_ratios: dict,     # {avg_gov_dependency, avg_program_ratio, avg_admin_ratio}
    cohort_df:    pd.DataFrame,
) -> float:
    """
    Scores how anomalous the target entity is vs the peer cohort using an
    ECOD-style empirical CDF outlier scorer — parameter-free (no contamination
    value to guess), no kernel tuning.

    FEATURES (all from the cohort query in retrieval.fetch_ghost_training_cohort):
      avg_gov_dependency   → government revenue share
      avg_program_ratio    → program spend share of expenses
      avg_admin_ratio      → admin spend share of expenses

    Returns a normalised anomaly score 0–1.
    The score SUPPLEMENTS compute_ghost_score — it answers:
    "Is this combination of ratios unusual even among other government-funded charities?"

    Divergence (high ghost_score, low ECOD score) suggests the entity sits inside
    a cluster of ghost-adjacent peers — worth flagging to the LLM as a note.
    """
    FEATURE_COLS = ["avg_gov_dependency", "avg_program_ratio", "avg_admin_ratio"]

    if cohort_df.empty or len(cohort_df) < 10:
        return 0.0

    X_train = cohort_df[FEATURE_COLS].fillna(0).to_numpy(dtype=float)
    X_target = np.array([[
        target_ratios.get("avg_gov_dependency", 0),
        target_ratios.get("avg_program_ratio", 0),
        target_ratios.get("avg_admin_ratio", 0),
    ]], dtype=float)

    train_scores, target_score = _ecod_scores(X_train, X_target)

    normalised = float(np.clip(
        (target_score - train_scores.min()) / (train_scores.max() - train_scores.min() + 1e-9),
        0, 1
    ))
    return round(normalised, 3)


# ─── ruptures: when did the ghost pattern start? ──────────────────────────────

def detect_regime_change(
    revenue_profiles: list[RevenueBreakdown],
) -> dict:
    """
    Uses ruptures Pelt (change-point detection) to find the fiscal year when
    government dependency shifted into the ghost zone.

    Input: revenue_profiles sorted oldest → newest (as returned by fetch_cra_revenue_sources
    with ORDER BY fpe ASC, or reversed from the DESC query).

    Returns:
      regime_change_year: str | None   — fiscal period when dependency spiked
      pre_change_avg:     float        — avg gov_dependency before the break
      post_change_avg:    float        — avg gov_dependency after the break
      n_breakpoints:      int          — number of detected breakpoints

    A single clean breakpoint (n=1) with a large pre→post jump is the clearest
    ghost signal: the entity was self-sustaining, then switched to full government
    dependence in a specific year. Multiple breakpoints or no breakpoints suggest
    either a gradual drift or a consistently dependent entity.

    Requires ≥4 data points — returns all None fields if fewer years are available.
    """
    if len(revenue_profiles) < 4:
        return {
            "regime_change_year": None,
            "pre_change_avg": None,
            "post_change_avg": None,
            "n_breakpoints": 0,
            "note": f"Only {len(revenue_profiles)} years of data — need ≥4 for change-point detection",
        }

    # Sort oldest first so the time series is chronological
    sorted_profiles = sorted(revenue_profiles, key=lambda r: r.fpe)
    years  = [r.fpe for r in sorted_profiles]
    signal = np.array([r.gov_dependency_ratio for r in sorted_profiles], dtype=float)

    # Dynp (dynamic programming) finds the single globally optimal change point.
    # We always ask for n_bkps=1, then decide if the jump is meaningful.
    # min_size=2 ensures at least 2 data points on each side of the break.
    algo = rpt.Dynp(model="l2", min_size=2, jump=1).fit(signal.reshape(-1, 1))
    result = algo.predict(n_bkps=1)  # returns [breakpoint_index, len(signal)]

    bp = result[0]  # 1-indexed; new regime starts at index bp (0-indexed)

    pre_avg  = round(float(signal[:bp].mean()), 3)
    post_avg = round(float(signal[bp:].mean()), 3)
    jump     = abs(post_avg - pre_avg)

    # Only report the change if the jump is large enough to be meaningful.
    # A ≥0.20 shift (e.g. 50% → 70%+ gov dependency) is unambiguous.
    if jump < 0.20:
        return {
            "regime_change_year": None,
            "pre_change_avg": round(float(signal.mean()), 3),
            "post_change_avg": None,
            "n_breakpoints": 0,
            "note": f"No significant regime change detected — dependency stable (max jump {jump*100:.1f}%)",
        }

    return {
        "regime_change_year": years[bp],      # first year in the new high-dependency regime
        "pre_change_avg":     pre_avg,
        "post_change_avg":    post_avg,
        "n_breakpoints":      1,
        "note": (
            f"Regime change detected at {years[bp]}: "
            f"gov dependency shifted from avg {pre_avg*100:.1f}% → {post_avg*100:.1f}%"
        ),
    }


# ─── Way 2: vectorized anomaly scoring ───────────────────────────────────────

WAY2_ML_FEATURES = [
    "avg_gov_dependency",
    "avg_program_ratio",
    "avg_admin_ratio",
    "log_fed_total",
    "log_fed_agreement_count",
    "funding_gap_ratio",
    "compensation_to_program_ratio",
    "transfers_to_expenses_ratio",
    "years_since_last_cra_filing",
    "grant_span_years",
    "revenue_cliff_ratio_filled",
    "rules_triggered",
    "gov_x_low_program",
]

WAY2_FLAG_COLS = [
    "flag_ceased", "flag_stopped_within_12mo", "flag_high_gov_dependency",
    "flag_no_cra_record", "flag_zero_private_revenue", "flag_zero_program_spend",
    "flag_comp_exceeds_programs", "flag_funding_gap", "flag_young_org", "flag_revenue_cliff",
]

WAY2_FLAG_LABELS = {
    "flag_ceased":                "Ceased filing",
    "flag_stopped_within_12mo":   "Stopped filing near grant end",
    "flag_high_gov_dependency":   "High gov dependency",
    "flag_no_cra_record":         "No CRA record",
    "flag_zero_private_revenue":  "Zero private revenue",
    "flag_zero_program_spend":    "Zero program spend",
    "flag_comp_exceeds_programs": "Compensation > program spend",
    "flag_funding_gap":           "Federal funding > program spend",
    "flag_young_org":             "Young org at first grant",
    "flag_revenue_cliff":         "Revenue cliff",
}

MIN_GROUP_SIZE = 15


def _ecod_scores_vectorized(X: np.ndarray) -> np.ndarray:
    """
    Vectorized ECOD: empirical CDF rank-based scoring for all rows simultaneously.
    O(n·d·log n) — avoids the O(n²) per-row percentileofscore loop.
    Score = sum over features of -log(min(rank/n, 1 - rank/n)).
    Extreme values (in either tail) accumulate high scores.
    """
    n, d = X.shape
    scores = np.zeros(n)
    for j in range(d):
        col = X[:, j]
        # argsort of argsort gives 0-based ranks; +1 makes them 1..n
        ranks = np.argsort(np.argsort(col)).astype(float) + 1
        p = ranks / n
        tail = np.minimum(p, 1.0 - p)
        scores += -np.log(tail + 1e-10)
    return scores


def _normalize_01(arr: np.ndarray) -> np.ndarray:
    lo, hi = arr.min(), arr.max()
    if hi - lo < 1e-9:
        return np.zeros_like(arr)
    return (arr - lo) / (hi - lo)


def _prepare_features(df: pd.DataFrame, feature_cols: list) -> np.ndarray:
    """Fill NaN with 0, winsorize at 1st/99th percentile."""
    X = df[feature_cols].fillna(0).to_numpy(dtype=float)
    for j in range(X.shape[1]):
        p1, p99 = np.percentile(X[:, j], [1, 99])
        X[:, j] = np.clip(X[:, j], p1, p99)
    return X


def _score_group(df: pd.DataFrame, feature_cols: list, model_name: str) -> pd.DataFrame:
    df = df.copy()
    if len(df) < 2:
        df["anomaly_score"] = 0.0
        return df

    X = _prepare_features(df, feature_cols)

    if model_name == "Isolation Forest":
        from sklearn.ensemble import IsolationForest
        clf = IsolationForest(n_estimators=100, contamination=0.1, random_state=42)
        clf.fit(X)
        raw = -clf.score_samples(X)
        scores = _normalize_01(raw)
    elif model_name == "LOF":
        from sklearn.neighbors import LocalOutlierFactor
        n_neighbors = min(20, len(df) - 1)
        clf = LocalOutlierFactor(n_neighbors=n_neighbors, contamination=0.1)
        clf.fit_predict(X)
        scores = _normalize_01(-clf.negative_outlier_factor_)
    else:
        # Default: ECOD
        scores = _normalize_01(_ecod_scores_vectorized(X))

    df["anomaly_score"] = scores
    return df


_WAY2_NUMERIC_COLS = [
    "fed_total", "fed_agreement_count", "funding_gap",
    "avg_gov_dependency", "avg_program_ratio", "avg_admin_ratio",
    "total_revenue", "total_program_spend", "total_expenses",
    "total_employees", "total_compensation", "transfers_out_total",
    "revenue_cliff_ratio",
]


def build_way2_ml_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Engineers ML features from the raw Way 2 feature table.
    Uses Way 1 flags as domain knowledge features alongside ratio/log-scale metrics.
    """
    df = df.copy()

    # psycopg2 returns Decimal for NUMERIC columns — cast to float before any numpy ops
    for col in _WAY2_NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    today = pd.Timestamp.today()

    df["log_fed_total"]          = np.log1p(df["fed_total"].clip(lower=0))
    df["log_fed_agreement_count"] = np.log1p(df["fed_agreement_count"].clip(lower=0))

    df["funding_gap_ratio"] = np.where(
        df["fed_total"] > 0,
        (df["funding_gap"] / df["fed_total"]).clip(0, 1),
        0.0,
    )

    df["compensation_to_program_ratio"] = np.where(
        df["total_program_spend"] > 0,
        (df["total_compensation"] / df["total_program_spend"]).clip(0, 10),
        np.where(df["total_compensation"] > 0, 10.0, 0.0),
    )

    df["transfers_to_expenses_ratio"] = np.where(
        df["total_expenses"] > 0,
        (df["transfers_out_total"] / df["total_expenses"]).clip(0, 1),
        0.0,
    )

    last_filing = pd.to_datetime(df["last_cra_filing"], errors="coerce")
    df["years_since_last_cra_filing"] = np.where(
        last_filing.notna(),
        (today - last_filing).dt.days / 365.25,
        5.0,  # no CRA record → assume 5-year gap
    )

    first_grant = pd.to_datetime(df["first_grant_date"], errors="coerce")
    last_grant  = pd.to_datetime(df["last_grant_date"],  errors="coerce")
    df["grant_span_years"] = np.where(
        first_grant.notna() & last_grant.notna(),
        ((last_grant - first_grant).dt.days / 365.25).clip(lower=0),
        0.0,
    )

    # Revenue cliff ratio: 1.0 means stable, <1 means drop. Fill missing as 1.0 (no cliff)
    df["revenue_cliff_ratio_filled"] = pd.to_numeric(df["revenue_cliff_ratio"], errors="coerce").fillna(1.0).clip(0, 5)

    # Way 1 domain knowledge: count of rules triggered
    existing_flags = [c for c in WAY2_FLAG_COLS if c in df.columns]
    for col in existing_flags:
        df[col] = df[col].astype(bool)
    df["rules_triggered"] = df[existing_flags].sum(axis=1).astype(float)

    # Interaction: entities with high gov dependency AND low program spend are doubly suspicious
    df["gov_x_low_program"] = (
        df["avg_gov_dependency"] * (1.0 - df["avg_program_ratio"].clip(0, 1))
    )

    return df


def score_way2_anomalies(
    feature_df: pd.DataFrame,
    model_name: str = "ECOD",
    peer_grouping: str = "By entity type + funding band",
) -> pd.DataFrame:
    """
    Scores each entity with an unsupervised anomaly model within peer groups.
    Falls back to global scoring for groups smaller than MIN_GROUP_SIZE.
    """
    df = build_way2_ml_features(feature_df)

    # Assign funding band
    df["funding_band"] = pd.cut(
        df["fed_total"],
        bins=[0, 10_000, 100_000, 1_000_000, 10_000_000, float("inf")],
        labels=["<$10K", "$10K–$100K", "$100K–$1M", "$1M–$10M", "$10M+"],
        right=True,
    ).astype(str)

    group_col_map = {
        "By entity type":              ["entity_type"],
        "By funding band":             ["funding_band"],
        "By entity type + funding band": ["entity_type", "funding_band"],
    }
    group_cols = group_col_map.get(peer_grouping, [])

    # Global scores used as fallback for small groups
    global_scored = _score_group(df, WAY2_ML_FEATURES, model_name)
    anomaly_scores  = global_scored["anomaly_score"].values.copy()
    peer_group_vals = np.full(len(df), "Global", dtype=object)

    if group_cols:
        for group_key, group_idx in df.groupby(group_cols, observed=True).groups.items():
            if len(group_idx) < MIN_GROUP_SIZE:
                # Keep global fallback scores for this small group
                if isinstance(group_key, tuple):
                    label = " / ".join(str(k) for k in group_key)
                else:
                    label = str(group_key)
                peer_group_vals[df.index.get_indexer(group_idx)] = f"{label} (global fallback)"
            else:
                scored = _score_group(df.loc[group_idx], WAY2_ML_FEATURES, model_name)
                pos = df.index.get_indexer(group_idx)
                anomaly_scores[pos]  = scored["anomaly_score"].values
                if isinstance(group_key, tuple):
                    label = " / ".join(str(k) for k in group_key)
                else:
                    label = str(group_key)
                peer_group_vals[pos] = label

    df["anomaly_score"] = anomaly_scores
    df["peer_group"]    = peer_group_vals
    return df


def explain_way2_results(scored_df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds human-readable explanation and top_rules columns.
    Translates statistical anomaly scores into investigator-language using Way 1 flags.
    """
    df = scored_df.copy()
    explanations = []
    top_rules_list = []

    for _, row in df.iterrows():
        parts = []
        triggered = [
            label for col, label in WAY2_FLAG_LABELS.items()
            if col in row and bool(row[col])
        ]

        if len(triggered) >= 3:
            parts.append(f"Triggered {len(triggered)} zombie rules.")
        elif triggered:
            parts.append(f"Rules: {', '.join(triggered[:2])}.")

        if not triggered and row.get("anomaly_score", 0) > 0.7:
            parts.append("Statistically unusual despite not matching current rules.")

        gov = float(row.get("avg_gov_dependency", 0))
        if gov >= 0.90:
            parts.append(f"Gov revenue {gov*100:.0f}%.")

        prog = float(row.get("avg_program_ratio", 1))
        if prog <= 0.20:
            parts.append(f"Program spend {prog*100:.0f}%.")

        gap = float(row.get("funding_gap", 0))
        if gap > 100_000:
            parts.append(f"Funding gap ${gap:,.0f}.")

        if float(row.get("transfers_out_total", 0)) > 50_000:
            parts.append("Large transfers to other donees.")

        if row.get("flag_no_cra_record"):
            parts.append("No CRA filing history.")

        explanations.append(" ".join(parts) if parts else "No strong signals detected.")
        top_rules_list.append(", ".join(triggered[:3]) if triggered else "—")

    df["explanation"] = explanations
    df["top_rules"]   = top_rules_list
    return df


# ─── Amendment creep (supporting signal) ──────────────────────────────────────

def detect_amendment_creep(amendments_df: pd.DataFrame) -> AnomalyResult:
    """
    Ghost entities are often re-funded indefinitely through amendments rather
    than new competitive grants. This function flags that pattern.

    Unchanged from the generic version — amendment creep is dataset-agnostic.
    Signals like "agreement amended 5 times, grew from $200K to $1.2M" give
    the LLM specific evidence to cite in the persistence section of the brief.
    """
    if amendments_df.empty:
        return AnomalyResult(
            anomaly_type="amendment_creep", detected=False,
            score=0.0, evidence=[], peer_context=None,
        )

    by_agreement = amendments_df.groupby("agreement_number").agg(
        amendment_count = ("amendment_number", "count"),
        initial_value   = ("agreement_value", "min"),
        final_value     = ("agreement_value", "max"),
    ).reset_index()

    by_agreement["value_increase"] = by_agreement["final_value"] - by_agreement["initial_value"]
    by_agreement["growth_pct"]     = (
        by_agreement["value_increase"]
        / (by_agreement["initial_value"].replace(0, np.nan))
        * 100
    ).fillna(0)

    by_agreement["growth_percentile"] = by_agreement["growth_pct"].rank(pct=True)

    creeping = by_agreement[
        (by_agreement["amendment_count"] >= 3) &
        (by_agreement["value_increase"]  >  0)
    ].sort_values("value_increase", ascending=False)

    top = creeping.head(5).to_dict("records")

    return AnomalyResult(
        anomaly_type = "amendment_creep",
        detected     = len(creeping) > 0,
        score        = float(min(len(creeping) * 0.25, 1.0)),
        evidence     = top,
        peer_context = (
            f"{len(creeping)} agreements amended 3+ times upward. "
            + (f"Largest: {top[0]['agreement_number']} grew "
               f"{top[0]['growth_pct']:.0f}% "
               f"(${top[0]['initial_value']:,.0f} → ${top[0]['final_value']:,.0f})"
               if top else "")
        ),
    )


# ─── Deterministic entity analysis (no LLM) ───────────────────────────────────

def analyze_entity_from_data(
    bn: str,
    entity_name: str,
    entity_type: str,
    province: str,
    revenue_df: pd.DataFrame,
    expense_df: pd.DataFrame,
    employee_df: pd.DataFrame,
    transfers_df: pd.DataFrame,
    grants_df: pd.DataFrame,
) -> "EntityAnalysisResult":
    """
    Pure computation — no DB access. Takes pre-fetched DataFrames and returns
    an EntityAnalysisResult. All logic is deterministic (no LLM).
    """
    # 1. Build revenue, capacity, and ghost profiles
    revenue_profiles  = compute_revenue_breakdown(revenue_df, bn)
    capacity_profiles = compute_capacity_profile(expense_df, employee_df, transfers_df, bn)
    ghost_profile     = compute_ghost_score(revenue_profiles, capacity_profiles, grants_df)

    has_cra_data = len(revenue_profiles) > 0 or len(capacity_profiles) > 0
    has_fed_data = not grants_df.empty

    cra_years = ghost_profile.years_analyzed

    # 2. Derive overall_risk
    gs = ghost_profile.ghost_score
    if gs >= 0.8:
        overall_risk = "CRITICAL"
    elif gs >= 0.6:
        overall_risk = "HIGH"
    elif gs >= 0.3:
        overall_risk = "MEDIUM"
    else:
        overall_risk = "LOW"

    # 3. Confidence
    if cra_years >= 3:
        confidence = "High"
    elif cra_years >= 1:
        confidence = "Medium"
    else:
        confidence = "Low"

    # 4. Override if no CRA data
    if not has_cra_data:
        overall_risk = "HIGH"
        confidence   = "Low"

    # 5. Build explanation from flagged signals
    flagged_signals = [s for s in ghost_profile.signals if s.flagged]
    top_flags = [s.label for s in flagged_signals]
    if flagged_signals:
        parts = [s.interpretation for s in flagged_signals]
        explanation = " | ".join(parts)
    else:
        explanation = "No strong ghost signals detected."

    # 6. Derived financial aggregates
    avg_gov_dep  = (
        float(np.mean([r.gov_dependency_ratio for r in revenue_profiles]))
        if revenue_profiles else 0.0
    )
    avg_prog_ratio = (
        float(np.mean([c.program_delivery_ratio for c in capacity_profiles]))
        if capacity_profiles else 0.0
    )
    total_employees = sum(c.employee_count for c in capacity_profiles)
    transfers_out_total = sum(c.transfers_out for c in capacity_profiles)
    total_compensation  = sum(c.compensation_total for c in capacity_profiles)
    fed_total  = ghost_profile.fed_grants_total
    funding_gap = ghost_profile.funding_to_program_gap

    # 7. Temporal fields from grants_df
    first_grant_date = None
    last_grant_date  = None
    last_cra_filing  = None
    if not grants_df.empty and "agreement_start_date" in grants_df.columns:
        dates = pd.to_datetime(grants_df["agreement_start_date"], errors="coerce").dropna()
        if not dates.empty:
            first_grant_date = str(dates.min().date())
            last_grant_date  = str(dates.max().date())
    if revenue_profiles:
        last_cra_filing = max(r.fpe for r in revenue_profiles if r.fpe) or None

    return EntityAnalysisResult(
        canonical_name      = entity_name,
        bn_root             = bn,
        entity_type         = entity_type,
        province            = province,
        ghost_score         = ghost_profile.ghost_score,
        anomaly_score       = 0.0,
        rules_triggered     = len(flagged_signals),
        overall_risk        = overall_risk,
        confidence          = confidence,
        signals             = ghost_profile.signals,
        explanation         = explanation,
        top_flags           = top_flags,
        fed_total           = fed_total,
        funding_gap         = funding_gap,
        avg_gov_dependency  = avg_gov_dep,
        avg_program_ratio   = avg_prog_ratio,
        total_employees     = total_employees,
        transfers_out_total = transfers_out_total,
        total_compensation  = total_compensation,
        first_grant_date    = first_grant_date,
        last_grant_date     = last_grant_date,
        last_cra_filing     = last_cra_filing,
        cra_years           = cra_years,
        persistence         = ghost_profile.persistence,
        has_cra_data        = has_cra_data,
        has_fed_data        = has_fed_data,
        analysis_notes      = ghost_profile.notes or "",
    )


# ─── Portfolio-level stats — fast path (no ML, flags already in SQL) ──────────

def compute_portfolio_stats_from_flags(df: pd.DataFrame) -> dict:
    """
    Fast portfolio aggregation using pre-computed flag columns from
    fetch_portfolio_summary_table. No ML scoring — just pandas groupby on flags.
    """
    if df.empty:
        return {
            "by_province":       pd.DataFrame(),
            "by_entity_type":    pd.DataFrame(),
            "by_funding_band":   pd.DataFrame(),
            "risk_distribution": pd.DataFrame(),
            "top_entities":      pd.DataFrame(),
            "alerts":            pd.DataFrame(),
        }

    df = df.copy()

    for col in ["fed_total", "funding_gap", "avg_gov_dependency", "avg_program_ratio"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    flag_cols = [c for c in WAY2_FLAG_COLS if c in df.columns]
    for col in flag_cols:
        df[col] = df[col].astype(bool)
    df["rules_triggered"] = df[flag_cols].sum(axis=1)

    df["funding_band"] = pd.cut(
        df["fed_total"].clip(lower=0),
        bins=[0, 10_000, 100_000, 1_000_000, 10_000_000, float("inf")],
        labels=["<$10K", "$10K-$100K", "$100K-$1M", "$1M-$10M", "$10M+"],
        right=True,
    ).astype(str)

    def _risk_label(rt: float) -> str:
        if rt >= 5:   return "CRITICAL"
        elif rt >= 3: return "HIGH"
        elif rt >= 1: return "MEDIUM"
        return "LOW"

    df["risk_label"] = df["rules_triggered"].apply(_risk_label)

    today = pd.Timestamp.today()
    last_filing = pd.to_datetime(df["last_cra_filing"], errors="coerce")
    df["years_since_last_cra_filing"] = np.where(
        last_filing.notna(),
        (today - last_filing).dt.days / 365.25,
        5.0,
    )

    def _group_stats(grouped) -> pd.DataFrame:
        out = grouped.agg(
            total_entities     = ("rules_triggered", "count"),
            risky_count        = ("rules_triggered", lambda x: (x >= 1).sum()),
            avg_gov_dependency = ("avg_gov_dependency", "mean"),
            avg_program_ratio  = ("avg_program_ratio", "mean"),
            total_funding      = ("fed_total", "sum"),
        ).reset_index()
        out["risk_rate"] = out["risky_count"] / out["total_entities"].replace(0, np.nan)
        out["risk_rate"] = out["risk_rate"].fillna(0)
        return out.sort_values("risk_rate", ascending=False).reset_index(drop=True)

    by_province     = _group_stats(df.groupby("province",     observed=True))
    by_entity_type  = _group_stats(df.groupby("entity_type",  observed=True))
    by_funding_band = _group_stats(df.groupby("funding_band", observed=True))

    risk_dist = (
        df.groupby("risk_label", observed=True)
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
        .reset_index(drop=True)
    )

    top_cols = [
        "canonical_name", "bn_root", "province", "entity_type",
        "fed_total", "avg_gov_dependency", "avg_program_ratio",
        "funding_gap", "rules_triggered", "last_cra_filing",
        "years_since_last_cra_filing", "status",
    ]
    top_entities = (
        df[[c for c in top_cols if c in df.columns]]
        .sort_values(["rules_triggered", "funding_gap"], ascending=[False, False])
        .head(25)
        .reset_index(drop=True)
    )

    alerts_df = df[df["avg_gov_dependency"] > 0.80].copy()
    if not alerts_df.empty:
        alerts_df["days_since_last_cra_filing"] = (
            alerts_df["years_since_last_cra_filing"].fillna(0) * 365.25
        ).round().astype(int)
        alert_cols = [
            "canonical_name", "bn_root", "province", "entity_type", "status",
            "fed_total", "avg_gov_dependency", "avg_program_ratio",
            "funding_gap", "rules_triggered", "last_cra_filing",
            "days_since_last_cra_filing",
        ]
        alerts = (
            alerts_df[[c for c in alert_cols if c in alerts_df.columns]]
            .sort_values(["avg_gov_dependency", "funding_gap"], ascending=[False, False])
            .head(50)
            .reset_index(drop=True)
        )
    else:
        alerts = pd.DataFrame()

    return {
        "by_province":       by_province,
        "by_entity_type":    by_entity_type,
        "by_funding_band":   by_funding_band,
        "risk_distribution": risk_dist,
        "top_entities":      top_entities,
        "alerts":            alerts,
    }


# ─── Portfolio-level stats (no LLM) ───────────────────────────────────────────

def compute_portfolio_stats(feature_df: pd.DataFrame) -> dict:
    """
    Takes the DataFrame from fetch_way2_feature_table (already has flag columns,
    avg_gov_dependency, avg_program_ratio, province, entity_type, fed_total, funding_gap).
    Returns a dict of summary DataFrames ready for Streamlit display.
    """
    if feature_df.empty:
        return {
            "by_province":      pd.DataFrame(),
            "by_entity_type":   pd.DataFrame(),
            "by_funding_band":  pd.DataFrame(),
            "risk_distribution": pd.DataFrame(),
            "top_entities":     pd.DataFrame(),
            "alerts":           pd.DataFrame(),
        }

    df = build_way2_ml_features(feature_df)

    # ── Helper ────────────────────────────────────────────────────────────────
    def _group_stats(grouped) -> pd.DataFrame:
        out = grouped.agg(
            total_entities    = ("rules_triggered", "count"),
            risky_count       = ("rules_triggered", lambda x: (x >= 1).sum()),
            avg_gov_dependency = ("avg_gov_dependency", "mean"),
            avg_program_ratio  = ("avg_program_ratio", "mean"),
            total_funding      = ("fed_total", "sum"),
        ).reset_index()
        out["risk_rate"] = out["risky_count"] / out["total_entities"].replace(0, np.nan)
        out["risk_rate"] = out["risk_rate"].fillna(0)
        out = out.sort_values("risk_rate", ascending=False).reset_index(drop=True)
        return out

    # ── By province ───────────────────────────────────────────────────────────
    by_province = _group_stats(df.groupby("province", observed=True))

    # ── By entity_type ────────────────────────────────────────────────────────
    by_entity_type = _group_stats(df.groupby("entity_type", observed=True))

    # ── By funding band ───────────────────────────────────────────────────────
    df["funding_band"] = pd.cut(
        df["fed_total"].clip(lower=0),
        bins=[0, 10_000, 100_000, 1_000_000, 10_000_000, float("inf")],
        labels=["<$10K", "$10K-$100K", "$100K-$1M", "$1M-$10M", "$10M+"],
        right=True,
    ).astype(str)
    by_funding_band = _group_stats(df.groupby("funding_band", observed=True))

    # ── Risk distribution ─────────────────────────────────────────────────────
    def _risk_label(rt: float) -> str:
        if rt >= 5:
            return "CRITICAL"
        elif rt >= 3:
            return "HIGH"
        elif rt >= 1:
            return "MEDIUM"
        return "LOW"

    df["risk_label"] = df["rules_triggered"].apply(_risk_label)
    risk_dist = (
        df.groupby("risk_label", observed=True)
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
        .reset_index(drop=True)
    )

    # ── Top entities ──────────────────────────────────────────────────────────
    top_cols = [
        "canonical_name", "bn_root", "province", "entity_type",
        "fed_total", "avg_gov_dependency", "avg_program_ratio",
        "funding_gap", "rules_triggered", "last_cra_filing",
        "years_since_last_cra_filing", "status",
    ]
    available_cols = [c for c in top_cols if c in df.columns]
    top_entities = (
        df[available_cols]
        .sort_values(["rules_triggered", "funding_gap"], ascending=[False, False])
        .head(25)
        .reset_index(drop=True)
    )

    # ── Early-warning alerts ─────────────────────────────────────────────────
    alerts_df = df.copy()
    if "status" in alerts_df.columns:
        active_mask = alerts_df["status"].astype(str).str.lower().isin(["active", "registered"])
    else:
        active_mask = True
    alerts_df = alerts_df[
        active_mask &
        (alerts_df["avg_gov_dependency"] > 0.80)
    ].copy()
    if not alerts_df.empty:
        alerts_df["days_since_last_cra_filing"] = (
            alerts_df["years_since_last_cra_filing"].fillna(0) * 365.25
        ).round().astype(int)
        alert_cols = [
            "canonical_name", "bn_root", "province", "entity_type", "status",
            "fed_total", "avg_gov_dependency", "avg_program_ratio",
            "funding_gap", "rules_triggered", "last_cra_filing",
            "days_since_last_cra_filing",
        ]
        alert_cols = [c for c in alert_cols if c in alerts_df.columns]
        alerts = (
            alerts_df[alert_cols]
            .sort_values(["avg_gov_dependency", "funding_gap"], ascending=[False, False])
            .head(50)
            .reset_index(drop=True)
        )
    else:
        alerts = pd.DataFrame()

    return {
        "by_province":       by_province,
        "by_entity_type":    by_entity_type,
        "by_funding_band":   by_funding_band,
        "risk_distribution": risk_dist,
        "top_entities":      top_entities,
        "alerts":            alerts,
    }
