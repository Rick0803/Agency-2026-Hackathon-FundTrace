# tools/retrieval.py
# Data retrieval for Ghost Capacity detection — CRA + FED only.
# All DB access lives here. Each function issues one SQL query and returns
# a pandas DataFrame. No computation happens here — that's analytics.py.

import os
from functools import lru_cache
import pandas as pd
import psycopg2
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

DB_URL = os.environ.get("DB_CONNECTION_STRING", "")
if not DB_URL:
    raise RuntimeError("DB_CONNECTION_STRING not set — check Proto/.env")


# ─── Connection ────────────────────────────────────────────────────────────────

def query(sql: str, params: dict = {}) -> pd.DataFrame:
    """
    Opens a short-lived psycopg2 connection, runs the query, returns a DataFrame.
    Uses %(name)s parameter style throughout (psycopg2 native).
    SSL is handled via ?sslmode=require in the connection string.
    """
    with psycopg2.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or None)
            cols = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
    return pd.DataFrame(rows, columns=cols)


def bn_root(bn: str) -> str:
    """
    CRA tables store full BNs (e.g. '119012607RR0001').
    Golden records store 9-digit roots (e.g. '119012607').
    Use LEFT(bn, 9) = %(bn)s in all CRA queries so both formats work.
    This helper just enforces we always pass the 9-digit root.
    """
    return bn[:9].strip()


# ─── Entity lookup ─────────────────────────────────────────────────────────────

CRA_FED_SOURCE_FILTER = "dataset_sources && ARRAY['cra','fed']::text[]"


def _entity_picker_where(search: str = "", filters: dict = None) -> tuple[str, dict]:
    filters = filters or {}
    params = {
        "search": search.strip(),
        "search_like": f"%{search.strip()}%",
    }
    clauses = [
        "bn_root IS NOT NULL",
        CRA_FED_SOURCE_FILTER,
    ]

    if search.strip():
        clauses.append("""(
            canonical_name %% %(search)s
            OR canonical_name ILIKE %(search_like)s
            OR bn_root = %(search)s
        )""")

    source = filters.get("source", "")
    if source == "cra":
        clauses.append("dataset_sources @> ARRAY['cra']::text[]")
    elif source == "fed":
        clauses.append("dataset_sources @> ARRAY['fed']::text[]")
    elif source == "cra_fed":
        clauses.append("dataset_sources @> ARRAY['cra','fed']::text[]")

    for field in ("entity_type", "status"):
        value = filters.get(field, "")
        if value:
            params[field] = value
            clauses.append(f"{field} = %({field})s")

    for field in ("city", "province"):
        value = filters.get(field, "")
        if value:
            params[field] = value
            clauses.append(f"""
                UPPER(COALESCE(
                    cra_profile->>'{field}',
                    fed_profile->>'{field}',
                    ''
                )) = UPPER(%({field})s)
            """)

    return " AND ".join(clauses), params


def fetch_entity_filter_options() -> dict:
    """Dropdown values for narrowing the Fetch-mode entity picker."""
    base_where = f"bn_root IS NOT NULL AND {CRA_FED_SOURCE_FILTER}"
    entity_types = query(f"""
        SELECT DISTINCT entity_type AS value
        FROM general.entity_golden_records
        WHERE {base_where} AND entity_type IS NOT NULL AND entity_type != ''
        ORDER BY entity_type
    """)
    statuses = query(f"""
        SELECT DISTINCT status AS value
        FROM general.entity_golden_records
        WHERE {base_where} AND status IS NOT NULL AND status != ''
        ORDER BY status
    """)
    provinces = query(f"""
        SELECT DISTINCT COALESCE(cra_profile->>'province', fed_profile->>'province') AS value
        FROM general.entity_golden_records
        WHERE {base_where}
          AND COALESCE(cra_profile->>'province', fed_profile->>'province') IS NOT NULL
          AND COALESCE(cra_profile->>'province', fed_profile->>'province') != ''
        ORDER BY value
    """)
    cities = query(f"""
        SELECT DISTINCT COALESCE(cra_profile->>'city', fed_profile->>'city') AS value
        FROM general.entity_golden_records
        WHERE {base_where}
          AND COALESCE(cra_profile->>'city', fed_profile->>'city') IS NOT NULL
          AND COALESCE(cra_profile->>'city', fed_profile->>'city') != ''
        ORDER BY value
        LIMIT 500
    """)
    return {
        "entity_types": entity_types["value"].dropna().tolist(),
        "statuses": statuses["value"].dropna().tolist(),
        "provinces": provinces["value"].dropna().tolist(),
        "cities": cities["value"].dropna().tolist(),
    }


def count_entity_picker_options(search: str = "", filters: dict = None) -> int:
    """Count matching CRA/FED entities for the Fetch-mode picker filters."""
    where_sql, params = _entity_picker_where(search, filters)
    df = query(f"""
        SELECT COUNT(*)::int AS count
        FROM general.entity_golden_records
        WHERE {where_sql}
    """, params)
    return int(df.iloc[0]["count"]) if not df.empty else 0


def fetch_entity_picker_options(search: str = "", limit: int = 100, filters: dict = None) -> pd.DataFrame:
    """
    Lightweight list for the Streamlit Fetch-mode picker.
    Keeps the page responsive by loading only identifying fields, not raw filings.
    """
    search = search.strip()
    where_sql, params = _entity_picker_where(search, filters)
    params["limit"] = limit
    order_sql = (
        "similarity(canonical_name, %(search)s) DESC, canonical_name ASC"
        if search else
        "canonical_name ASC"
    )
    sql = f"""
        SELECT *
        FROM general.entity_golden_records
        WHERE {where_sql}
        ORDER BY {order_sql}
        LIMIT %(limit)s
    """
    return query(sql, params)


def fetch_entity_by_name(name: str) -> dict:
    """
    Trigram search in golden records.
    Returns canonical_name, bn_root, dataset_sources, cra_profile, fed_profile.
    Call this first — tells the LLM whether the entity has a CRA record at all.
    An org with FED grants but no CRA entry is already suspicious.
    """
    sql = """
        SELECT canonical_name, bn_root, entity_type, status, dataset_sources,
               cra_profile, fed_profile, confidence
        FROM general.entity_golden_records
        WHERE """ + CRA_FED_SOURCE_FILTER + """
          AND canonical_name %% %(name)s
        ORDER BY similarity(canonical_name, %(name)s) DESC
        LIMIT 1
    """
    df = query(sql, {"name": name})
    return df.iloc[0].to_dict() if not df.empty else {}


def fetch_entity_by_bn(bn: str) -> dict:
    """Exact lookup by 9-digit CRA business number root."""
    sql = """
        SELECT canonical_name, bn_root, entity_type, status, dataset_sources,
               cra_profile, fed_profile
        FROM general.entity_golden_records
        WHERE """ + CRA_FED_SOURCE_FILTER + """
          AND bn_root = %(bn)s
        LIMIT 1
    """
    df = query(sql, {"bn": bn})
    return df.iloc[0].to_dict() if not df.empty else {}


# ─── Open search candidates ───────────────────────────────────────────────────

OPEN_SEARCH_METRICS = {
    "prefilter_score": "prefilter_score",
    "transfers_out_total": "transfers_out_total",
    "fed_total": "fed_total",
    "funding_to_program_gap": "funding_to_program_gap",
    "avg_gov_dependency": "avg_gov_dependency",
    "avg_program_ratio": "avg_program_ratio",
    "total_employees": "total_employees",
    "total_compensation": "total_compensation",
    "avg_admin_ratio": "avg_admin_ratio",
    "cra_years": "cra_years",
    "fed_agreement_count": "fed_agreement_count",
}


def _open_search_filters(filters: dict = None) -> tuple[list[str], dict]:
    filters = filters or {}
    clauses = []
    params = {}

    text_filters = {
        "province": "province",
        "city": "city",
        "entity_type": "entity_type",
    }
    for key, column in text_filters.items():
        value = filters.get(key)
        if value:
            params[key] = str(value)
            clauses.append(f"UPPER({column}) = UPPER(%({key})s)")

    numeric_filters = {
        "min_fed_total": ("fed_total", ">="),
        "max_fed_total": ("fed_total", "<="),
        "min_transfers_out": ("transfers_out_total", ">="),
        "min_gov_dependency": ("avg_gov_dependency", ">="),
        "max_program_ratio": ("avg_program_ratio", "<="),
        "min_funding_gap": ("funding_to_program_gap", ">="),
        "min_cra_years": ("cra_years", ">="),
    }
    for key, (column, op) in numeric_filters.items():
        value = filters.get(key)
        if value not in (None, ""):
            params[key] = float(value)
            clauses.append(f"{column} {op} %({key})s")

    if filters.get("zero_employees"):
        clauses.append("total_employees = 0")

    return clauses, params


