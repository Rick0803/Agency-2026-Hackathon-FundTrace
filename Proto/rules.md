# Zombie Recipient Detection Rules

Rules used in Way 1 of the Fetch page to flag organizations that received public funding
but show signs of having ceased operations or never meaningfully delivered on that funding.

Any entity triggering **at least one rule** is included in the flagged results.

---

## R1 — Gone Dark

**Flag:** `flag_ceased`

The organization's last CRA T3010 filing occurred before the cutoff year, indicating it has
gone dark and is no longer actively reporting to the CRA.

| Parameter | Default | Range | Description |
|---|---|---|---|
| Cutoff year | 2023 | 2020 – 2024 | Flag entities whose last CRA filing was before January 1 of this year |

---

## R2 — Stopped Filing Shortly After Last Grant

**Flag:** `flag_stopped_within_12mo`

The organization's last CRA filing falls within a short window after its last federal grant,
suggesting it may have dissolved once funding stopped.

| Parameter | Default | Range | Description |
|---|---|---|---|
| Filing window | 12 months | 1 – 36 months | Flag entities whose last CRA filing was within this many months after their last federal grant |

---

## R3 — High Government Dependency

**Flag:** `flag_high_gov_dependency`

The organization's average government revenue share across all filing years is at or above the
threshold. Entities almost entirely reliant on government funding have no independent revenue base.

| Parameter | Default | Range | Description |
|---|---|---|---|
| Gov dependency threshold | 70% | 0 – 100% | Flag entities whose average government revenue share meets or exceeds this level |

---

## R4 — No CRA Record

**Flag:** `flag_no_cra_record`

The organization received federal grants but has zero CRA T3010 filings. It is completely
unverifiable — there is no charity registration, no financial disclosure, and no program reporting.

*No tunable parameters. This rule is binary.*

---

## R5 — Zero Private Revenue

**Flag:** `flag_zero_private_revenue`

The organization has never reported any private donations or earned income across any filing year.
It is 100% reliant on government funding with no demonstrated ability to attract independent support.

*No tunable parameters. This rule is binary.*

---

## R6 — Zero Program Spend

**Flag:** `flag_zero_program_spend`

The organization has reported zero charitable program expenditure across all filing years despite
receiving public funding. No money is reaching the programs it was funded to deliver.

*No tunable parameters. This rule is binary.*

---

## R7 — Compensation Exceeds Program Spend

**Flag:** `flag_comp_exceeds_programs`

Total compensation paid out to staff exceeds total spending on charitable programs. The organization
is spending more on itself than on its stated mission.

*No tunable parameters. This rule is binary.*

---

## R8 — Funding Gap

**Flag:** `flag_funding_gap`

Total federal grants received exceed total CRA program spend. Public money came in but program
delivery does not account for it — a gap between inflow and verifiable output.

*No tunable parameters. This rule is binary.*

---

## R9 — Young Org, Early Grant

**Flag:** `flag_young_org`

The organization received its first federal grant within a short window of its first CRA filing,
meaning it had little or no track record when it was awarded public funding.

| Parameter | Default | Range | Description |
|---|---|---|---|
| Track record window | 2 years | 1 – 5 years | Flag entities whose first federal grant arrived within this many years of their first CRA filing |

---

## R10 — Revenue Cliff

**Flag:** `flag_revenue_cliff`

Revenue in the organization's final filing year dropped below a threshold percentage of its
prior average, indicating a visible collapse in financial activity.

| Parameter | Default | Range | Description |
|---|---|---|---|
| Revenue cliff drop | 50% | 10 – 90% | Flag entities whose final year revenue fell below this percentage of their prior average |

---

## Global Filter

| Parameter | Default | Description |
|---|---|---|
| Min federal funding | $0 | Only scan entities that received at least this much in total federal grants |

---

## Notes

- Rules R4–R8 are binary with no threshold to adjust — they fire based on whether a value is zero or exceeds another value.
- Rules R1, R2, R3, R9, R10 have tunable thresholds accessible via the "Adjust rule thresholds" expander on the Fetch page.
- Government bodies, universities, municipalities, school boards, health authorities, and regional districts are excluded from the scan by name and entity type.
- The CRA T3010 dataset only contains active filers — revocation status is not available in this dataset.