def fetch_open_search_candidates(
    limit: int = 50,
    min_fed_total: float = 0,
    metric: str = "prefilter_score",
    sort: str = "desc",
    filters: dict = None,
) -> pd.DataFrame:
    """
    Deterministic Open Search query over CRA+FED aggregate metrics.
    Metric, sort, and filters are allowlisted so LLM output never becomes raw SQL.
    """
    metric = metric if metric in OPEN_SEARCH_METRICS else "prefilter_score"
    sort = "asc" if sort == "asc" else "desc"
    limit = max(1, min(int(limit), 200))

    combined_filters = dict(filters or {})
    if min_fed_total:
        combined_filters["min_fed_total"] = max(
            float(min_fed_total),
            float(combined_filters.get("min_fed_total") or 0),
        )
    filter_clauses, params = _open_search_filters(combined_filters)
    params["limit"] = limit

    where_tail = ""
    if filter_clauses:
        where_tail = "WHERE " + " AND ".join(filter_clauses)

    order_column = OPEN_SEARCH_METRICS[metric]
    order_sql = f"{order_column} {sort.upper()} NULLS LAST, canonical_name ASC"

    sql = f"""
        WITH fed AS (
            SELECT
                LEFT(recipient_business_number, 9) AS bn_root,
                SUM(COALESCE(agreement_value, 0))  AS fed_total,
                COUNT(*)                           AS fed_agreement_count,
                MIN(agreement_start_date)          AS first_grant_date,
                MAX(agreement_start_date)          AS last_grant_date
            FROM fed.grants_contributions
            WHERE recipient_business_number IS NOT NULL
            GROUP BY LEFT(recipient_business_number, 9)
        ),
        cra_fin AS (
            SELECT
                LEFT(bn, 9) AS bn_root,
                COUNT(DISTINCT fpe) AS cra_years,
                AVG(
                    CASE
                        WHEN COALESCE(field_4700, 0) > 0 THEN
                            CASE
                                WHEN COALESCE(field_4540,0)+COALESCE(field_4550,0)+COALESCE(field_4560,0) > 0
                                THEN (COALESCE(field_4540,0)+COALESCE(field_4550,0)+COALESCE(field_4560,0))
                                     / NULLIF(COALESCE(field_4700,0), 0)
                                ELSE COALESCE(field_4570,0) / NULLIF(COALESCE(field_4700,0), 0)
                            END
                        ELSE NULL
                    END
                ) AS avg_gov_dependency,
                AVG(COALESCE(field_4120, 0) / NULLIF(COALESCE(field_4950, 0), 0)) AS avg_program_ratio,
                AVG(COALESCE(field_4100, 0) / NULLIF(COALESCE(field_4950, 0), 0)) AS avg_admin_ratio,
                SUM(COALESCE(field_4120, 0)) AS cra_program_spend_total,
                SUM(COALESCE(field_4950, 0)) AS cra_expenses_total,
                SUM(COALESCE(field_4700, 0)) AS cra_revenue_total
            FROM cra.cra_financial_details
            GROUP BY LEFT(bn, 9)
        ),
        comp AS (
            SELECT
                LEFT(bn, 9) AS bn_root,
                SUM(COALESCE(field_300, 0)) AS total_employees,
                SUM(COALESCE(field_390, 0)) AS total_compensation
            FROM cra.cra_compensation
            GROUP BY LEFT(bn, 9)
        ),
        transfers AS (
            SELECT
                LEFT(bn, 9) AS bn_root,
                SUM(COALESCE(total_gifts, 0)) AS transfers_out_total,
                COUNT(*) AS transfer_count
            FROM cra.cra_qualified_donees
            GROUP BY LEFT(bn, 9)
        ),
        base AS (
        SELECT
            gr.canonical_name,
            gr.bn_root,
            gr.entity_type,
            gr.status,
            gr.dataset_sources,
            COALESCE(gr.cra_profile->>'city', gr.fed_profile->>'city') AS city,
            COALESCE(gr.cra_profile->>'province', gr.fed_profile->>'province') AS province,
            fed.fed_total,
            fed.fed_agreement_count,
            fed.first_grant_date,
            fed.last_grant_date,
            cra_fin.cra_years,
            ROUND(COALESCE(cra_fin.avg_gov_dependency, 0)::numeric, 3) AS avg_gov_dependency,
            ROUND(COALESCE(cra_fin.avg_program_ratio, 0)::numeric, 3) AS avg_program_ratio,
            ROUND(COALESCE(cra_fin.avg_admin_ratio, 0)::numeric, 3) AS avg_admin_ratio,
            COALESCE(comp.total_employees, 0) AS total_employees,
            COALESCE(comp.total_compensation, 0) AS total_compensation,
            COALESCE(transfers.transfers_out_total, 0) AS transfers_out_total,
            COALESCE(transfers.transfer_count, 0) AS transfer_count,
            COALESCE(cra_fin.cra_program_spend_total, 0) AS cra_program_spend_total,
            COALESCE(cra_fin.cra_expenses_total, 0) AS cra_expenses_total,
            COALESCE(fed.fed_total, 0) - COALESCE(cra_fin.cra_program_spend_total, 0) AS funding_to_program_gap,
            ROUND((
                LEAST(COALESCE(cra_fin.avg_gov_dependency, 0) / 0.90, 1.0) * 0.25
                + LEAST((1.0 - COALESCE(cra_fin.avg_program_ratio, 1.0)) / 0.80, 1.0) * 0.30
                + CASE WHEN COALESCE(comp.total_employees, 0) = 0 THEN 0.10 ELSE 0 END
                + LEAST(
                    COALESCE(transfers.transfers_out_total, 0)
                    / NULLIF(COALESCE(cra_fin.cra_expenses_total, 0), 0)
                    / 0.40,
                    1.0
                  ) * 0.15
                + LEAST(
                    GREATEST(COALESCE(fed.fed_total, 0) - COALESCE(cra_fin.cra_program_spend_total, 0), 0)
                    / NULLIF(COALESCE(fed.fed_total, 0), 0),
                    1.0
                  ) * 0.20
            )::numeric, 3) AS prefilter_score
        FROM general.entity_golden_records gr
        JOIN fed ON fed.bn_root = gr.bn_root
        JOIN cra_fin ON cra_fin.bn_root = gr.bn_root
        LEFT JOIN comp ON comp.bn_root = gr.bn_root
        LEFT JOIN transfers ON transfers.bn_root = gr.bn_root
        WHERE gr.status = 'active'
          AND gr.dataset_sources @> ARRAY['cra','fed']::text[]
        )
        SELECT *
        FROM base
        {where_tail}
        ORDER BY {order_sql}
        LIMIT %(limit)s
    """
    return query(sql, params)


# ─── CRA revenue breakdown ─────────────────────────────────────────────────────

def fetch_cra_revenue_sources(bn: str) -> pd.DataFrame:
    """
    Government vs non-government revenue per fiscal year (last 5 years).
    gov_dependency_ratio = gov_total / total_revenue.
    Ghost entities show >90% dependency year-over-year.

    VERIFIED field mapping from CRA/docs/DATA_DICTIONARY.md:
      field_4700 = Total revenue (both Section D and Schedule 6)
      field_4540 = Federal government revenue    (Schedule 6 large charities only)
      field_4550 = Provincial government revenue (Schedule 6 only)
      field_4560 = Municipal government revenue  (Schedule 6 only)
      field_4570 = Total government revenue      (Section D small charities only — combined)
      field_4500 = Total tax-receipted gifts (donations, NOT government grants)
      field_4530 = Non-tax-receipted gifts

    Section D charities (revenue < $100K) do not break out government revenue by level —
    they only have field_4570 (combined). Schedule 6 (revenue > $100K) uses
    field_4540 + field_4550 + field_4560. The COALESCE logic handles both:
    prefer the Schedule 6 breakdown, fall back to field_4570.
    """
    sql = """
        SELECT
            fd.fpe,
            COALESCE(fd.field_4540, 0)                            AS federal_grants,
            COALESCE(fd.field_4550, 0)                            AS provincial_grants,
            COALESCE(fd.field_4560, 0)                            AS municipal_grants,
            CASE
                WHEN COALESCE(fd.field_4540, 0) + COALESCE(fd.field_4550, 0)
                     + COALESCE(fd.field_4560, 0) > 0
                THEN COALESCE(fd.field_4540, 0) + COALESCE(fd.field_4550, 0)
                     + COALESCE(fd.field_4560, 0)
                ELSE COALESCE(fd.field_4570, 0)
            END                                                   AS gov_total,
            COALESCE(fd.field_4500, 0)
              + COALESCE(fd.field_4530, 0)                        AS private_donations,
            COALESCE(fd.field_4700, 0)                            AS total_revenue
        FROM cra.cra_financial_details fd
        WHERE LEFT(fd.bn, 9) = %(bn)s
        ORDER BY fd.fpe DESC
        LIMIT 5
    """
    return query(sql, {"bn": bn})


# ─── CRA expense profile ───────────────────────────────────────────────────────

def fetch_cra_expense_profile(bn: str) -> pd.DataFrame:
    """
    Program vs admin spend per fiscal year.
    program_delivery_ratio = program_spend / total_expenses.
    Ghost entities have this near 0 despite receiving large grants.

    FIELD MAPPING — verify against DATA_DICTIONARY.md:
      field_4100 = management and administration  (T3010 line 4100)
      field_4110 = fundraising                    (T3010 line 4110)
      field_4120 = charitable programs            (T3010 line 4120)
      field_4950 = total expenses                 (T3010 line 4950)
    """
    sql = """
        SELECT
            fd.fpe,
            COALESCE(fd.field_4120, 0)   AS program_spend,
            COALESCE(fd.field_4100, 0)   AS admin_spend,
            COALESCE(fd.field_4110, 0)   AS fundraising_spend,
            COALESCE(fd.field_4950, 0)   AS total_expenses
        FROM cra.cra_financial_details fd
        WHERE LEFT(fd.bn, 9) = %(bn)s
        ORDER BY fd.fpe DESC
        LIMIT 5
    """
    return query(sql, {"bn": bn})


# ─── CRA employee count ────────────────────────────────────────────────────────

def fetch_cra_employee_count(bn: str) -> pd.DataFrame:
    """
    Employee count and total compensation from cra_compensation (Schedule 3).

    VERIFIED field mapping from CRA/docs/DATA_DICTIONARY.md:
      field_300 = Total number of permanent full-time compensated positions
      field_390 = Total compensation paid to all positions in Schedule 3

    field_305 through field_345 are counts of the TOP-10 positions broken
    down by salary bracket — not all employees, just the highest-paid 10.
    For ghost capacity we want the total headcount (field_300) and total
    compensation cost (field_390).

    Zero employees (field_300 = 0 or NULL) combined with non-zero
    compensation expenses in cra_financial_details (field_4880) is the
    clearest structural ghost signal: money going to individuals not on payroll.
    """
    sql = """
        SELECT
            cc.fpe,
            COALESCE(cc.field_300, 0)    AS total_employees,
            COALESCE(cc.field_390, 0)    AS total_compensation
        FROM cra.cra_compensation cc
        WHERE LEFT(cc.bn, 9) = %(bn)s
        ORDER BY cc.fpe DESC
        LIMIT 5
    """
    return query(sql, {"bn": bn})


# ─── CRA transfers out ─────────────────────────────────────────────────────────

def fetch_cra_transfers_out(bn: str) -> pd.DataFrame:
    """
    Gifts this charity made to other charities (qualified donees).
    High transfer_ratio = money forwarded rather than used for programs.

    VERIFY table name: may be cra_qualified_donees or cra_gifts_to_donees.
    """
    sql = """
        SELECT
            qd.fpe,
            qd.donee_bn,
            qd.donee_name,
            qd.total_gifts AS amount
        FROM cra.cra_qualified_donees qd
        WHERE LEFT(qd.bn, 9) = %(bn)s
        ORDER BY qd.fpe DESC, qd.total_gifts DESC
    """
    return query(sql, {"bn": bn})


# ─── FED grants ────────────────────────────────────────────────────────────────

def fetch_fed_grants(bn: str) -> pd.DataFrame:
    """
    Federal grants for this recipient — one row per agreement (latest amendment).
    Includes agreement_start_date so analytics can compute grant_span (persistence).
    """
    sql = """
        SELECT
            agreement_number,
            agreement_value,
            owner_org_title        AS department,
            recipient_type,
            agreement_start_date,
            agreement_end_date,
            is_amendment,
            amendment_number
        FROM fed.grants_contributions
        WHERE LEFT(recipient_business_number, 9) = %(bn)s
        ORDER BY agreement_start_date ASC
    """
    return query(sql, {"bn": bn})


def fetch_fed_amendments(bn: str) -> pd.DataFrame:
    """Full amendment history for grants to this recipient."""
    sql = """
        SELECT
            agreement_number,
            amendment_number,
            agreement_value,
            owner_org_title        AS department,
            agreement_start_date
        FROM fed.grants_contributions
        WHERE LEFT(recipient_business_number, 9) = %(bn)s
          AND (is_amendment = true OR amendment_number > 0)
        ORDER BY agreement_number, amendment_number
    """
    return query(sql, {"bn": bn})


# ─── Isolation Forest training cohort ─────────────────────────────────────────

def fetch_fed_entity_count() -> int:
    """Total number of distinct entities that appear in the FED grants table."""
    df = query("""
        SELECT COUNT(DISTINCT LEFT(recipient_business_number, 9)) AS count
        FROM fed.grants_contributions
        WHERE recipient_business_number IS NOT NULL
          AND LENGTH(TRIM(recipient_business_number)) >= 9
    """)
    return int(df.iloc[0]["count"]) if not df.empty else 0


@lru_cache(maxsize=1)
def _fetch_fetch_feature_table_cached() -> pd.DataFrame:
    """
    Shared entity-level feature table for Fetch Way 1 and Way 2.

    This runs the expensive FED/CRA aggregations once per app process. Way 1
    applies rule thresholds in pandas; Way 2 reuses the same rows for anomaly
    feature engineering. The older SQL-specific functions remain below as a
    fallback/reference, but the app routes through this cached path.
    """
    sql = """
        WITH fed_agg AS (
            SELECT
                LEFT(recipient_business_number, 9)      AS bn_root,
                SUM(COALESCE(agreement_value, 0))       AS fed_total,
                COUNT(*)                                AS fed_agreement_count,
                MIN(agreement_start_date::date)         AS first_grant_date,
                MAX(agreement_start_date::date)         AS last_grant_date
            FROM fed.grants_contributions
            WHERE recipient_business_number IS NOT NULL
              AND LENGTH(TRIM(recipient_business_number)) >= 9
            GROUP BY LEFT(recipient_business_number, 9)
        ),
        cra_agg AS (
            SELECT
                LEFT(bn, 9)                             AS bn_root,
                MIN(fpe::date)                          AS first_cra_filing,
                MAX(fpe::date)                          AS last_cra_filing,
                COUNT(DISTINCT fpe)                     AS cra_years,
                AVG(
                    CASE
                        WHEN COALESCE(field_4540,0)+COALESCE(field_4550,0)+COALESCE(field_4560,0) > 0
                        THEN (COALESCE(field_4540,0)+COALESCE(field_4550,0)+COALESCE(field_4560,0))
                             / NULLIF(COALESCE(field_4700,0), 0)
                        ELSE COALESCE(field_4570,0) / NULLIF(COALESCE(field_4700,0), 0)
                    END
                )                                       AS avg_gov_dependency,
                AVG(COALESCE(field_4120, 0) / NULLIF(COALESCE(field_4950, 0), 0)) AS avg_program_ratio,
                AVG(COALESCE(field_4100, 0) / NULLIF(COALESCE(field_4950, 0), 0)) AS avg_admin_ratio,
                SUM(COALESCE(field_4700, 0))            AS total_revenue,
                SUM(COALESCE(field_4500, 0)
                  + COALESCE(field_4530, 0))            AS total_private_donations,
                SUM(COALESCE(field_4120, 0))            AS total_program_spend,
                SUM(COALESCE(field_4950, 0))            AS total_expenses
            FROM cra.cra_financial_details
            GROUP BY LEFT(bn, 9)
        ),
        cra_trend AS (
            SELECT
                bn_root,
                MAX(CASE WHEN fpe = max_fpe THEN revenue END) AS last_year_revenue,
                AVG(CASE WHEN fpe < max_fpe  THEN revenue END) AS avg_prior_revenue
            FROM (
                SELECT
                    LEFT(bn, 9)                                         AS bn_root,
                    fpe,
                    COALESCE(field_4700, 0)                             AS revenue,
                    MAX(fpe) OVER (PARTITION BY LEFT(bn, 9))            AS max_fpe
                FROM cra.cra_financial_details
            ) t
            GROUP BY bn_root
        ),
        comp_agg AS (
            SELECT
                LEFT(bn, 9)                             AS bn_root,
                SUM(COALESCE(field_300, 0))             AS total_employees,
                SUM(COALESCE(field_390, 0))             AS total_compensation
            FROM cra.cra_compensation
            GROUP BY LEFT(bn, 9)
        ),
        transfers_agg AS (
            SELECT
                LEFT(bn, 9)                             AS bn_root,
                SUM(COALESCE(total_gifts, 0))           AS transfers_out_total
            FROM cra.cra_qualified_donees
            GROUP BY LEFT(bn, 9)
        )
        SELECT
            gr.canonical_name,
            gr.bn_root,
            gr.entity_type,
            gr.status,
            gr.dataset_sources,
            COALESCE(gr.cra_profile->>'city',     gr.fed_profile->>'city')     AS city,
            COALESCE(gr.cra_profile->>'province', gr.fed_profile->>'province') AS province,
            ROUND(fed.fed_total::numeric, 2)                                   AS fed_total,
            fed.fed_agreement_count,
            fed.first_grant_date,
            fed.last_grant_date,
            cra.first_cra_filing,
            cra.last_cra_filing,
            COALESCE(cra.cra_years, 0)                                         AS cra_years,
            ROUND(COALESCE(cra.avg_gov_dependency, 0)::numeric, 3)             AS avg_gov_dependency,
            ROUND(COALESCE(cra.avg_program_ratio, 0)::numeric, 3)              AS avg_program_ratio,
            ROUND(COALESCE(cra.avg_admin_ratio, 0)::numeric, 3)                AS avg_admin_ratio,
            ROUND(COALESCE(cra.total_revenue, 0)::numeric, 2)                  AS total_revenue,
            ROUND(COALESCE(cra.total_private_donations, 0)::numeric, 2)        AS total_private_donations,
            ROUND(COALESCE(cra.total_program_spend, 0)::numeric, 2)            AS total_program_spend,
            ROUND(COALESCE(cra.total_expenses, 0)::numeric, 2)                 AS total_expenses,
            ROUND((fed.fed_total - COALESCE(cra.total_program_spend, 0))::numeric, 2) AS funding_gap,
            COALESCE(comp.total_employees, 0)                                  AS total_employees,
            COALESCE(comp.total_compensation, 0)                               AS total_compensation,
            COALESCE(transfers.transfers_out_total, 0)                         AS transfers_out_total,
            ct.last_year_revenue,
            ct.avg_prior_revenue,
            CASE WHEN ct.avg_prior_revenue > 0
                 THEN ROUND((ct.last_year_revenue / ct.avg_prior_revenue)::numeric, 3)
                 ELSE NULL END                                                 AS revenue_cliff_ratio
        FROM general.entity_golden_records gr
        JOIN      fed_agg       fed       ON fed.bn_root       = gr.bn_root
        LEFT JOIN cra_agg       cra       ON cra.bn_root       = gr.bn_root
        LEFT JOIN cra_trend     ct        ON ct.bn_root        = gr.bn_root
        LEFT JOIN comp_agg      comp      ON comp.bn_root      = gr.bn_root
        LEFT JOIN transfers_agg transfers ON transfers.bn_root = gr.bn_root
        WHERE gr.entity_type IS DISTINCT FROM 'government'
          AND gr.canonical_name NOT ILIKE 'government of %'
          AND gr.canonical_name NOT ILIKE 'province of %'
          AND gr.canonical_name NOT ILIKE 'minister of %'
          AND gr.canonical_name NOT ILIKE 'ministry of %'
          AND gr.canonical_name NOT ILIKE 'university of %'
          AND gr.canonical_name NOT ILIKE '% university'
          AND gr.canonical_name NOT ILIKE '% université'
          AND gr.canonical_name NOT ILIKE '% school board'
          AND gr.canonical_name NOT ILIKE '% school district%'
          AND gr.canonical_name NOT ILIKE 'city of %'
          AND gr.canonical_name NOT ILIKE 'town of %'
          AND gr.canonical_name NOT ILIKE 'municipality of %'
          AND gr.canonical_name NOT ILIKE '% health authority%'
          AND gr.canonical_name NOT ILIKE '% regional district%'
    """
    return query(sql)


def _fetch_feature_table() -> pd.DataFrame:
    df = _fetch_fetch_feature_table_cached().copy()
    numeric_cols = [
        "fed_total", "fed_agreement_count", "cra_years", "avg_gov_dependency",
        "avg_program_ratio", "avg_admin_ratio", "total_revenue",
        "total_private_donations", "total_program_spend", "total_expenses",
        "funding_gap", "total_employees", "total_compensation",
        "transfers_out_total", "last_year_revenue", "avg_prior_revenue",
        "revenue_cliff_ratio",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    for col in ("first_grant_date", "last_grant_date", "first_cra_filing", "last_cra_filing"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def _add_way_rule_flags(
    df: pd.DataFrame,
    gov_dependency_threshold: float = 0.70,
    revenue_cliff_threshold: float = 0.50,
    ceased_cutoff_year: int = 2023,
    filing_window_days: int = 365,
    young_org_years: int = 2,
) -> pd.DataFrame:
    df = df.copy()
    threshold   = max(0.0, min(1.0, float(gov_dependency_threshold)))
    cliff       = max(0.0, min(1.0, float(revenue_cliff_threshold)))
    cutoff_year = max(2018, min(2024, int(ceased_cutoff_year)))
    cutoff_date = pd.Timestamp(f"{cutoff_year}-01-01")
    window_days = max(30, min(1825, int(filing_window_days)))
    young_days  = max(365, min(3650, int(young_org_years) * 365))

    has_cra = df["cra_years"].fillna(0).astype(float) > 0
    last_cra = df["last_cra_filing"]
    first_cra = df["first_cra_filing"]
    last_grant = df["last_grant_date"]
    first_grant = df["first_grant_date"]

    df["flag_ceased"] = last_cra.notna() & (last_cra < cutoff_date)
    df["flag_stopped_within_12mo"] = (
        last_cra.notna()
        & last_grant.notna()
        & (last_cra >= last_grant)
        & (last_cra <= last_grant + pd.to_timedelta(window_days, unit="D"))
    )
    df["flag_high_gov_dependency"] = df["avg_gov_dependency"].fillna(0) >= threshold
    df["flag_no_cra_record"] = ~has_cra
    df["flag_zero_private_revenue"] = has_cra & (df["total_private_donations"].fillna(0) == 0)
    df["flag_zero_program_spend"] = has_cra & (df["total_program_spend"].fillna(0) == 0)
    df["flag_comp_exceeds_programs"] = (
        (df["total_compensation"].fillna(0) > df["total_program_spend"].fillna(0))
        & (df["total_compensation"].fillna(0) > 0)
    )
    df["flag_funding_gap"] = df["fed_total"].fillna(0) > df["total_program_spend"].fillna(0)
    df["flag_young_org"] = (
        first_cra.notna()
        & first_grant.notna()
        & (first_grant <= first_cra + pd.to_timedelta(young_days, unit="D"))
    )
    df["flag_revenue_cliff"] = (
        (df["avg_prior_revenue"].fillna(0) > 0)
        & (df["last_year_revenue"].fillna(0) < cliff * df["avg_prior_revenue"].fillna(0))
    )

    flag_cols = [
        "flag_ceased", "flag_stopped_within_12mo", "flag_high_gov_dependency",
        "flag_no_cra_record", "flag_zero_private_revenue", "flag_zero_program_spend",
        "flag_comp_exceeds_programs", "flag_funding_gap", "flag_young_org", "flag_revenue_cliff",
    ]
    df["rules_triggered"] = df[flag_cols].sum(axis=1).astype(int)
    df["zombie_flag"] = (df["rules_triggered"] > 0).astype(int)
    df["days_filing_after_grant"] = (last_cra - last_grant).dt.days
    return df


def fetch_zombie_heuristics_fast(
    gov_dependency_threshold: float = 0.70,
    min_fed_total: float = 0,
    revenue_cliff_threshold: float = 0.50,
    ceased_cutoff_year: int = 2023,
    filing_window_days: int = 365,
    young_org_years: int = 2,
) -> pd.DataFrame:
    df = _fetch_feature_table()
    df = _add_way_rule_flags(
        df,
        gov_dependency_threshold,
        revenue_cliff_threshold,
        ceased_cutoff_year,
        filing_window_days,
        young_org_years,
    )
    min_fed = max(0.0, float(min_fed_total))
    df = df[(df["fed_total"] >= min_fed) & (df["zombie_flag"] == 1)]
    return df.sort_values("fed_total", ascending=False).reset_index(drop=True)


def fetch_way2_feature_table_fast(
    min_fed_total: float = 0,
    gov_dependency_threshold: float = 0.70,
    revenue_cliff_threshold: float = 0.50,
    ceased_cutoff_year: int = 2023,
    filing_window_days: int = 365,
    young_org_years: int = 2,
) -> pd.DataFrame:
    df = _fetch_feature_table()
    df = _add_way_rule_flags(
        df,
        gov_dependency_threshold,
        revenue_cliff_threshold,
        ceased_cutoff_year,
        filing_window_days,
        young_org_years,
    )
    min_fed = max(0.0, float(min_fed_total))
    df = df[(df["status"] == "active") & (df["fed_total"] >= min_fed)]
    return df.reset_index(drop=True)


def fetch_zombie_heuristics(
    gov_dependency_threshold: float = 0.70,
    min_fed_total: float = 0,
    revenue_cliff_threshold: float = 0.50,
    ceased_cutoff_year: int = 2023,
    filing_window_days: int = 365,
    young_org_years: int = 2,
) -> pd.DataFrame:
    # Validate and clamp inputs so inlining them into SQL is safe
    threshold    = max(0.0, min(1.0, float(gov_dependency_threshold)))
    min_fed      = max(0.0, float(min_fed_total))
    cliff        = max(0.0, min(1.0, float(revenue_cliff_threshold)))
    cutoff_year  = max(2018, min(2024, int(ceased_cutoff_year)))
    cutoff_date  = f"{cutoff_year}-01-01"
    window_days  = max(30, min(1825, int(filing_window_days)))
    young_days   = max(365, min(3650, int(young_org_years) * 365))
    """
    Rule-based zombie recipient detection. Eight rules total.

    Original three:
      1. Ceased        — status is not 'active'
      2. Stopped filing within 12 months of last federal grant
      3. High gov dependency — avg gov revenue share >= threshold

    New five:
      4. No CRA record — entity received FED grants but has zero CRA filings
      5. Zero private revenue ever — no donations or earned income across all years
      6. Zero program spend ever — charitable program expenditure is zero across all years
      7. Ghost payroll — zero reported employees but non-zero compensation paid out
      8. Funding gap — total federal grants exceed total CRA program spend
    """
    sql = f"""
        WITH fed_agg AS (
            SELECT
                LEFT(recipient_business_number, 9)      AS bn_root,
                SUM(COALESCE(agreement_value, 0))       AS fed_total,
                COUNT(*)                                AS fed_agreement_count,
                MIN(agreement_start_date::date)         AS first_grant_date,
                MAX(agreement_start_date::date)         AS last_grant_date
            FROM fed.grants_contributions
            WHERE recipient_business_number IS NOT NULL
              AND LENGTH(TRIM(recipient_business_number)) >= 9
            GROUP BY LEFT(recipient_business_number, 9)
        ),
        cra_agg AS (
            SELECT
                LEFT(bn, 9)                             AS bn_root,
                MIN(fpe::date)                          AS first_cra_filing,
                MAX(fpe::date)                          AS last_cra_filing,
                COUNT(DISTINCT fpe)                     AS cra_years,
                AVG(
                    CASE
                        WHEN COALESCE(field_4540,0)+COALESCE(field_4550,0)+COALESCE(field_4560,0) > 0
                        THEN (COALESCE(field_4540,0)+COALESCE(field_4550,0)+COALESCE(field_4560,0))
                             / NULLIF(COALESCE(field_4700,0), 0)
                        ELSE COALESCE(field_4570,0) / NULLIF(COALESCE(field_4700,0), 0)
                    END
                )                                       AS avg_gov_dependency,
                SUM(COALESCE(field_4700, 0))            AS total_revenue,
                SUM(COALESCE(field_4500, 0)
                  + COALESCE(field_4530, 0))            AS total_private_donations,
                SUM(COALESCE(field_4120, 0))            AS total_program_spend
            FROM cra.cra_financial_details
            GROUP BY LEFT(bn, 9)
        ),
        cra_trend AS (
            SELECT
                bn_root,
                MAX(CASE WHEN fpe = max_fpe THEN revenue END) AS last_year_revenue,
                AVG(CASE WHEN fpe < max_fpe  THEN revenue END) AS avg_prior_revenue
            FROM (
                SELECT
                    LEFT(bn, 9)                                         AS bn_root,
                    fpe,
                    COALESCE(field_4700, 0)                             AS revenue,
                    MAX(fpe) OVER (PARTITION BY LEFT(bn, 9))            AS max_fpe
                FROM cra.cra_financial_details
            ) t
            GROUP BY bn_root
        ),
        comp_agg AS (
            SELECT
                LEFT(bn, 9)                             AS bn_root,
                SUM(COALESCE(field_300, 0))             AS total_employees,
                SUM(COALESCE(field_390, 0))             AS total_compensation
            FROM cra.cra_compensation
            GROUP BY LEFT(bn, 9)
        )
        SELECT
            gr.canonical_name,
            gr.bn_root,
            gr.entity_type,
            gr.status,
            gr.dataset_sources,
            COALESCE(gr.cra_profile->>'city',     gr.fed_profile->>'city')     AS city,
            COALESCE(gr.cra_profile->>'province', gr.fed_profile->>'province') AS province,
            ROUND(fed.fed_total::numeric, 2)                                   AS fed_total,
            fed.fed_agreement_count,
            fed.first_grant_date,
            fed.last_grant_date,
            cra.first_cra_filing,
            cra.last_cra_filing,
            COALESCE(cra.cra_years, 0)                                         AS cra_years,
            ROUND(COALESCE(cra.avg_gov_dependency, 0)::numeric, 3)             AS avg_gov_dependency,
            ROUND(COALESCE(cra.total_revenue, 0)::numeric, 2)                  AS total_revenue,
            ROUND(COALESCE(cra.total_program_spend, 0)::numeric, 2)            AS total_program_spend,
            ROUND((fed.fed_total - COALESCE(cra.total_program_spend, 0))::numeric, 2) AS funding_gap,
            COALESCE(comp.total_compensation, 0)                               AS total_compensation,
            (cra.last_cra_filing - fed.last_grant_date)                        AS days_filing_after_grant,
            -- R1: Ceased — last CRA filing before the cutoff year
            CASE WHEN cra.last_cra_filing IS NOT NULL
                  AND cra.last_cra_filing < '{cutoff_date}'
                 THEN true ELSE false END                                       AS flag_ceased,
            -- R2: Stopped filing within N days of last grant
            CASE WHEN cra.last_cra_filing >= fed.last_grant_date
                  AND cra.last_cra_filing <= fed.last_grant_date + INTERVAL '{window_days} days'
                 THEN true ELSE false END                                       AS flag_stopped_within_12mo,
            -- R3: High government dependency
            CASE WHEN COALESCE(cra.avg_gov_dependency, 0) >= {threshold}
                 THEN true ELSE false END                                       AS flag_high_gov_dependency,
            -- R4: No CRA record at all
            CASE WHEN cra.bn_root IS NULL
                 THEN true ELSE false END                                       AS flag_no_cra_record,
            -- R5: Zero private revenue ever
            CASE WHEN cra.bn_root IS NOT NULL
                  AND COALESCE(cra.total_private_donations, 0) = 0
                 THEN true ELSE false END                                       AS flag_zero_private_revenue,
            -- R6: Zero program spend ever
            CASE WHEN cra.bn_root IS NOT NULL
                  AND COALESCE(cra.total_program_spend, 0) = 0
                 THEN true ELSE false END                                       AS flag_zero_program_spend,
            -- R7: Compensation exceeds program spend
            CASE WHEN COALESCE(comp.total_compensation, 0) > COALESCE(cra.total_program_spend, 0)
                  AND COALESCE(comp.total_compensation, 0) > 0
                 THEN true ELSE false END                                       AS flag_comp_exceeds_programs,
            -- R8: Funding gap — federal grants exceed CRA program spend
            CASE WHEN fed.fed_total > COALESCE(cra.total_program_spend, 0)
                 THEN true ELSE false END                                       AS flag_funding_gap,
            -- R9: Young org — first grant within N days of first CRA filing
            CASE WHEN cra.first_cra_filing IS NOT NULL
                  AND fed.first_grant_date <= cra.first_cra_filing + INTERVAL '{young_days} days'
                 THEN true ELSE false END                                       AS flag_young_org,
            -- R10: Revenue cliff — last filing year revenue below threshold % of prior average
            CASE WHEN ct.avg_prior_revenue > 0
                  AND ct.last_year_revenue < {cliff} * ct.avg_prior_revenue
                 THEN true ELSE false END                                       AS flag_revenue_cliff,
            -- Zombie flag: 1 if any rule triggered
            CASE WHEN (
                (cra.last_cra_filing IS NOT NULL AND cra.last_cra_filing < '{cutoff_date}')
                OR (cra.last_cra_filing >= fed.last_grant_date
                    AND cra.last_cra_filing <= fed.last_grant_date + INTERVAL '{window_days} days')
                OR COALESCE(cra.avg_gov_dependency, 0) >= {threshold}
                OR cra.bn_root IS NULL
                OR (cra.bn_root IS NOT NULL AND COALESCE(cra.total_private_donations, 0) = 0)
                OR (cra.bn_root IS NOT NULL AND COALESCE(cra.total_program_spend, 0) = 0)
                OR (COALESCE(comp.total_compensation, 0) > COALESCE(cra.total_program_spend, 0)
                    AND COALESCE(comp.total_compensation, 0) > 0)
                OR fed.fed_total > COALESCE(cra.total_program_spend, 0)
                OR (cra.first_cra_filing IS NOT NULL
                    AND fed.first_grant_date <= cra.first_cra_filing + INTERVAL '{young_days} days')
                OR (ct.avg_prior_revenue > 0
                    AND ct.last_year_revenue < {cliff} * ct.avg_prior_revenue)
            ) THEN 1 ELSE 0 END                                                AS zombie_flag
        FROM general.entity_golden_records gr
        JOIN      fed_agg   fed  ON fed.bn_root  = gr.bn_root
        LEFT JOIN cra_agg   cra  ON cra.bn_root  = gr.bn_root
        LEFT JOIN cra_trend  ct  ON ct.bn_root   = gr.bn_root
        LEFT JOIN comp_agg  comp ON comp.bn_root = gr.bn_root
        WHERE fed.fed_total >= {min_fed}
          -- Exclude entities that are clearly not zombie candidates
          AND gr.entity_type IS DISTINCT FROM 'government'
          AND gr.canonical_name NOT ILIKE 'government of %'
          AND gr.canonical_name NOT ILIKE 'province of %'
          AND gr.canonical_name NOT ILIKE 'minister of %'
          AND gr.canonical_name NOT ILIKE 'ministry of %'
          AND gr.canonical_name NOT ILIKE 'university of %'
          AND gr.canonical_name NOT ILIKE '% university'
          AND gr.canonical_name NOT ILIKE '% université'
          AND gr.canonical_name NOT ILIKE '% school board'
          AND gr.canonical_name NOT ILIKE '% school district%'
          AND gr.canonical_name NOT ILIKE 'city of %'
          AND gr.canonical_name NOT ILIKE 'town of %'
          AND gr.canonical_name NOT ILIKE 'municipality of %'
          AND gr.canonical_name NOT ILIKE '% health authority%'
          AND gr.canonical_name NOT ILIKE '% regional district%'
          AND (
              (cra.last_cra_filing IS NOT NULL AND cra.last_cra_filing < '{cutoff_date}')
              OR (cra.last_cra_filing >= fed.last_grant_date
                  AND cra.last_cra_filing <= fed.last_grant_date + INTERVAL '{window_days} days')
              OR COALESCE(cra.avg_gov_dependency, 0) >= {threshold}
              OR cra.bn_root IS NULL
              OR (cra.bn_root IS NOT NULL AND COALESCE(cra.total_private_donations, 0) = 0)
              OR (cra.bn_root IS NOT NULL AND COALESCE(cra.total_program_spend, 0) = 0)
              OR (COALESCE(comp.total_compensation, 0) > COALESCE(cra.total_program_spend, 0)
                  AND COALESCE(comp.total_compensation, 0) > 0)
              OR fed.fed_total > COALESCE(cra.total_program_spend, 0)
              OR (cra.first_cra_filing IS NOT NULL
                  AND fed.first_grant_date <= cra.first_cra_filing + INTERVAL '{young_days} days')
              OR (ct.avg_prior_revenue > 0
                  AND ct.last_year_revenue < {cliff} * ct.avg_prior_revenue)
          )
        ORDER BY fed.fed_total DESC
    """
    return query(sql)


def fetch_way2_feature_table(
    min_fed_total: float = 0,
    gov_dependency_threshold: float = 0.70,
    revenue_cliff_threshold: float = 0.50,
    ceased_cutoff_year: int = 2023,
    filing_window_days: int = 365,
    young_org_years: int = 2,
) -> pd.DataFrame:
    """
    Full entity feature table for Way 2 unsupervised anomaly detection.
    Returns ALL active non-government FED recipients (not filtered by zombie flags),
    with the same 10 Way 1 flags embedded as domain knowledge columns.

    Difference from fetch_zombie_heuristics:
      - No WHERE filter removing entities that failed all rules
      - Adds avg_admin_ratio, total_expenses, transfers_out_total, revenue_cliff_ratio
      - Includes transfers_agg CTE for pass-through detection
    """
    threshold   = max(0.0, min(1.0, float(gov_dependency_threshold)))
    min_fed     = max(0.0, float(min_fed_total))
    cliff       = max(0.0, min(1.0, float(revenue_cliff_threshold)))
    cutoff_year = max(2018, min(2024, int(ceased_cutoff_year)))
    cutoff_date = f"{cutoff_year}-01-01"
    window_days = max(30, min(1825, int(filing_window_days)))
    young_days  = max(365, min(3650, int(young_org_years) * 365))

    sql = f"""
        WITH fed_agg AS (
            SELECT
                LEFT(recipient_business_number, 9)      AS bn_root,
                SUM(COALESCE(agreement_value, 0))       AS fed_total,
                COUNT(*)                                AS fed_agreement_count,
                MIN(agreement_start_date::date)         AS first_grant_date,
                MAX(agreement_start_date::date)         AS last_grant_date
            FROM fed.grants_contributions
            WHERE recipient_business_number IS NOT NULL
              AND LENGTH(TRIM(recipient_business_number)) >= 9
            GROUP BY LEFT(recipient_business_number, 9)
        ),
        cra_agg AS (
            SELECT
                LEFT(bn, 9)                             AS bn_root,
                MIN(fpe::date)                          AS first_cra_filing,
                MAX(fpe::date)                          AS last_cra_filing,
                COUNT(DISTINCT fpe)                     AS cra_years,
                AVG(
                    CASE
                        WHEN COALESCE(field_4540,0)+COALESCE(field_4550,0)+COALESCE(field_4560,0) > 0
                        THEN (COALESCE(field_4540,0)+COALESCE(field_4550,0)+COALESCE(field_4560,0))
                             / NULLIF(COALESCE(field_4700,0), 0)
                        ELSE COALESCE(field_4570,0) / NULLIF(COALESCE(field_4700,0), 0)
                    END
                )                                       AS avg_gov_dependency,
                AVG(COALESCE(field_4120, 0) / NULLIF(COALESCE(field_4950, 0), 0)) AS avg_program_ratio,
                AVG(COALESCE(field_4100, 0) / NULLIF(COALESCE(field_4950, 0), 0)) AS avg_admin_ratio,
                SUM(COALESCE(field_4700, 0))            AS total_revenue,
                SUM(COALESCE(field_4500, 0)
                  + COALESCE(field_4530, 0))            AS total_private_donations,
                SUM(COALESCE(field_4120, 0))            AS total_program_spend,
                SUM(COALESCE(field_4950, 0))            AS total_expenses
            FROM cra.cra_financial_details
            GROUP BY LEFT(bn, 9)
        ),
        cra_trend AS (
            SELECT
                bn_root,
                MAX(CASE WHEN fpe = max_fpe THEN revenue END) AS last_year_revenue,
                AVG(CASE WHEN fpe < max_fpe  THEN revenue END) AS avg_prior_revenue
            FROM (
                SELECT
                    LEFT(bn, 9)                                         AS bn_root,
                    fpe,
                    COALESCE(field_4700, 0)                             AS revenue,
                    MAX(fpe) OVER (PARTITION BY LEFT(bn, 9))            AS max_fpe
                FROM cra.cra_financial_details
            ) t
            GROUP BY bn_root
        ),
        comp_agg AS (
            SELECT
                LEFT(bn, 9)                             AS bn_root,
                SUM(COALESCE(field_300, 0))             AS total_employees,
                SUM(COALESCE(field_390, 0))             AS total_compensation
            FROM cra.cra_compensation
            GROUP BY LEFT(bn, 9)
        ),
        transfers_agg AS (
            SELECT
                LEFT(bn, 9)                             AS bn_root,
                SUM(COALESCE(total_gifts, 0))           AS transfers_out_total
            FROM cra.cra_qualified_donees
            GROUP BY LEFT(bn, 9)
        )
        SELECT
            gr.canonical_name,
            gr.bn_root,
            gr.entity_type,
            gr.status,
            gr.dataset_sources,
            COALESCE(gr.cra_profile->>'city',     gr.fed_profile->>'city')     AS city,
            COALESCE(gr.cra_profile->>'province', gr.fed_profile->>'province') AS province,
            -- FED metrics
            ROUND(fed.fed_total::numeric, 2)                                   AS fed_total,
            fed.fed_agreement_count,
            fed.first_grant_date,
            fed.last_grant_date,
            -- CRA metrics
            cra.first_cra_filing,
            cra.last_cra_filing,
            COALESCE(cra.cra_years, 0)                                         AS cra_years,
            ROUND(COALESCE(cra.avg_gov_dependency, 0)::numeric, 3)             AS avg_gov_dependency,
            ROUND(COALESCE(cra.avg_program_ratio, 0)::numeric, 3)              AS avg_program_ratio,
            ROUND(COALESCE(cra.avg_admin_ratio, 0)::numeric, 3)                AS avg_admin_ratio,
            ROUND(COALESCE(cra.total_revenue, 0)::numeric, 2)                  AS total_revenue,
            ROUND(COALESCE(cra.total_program_spend, 0)::numeric, 2)            AS total_program_spend,
            ROUND(COALESCE(cra.total_expenses, 0)::numeric, 2)                 AS total_expenses,
            ROUND((fed.fed_total - COALESCE(cra.total_program_spend, 0))::numeric, 2) AS funding_gap,
            -- Compensation
            COALESCE(comp.total_employees, 0)                                  AS total_employees,
            COALESCE(comp.total_compensation, 0)                               AS total_compensation,
            -- Transfers
            COALESCE(transfers.transfers_out_total, 0)                         AS transfers_out_total,
            -- Revenue cliff ratio (last year vs prior average; NULL if no trend data)
            CASE WHEN ct.avg_prior_revenue > 0
                 THEN ROUND((ct.last_year_revenue / ct.avg_prior_revenue)::numeric, 3)
                 ELSE NULL END                                                  AS revenue_cliff_ratio,
            -- Way 1 domain knowledge flags
            CASE WHEN cra.last_cra_filing IS NOT NULL
                  AND cra.last_cra_filing < '{cutoff_date}'
                 THEN true ELSE false END                                       AS flag_ceased,
            CASE WHEN cra.last_cra_filing >= fed.last_grant_date
                  AND cra.last_cra_filing <= fed.last_grant_date + INTERVAL '{window_days} days'
                 THEN true ELSE false END                                       AS flag_stopped_within_12mo,
            CASE WHEN COALESCE(cra.avg_gov_dependency, 0) >= {threshold}
                 THEN true ELSE false END                                       AS flag_high_gov_dependency,
            CASE WHEN cra.bn_root IS NULL
                 THEN true ELSE false END                                       AS flag_no_cra_record,
            CASE WHEN cra.bn_root IS NOT NULL
                  AND COALESCE(cra.total_private_donations, 0) = 0
                 THEN true ELSE false END                                       AS flag_zero_private_revenue,
            CASE WHEN cra.bn_root IS NOT NULL
                  AND COALESCE(cra.total_program_spend, 0) = 0
                 THEN true ELSE false END                                       AS flag_zero_program_spend,
            CASE WHEN COALESCE(comp.total_compensation, 0) > COALESCE(cra.total_program_spend, 0)
                  AND COALESCE(comp.total_compensation, 0) > 0
                 THEN true ELSE false END                                       AS flag_comp_exceeds_programs,
            CASE WHEN fed.fed_total > COALESCE(cra.total_program_spend, 0)
                 THEN true ELSE false END                                       AS flag_funding_gap,
            CASE WHEN cra.first_cra_filing IS NOT NULL
                  AND fed.first_grant_date <= cra.first_cra_filing + INTERVAL '{young_days} days'
                 THEN true ELSE false END                                       AS flag_young_org,
            CASE WHEN ct.avg_prior_revenue > 0
                  AND ct.last_year_revenue < {cliff} * ct.avg_prior_revenue
                 THEN true ELSE false END                                       AS flag_revenue_cliff
        FROM general.entity_golden_records gr
        JOIN      fed_agg       fed       ON fed.bn_root       = gr.bn_root
        LEFT JOIN cra_agg       cra       ON cra.bn_root       = gr.bn_root
        LEFT JOIN cra_trend     ct        ON ct.bn_root        = gr.bn_root
        LEFT JOIN comp_agg      comp      ON comp.bn_root      = gr.bn_root
        LEFT JOIN transfers_agg transfers ON transfers.bn_root  = gr.bn_root
        WHERE gr.status = 'active'
          AND fed.fed_total >= {min_fed}
          AND gr.entity_type IS DISTINCT FROM 'government'
          AND gr.canonical_name NOT ILIKE 'government of %'
          AND gr.canonical_name NOT ILIKE 'province of %'
          AND gr.canonical_name NOT ILIKE 'minister of %'
          AND gr.canonical_name NOT ILIKE 'ministry of %'
          AND gr.canonical_name NOT ILIKE 'university of %'
          AND gr.canonical_name NOT ILIKE '% university'
          AND gr.canonical_name NOT ILIKE '% université'
          AND gr.canonical_name NOT ILIKE '% school board'
          AND gr.canonical_name NOT ILIKE '% school district%'
          AND gr.canonical_name NOT ILIKE 'city of %'
          AND gr.canonical_name NOT ILIKE 'town of %'
          AND gr.canonical_name NOT ILIKE 'municipality of %'
          AND gr.canonical_name NOT ILIKE '% health authority%'
          AND gr.canonical_name NOT ILIKE '% regional district%'
    """
    return query(sql)


def fetch_portfolio_summary_table(min_fed_total: float = 0) -> pd.DataFrame:
    """
    Slim entity table for portfolio aggregation — groupby keys + 10 flag columns only.
    Skips ML feature columns (avg_admin_ratio, totals, etc.) that aren't needed for
    province/entity_type/funding_band groupby stats. Fixed thresholds (system baseline).
    """
    min_fed     = max(0.0, float(min_fed_total))
    threshold   = 0.70
    cliff       = 0.50
    cutoff_date = "2023-01-01"
    window_days = 365
    young_days  = 730

    sql = f"""
        WITH fed_agg AS (
            SELECT
                LEFT(recipient_business_number, 9)  AS bn_root,
                SUM(COALESCE(agreement_value, 0))   AS fed_total,
                MIN(agreement_start_date::date)     AS first_grant_date,
                MAX(agreement_start_date::date)     AS last_grant_date
            FROM fed.grants_contributions
            WHERE recipient_business_number IS NOT NULL
              AND LENGTH(TRIM(recipient_business_number)) >= 9
            GROUP BY LEFT(recipient_business_number, 9)
        ),
        cra_agg AS (
            SELECT
                LEFT(bn, 9)                             AS bn_root,
                MIN(fpe::date)                          AS first_cra_filing,
                MAX(fpe::date)                          AS last_cra_filing,
                AVG(
                    CASE
                        WHEN COALESCE(field_4540,0)+COALESCE(field_4550,0)+COALESCE(field_4560,0) > 0
                        THEN (COALESCE(field_4540,0)+COALESCE(field_4550,0)+COALESCE(field_4560,0))
                             / NULLIF(COALESCE(field_4700,0), 0)
                        ELSE COALESCE(field_4570,0) / NULLIF(COALESCE(field_4700,0), 0)
                    END
                )                                       AS avg_gov_dependency,
                AVG(COALESCE(field_4120, 0) / NULLIF(COALESCE(field_4950, 0), 0)) AS avg_program_ratio,
                SUM(COALESCE(field_4500, 0) + COALESCE(field_4530, 0)) AS total_private_donations,
                SUM(COALESCE(field_4120, 0))            AS total_program_spend
            FROM cra.cra_financial_details
            GROUP BY LEFT(bn, 9)
        ),
        cra_trend AS (
            SELECT
                bn_root,
                MAX(CASE WHEN fpe = max_fpe THEN revenue END) AS last_year_revenue,
                AVG(CASE WHEN fpe < max_fpe  THEN revenue END) AS avg_prior_revenue
            FROM (
                SELECT
                    LEFT(bn, 9)                                  AS bn_root,
                    fpe,
                    COALESCE(field_4700, 0)                      AS revenue,
                    MAX(fpe) OVER (PARTITION BY LEFT(bn, 9))     AS max_fpe
                FROM cra.cra_financial_details
            ) t
            GROUP BY bn_root
        ),
        comp_agg AS (
            SELECT
                LEFT(bn, 9)                    AS bn_root,
                SUM(COALESCE(field_390, 0))    AS total_compensation
            FROM cra.cra_compensation
            GROUP BY LEFT(bn, 9)
        )
        SELECT
            gr.canonical_name,
            gr.bn_root,
            gr.entity_type,
            gr.status,
            COALESCE(gr.cra_profile->>'province', gr.fed_profile->>'province') AS province,
            ROUND(fed.fed_total::numeric, 2)                                   AS fed_total,
            ROUND((fed.fed_total - COALESCE(cra.total_program_spend, 0))::numeric, 2) AS funding_gap,
            ROUND(COALESCE(cra.avg_gov_dependency, 0)::numeric, 3)             AS avg_gov_dependency,
            ROUND(COALESCE(cra.avg_program_ratio, 0)::numeric, 3)              AS avg_program_ratio,
            cra.last_cra_filing,
            CASE WHEN cra.last_cra_filing IS NOT NULL
                  AND cra.last_cra_filing < '{cutoff_date}'
                 THEN true ELSE false END                                       AS flag_ceased,
            CASE WHEN cra.last_cra_filing >= fed.last_grant_date
                  AND cra.last_cra_filing <= fed.last_grant_date + INTERVAL '{window_days} days'
                 THEN true ELSE false END                                       AS flag_stopped_within_12mo,
            CASE WHEN COALESCE(cra.avg_gov_dependency, 0) >= {threshold}
                 THEN true ELSE false END                                       AS flag_high_gov_dependency,
            CASE WHEN cra.bn_root IS NULL
                 THEN true ELSE false END                                       AS flag_no_cra_record,
            CASE WHEN cra.bn_root IS NOT NULL
                  AND COALESCE(cra.total_private_donations, 0) = 0
                 THEN true ELSE false END                                       AS flag_zero_private_revenue,
            CASE WHEN cra.bn_root IS NOT NULL
                  AND COALESCE(cra.total_program_spend, 0) = 0
                 THEN true ELSE false END                                       AS flag_zero_program_spend,
            CASE WHEN COALESCE(comp.total_compensation, 0) > COALESCE(cra.total_program_spend, 0)
                  AND COALESCE(comp.total_compensation, 0) > 0
                 THEN true ELSE false END                                       AS flag_comp_exceeds_programs,
            CASE WHEN fed.fed_total > COALESCE(cra.total_program_spend, 0)
                 THEN true ELSE false END                                       AS flag_funding_gap,
            CASE WHEN cra.first_cra_filing IS NOT NULL
                  AND fed.first_grant_date <= cra.first_cra_filing + INTERVAL '{young_days} days'
                 THEN true ELSE false END                                       AS flag_young_org,
            CASE WHEN ct.avg_prior_revenue > 0
                  AND ct.last_year_revenue < {cliff} * ct.avg_prior_revenue
                 THEN true ELSE false END                                       AS flag_revenue_cliff
        FROM general.entity_golden_records gr
        JOIN      fed_agg  fed  ON fed.bn_root  = gr.bn_root
        LEFT JOIN cra_agg  cra  ON cra.bn_root  = gr.bn_root
        LEFT JOIN cra_trend ct  ON ct.bn_root   = gr.bn_root
        LEFT JOIN comp_agg comp ON comp.bn_root = gr.bn_root
        WHERE gr.status = 'active'
          AND fed.fed_total >= {min_fed}
          AND gr.entity_type IS DISTINCT FROM 'government'
          AND gr.canonical_name NOT ILIKE 'government of %'
          AND gr.canonical_name NOT ILIKE 'province of %'
          AND gr.canonical_name NOT ILIKE 'minister of %'
          AND gr.canonical_name NOT ILIKE 'ministry of %'
          AND gr.canonical_name NOT ILIKE 'university of %'
          AND gr.canonical_name NOT ILIKE '% university'
          AND gr.canonical_name NOT ILIKE '% université'
          AND gr.canonical_name NOT ILIKE '% school board'
          AND gr.canonical_name NOT ILIKE '% school district%'
          AND gr.canonical_name NOT ILIKE 'city of %'
          AND gr.canonical_name NOT ILIKE 'town of %'
          AND gr.canonical_name NOT ILIKE 'municipality of %'
          AND gr.canonical_name NOT ILIKE '% health authority%'
          AND gr.canonical_name NOT ILIKE '% regional district%'
    """
    return query(sql)


def fetch_ghost_training_cohort(limit: int = 2000) -> pd.DataFrame:
    """
    Random sample of CRA-registered orgs that also received FED grants,
    with pre-aggregated financial ratios. Used to train the Isolation Forest
    so "outlier" means unusual among government-funded charities specifically.
    """
    sql = """
        SELECT
            fd.bn,
            AVG(COALESCE(fd.field_4120, 0)
                / NULLIF(COALESCE(fd.field_4950, 0), 0))   AS avg_program_ratio,
            AVG(
                CASE
                    WHEN COALESCE(fd.field_4540,0)+COALESCE(fd.field_4550,0)+COALESCE(fd.field_4560,0) > 0
                    THEN (COALESCE(fd.field_4540,0)+COALESCE(fd.field_4550,0)+COALESCE(fd.field_4560,0))
                         / NULLIF(COALESCE(fd.field_4700,0), 0)
                    ELSE COALESCE(fd.field_4570,0) / NULLIF(COALESCE(fd.field_4700,0), 0)
                END
            )                                               AS avg_gov_dependency,
            AVG(COALESCE(fd.field_4100, 0)
                / NULLIF(COALESCE(fd.field_4950, 0), 0))   AS avg_admin_ratio,
            COUNT(DISTINCT fd.fpe)                          AS years_reported,
            SUM(fc.total_grants)                            AS total_fed_grants
        FROM cra.cra_financial_details fd
        JOIN (
            SELECT recipient_business_number AS bn,
                   SUM(agreement_value)      AS total_grants
            FROM fed.grants_contributions
            WHERE recipient_business_number IS NOT NULL
            GROUP BY recipient_business_number
        ) fc ON fc.bn = fd.bn
        GROUP BY fd.bn
        HAVING COUNT(DISTINCT fd.fpe) >= 2
        ORDER BY RANDOM()
        LIMIT %(limit)s
    """
    return query(sql, {"limit": limit})


# ─── Department-level risk aggregation ─────────────────────────────────────────

def fetch_department_stats() -> pd.DataFrame:
    """
    Aggregates risk indicators by federal department.
    Each recipient entity is flagged as risky if:
      - No CRA record found, OR
      - Last CRA filing is before 2023-01-01, OR
      - Average gov dependency >= 0.70, OR
      - Total program spend = 0

    Excludes governments, universities, cities and similar entities.
    Returns departments with >= 5 distinct recipients, ordered by risk_rate desc,
    then total_funding desc. Limit 50.

    Columns returned: department, total_recipients, total_funding,
                      risky_count, risk_rate, avg_gov_dependency, avg_program_ratio
    """
    sql = f"""
        WITH fed_agg AS (
            SELECT
                gc.owner_org_title                              AS department,
                LEFT(gc.recipient_business_number, 9)          AS bn_root,
                SUM(gc.agreement_value)                        AS fed_total
            FROM fed.grants_contributions gc
            WHERE gc.recipient_business_number IS NOT NULL
              AND LENGTH(TRIM(gc.recipient_business_number)) >= 9
            GROUP BY gc.owner_org_title, LEFT(gc.recipient_business_number, 9)
        ),
        cra_agg AS (
            SELECT
                LEFT(fd.bn, 9)                                          AS bn_root,
                AVG(
                    CASE
                        WHEN COALESCE(fd.field_4540,0)+COALESCE(fd.field_4550,0)+COALESCE(fd.field_4560,0) > 0
                        THEN (COALESCE(fd.field_4540,0)+COALESCE(fd.field_4550,0)+COALESCE(fd.field_4560,0))
                             / NULLIF(COALESCE(fd.field_4700,0), 0)
                        ELSE COALESCE(fd.field_4570,0) / NULLIF(COALESCE(fd.field_4700,0), 0)
                    END
                )                                                       AS avg_gov_dependency,
                AVG(
                    COALESCE(fd.field_4120, 0)
                    / NULLIF(COALESCE(fd.field_4950, 0), 0)
                )                                                       AS avg_program_ratio,
                MAX(fd.fpe)                                             AS last_cra_filing,
                SUM(COALESCE(fd.field_4120, 0))                        AS total_program_spend
            FROM cra.cra_financial_details fd
            GROUP BY LEFT(fd.bn, 9)
        ),
        entity_risk AS (
            SELECT
                fa.department,
                fa.bn_root,
                fa.fed_total,
                cra.avg_gov_dependency,
                cra.avg_program_ratio,
                CASE
                    WHEN cra.bn_root IS NULL
                      OR cra.last_cra_filing < '2023-01-01'
                      OR COALESCE(cra.avg_gov_dependency, 0) >= 0.70
                      OR COALESCE(cra.total_program_spend, 0) = 0
                    THEN 1 ELSE 0
                END                                                     AS is_risky
            FROM fed_agg fa
            JOIN general.entity_golden_records gr ON gr.bn_root = fa.bn_root
            LEFT JOIN cra_agg cra ON cra.bn_root = fa.bn_root
            WHERE gr.status = 'active'
              AND gr.entity_type IS DISTINCT FROM 'government'
              AND gr.canonical_name NOT ILIKE 'government of %'
              AND gr.canonical_name NOT ILIKE 'province of %'
              AND gr.canonical_name NOT ILIKE 'minister of %'
              AND gr.canonical_name NOT ILIKE 'ministry of %'
              AND gr.canonical_name NOT ILIKE 'university of %'
              AND gr.canonical_name NOT ILIKE '% university'
              AND gr.canonical_name NOT ILIKE '% université'
              AND gr.canonical_name NOT ILIKE '% school board'
              AND gr.canonical_name NOT ILIKE '% school district%'
              AND gr.canonical_name NOT ILIKE 'city of %'
              AND gr.canonical_name NOT ILIKE 'town of %'
              AND gr.canonical_name NOT ILIKE 'municipality of %'
              AND gr.canonical_name NOT ILIKE '% health authority%'
              AND gr.canonical_name NOT ILIKE '% regional district%'
        )
        SELECT
            department,
            COUNT(DISTINCT bn_root)                     AS total_recipients,
            SUM(fed_total)                              AS total_funding,
            SUM(is_risky)                               AS risky_count,
            ROUND(SUM(is_risky)::numeric / NULLIF(COUNT(DISTINCT bn_root), 0), 4)
                                                        AS risk_rate,
            ROUND(AVG(avg_gov_dependency)::numeric, 4)  AS avg_gov_dependency,
            ROUND(AVG(avg_program_ratio)::numeric, 4)   AS avg_program_ratio
        FROM entity_risk
        GROUP BY department
        HAVING COUNT(DISTINCT bn_root) >= 5
        ORDER BY risk_rate DESC, total_funding DESC
        LIMIT 50
    """
    return query(sql)
