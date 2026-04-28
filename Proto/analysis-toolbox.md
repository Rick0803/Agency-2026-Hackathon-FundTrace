# Analysis toolbox — suggested libraries

> **Note from the organizers:** This toolbox is a suggestive guide, not an endorsement. The libraries listed are provided as a convenience starting point — the organizers do not personally recommend or endorse any specific tool. Participants are free to use any libraries, frameworks, or approaches they prefer, including none of these.

Mature open-source libraries exist for most common analytical tasks on entity-level and transactional data. This document lists the canonical choice per problem family. **Reach for these before writing custom implementations.**

Everything listed here is MIT/Apache/BSD-licensed unless otherwise noted. All links are to the source repo on GitHub.

---

## Anomaly detection on tabular data

**PyOD** — https://github.com/yzhao062/pyod

60+ outlier detection algorithms (Isolation Forest, LOF, ECOD, COPOD, deep variants) under one scikit-learn-style API. The canonical choice for *"are there outliers in this table?"*.

**When not to use:** if the "anomaly" is a business rule (e.g. "amount > threshold"), a SQL query is the right tool.

---

## Entity resolution / record linkage

> **Already done for you:** The golden entity table (`general/data/entity-master.sqlite`) is already entity-matched across the core datasets. Feel free to use Splink if you're ingesting a new dataset it doesn't cover.

**Splink** — https://github.com/moj-analytical-services/splink

Probabilistic record linkage using Fellegi-Sunter models. Scales to millions of rows via DuckDB, Spark, or Athena backends. Standard choice for linking names across registries, filings, and transactions.

**When not to use:** if exact-match on a clean identifier works, use it. Probabilistic matching has false-positive cost.

---

## Graph construction and analysis

**NetworkX** — https://github.com/networkx/networkx

The default Python graph library. Cycles, connected components, shortest paths, centrality, basic community detection. Fine up to low hundreds of thousands of edges. Readable API, extensive algorithm coverage.

**python-louvain / leidenalg** — https://github.com/taynaud/python-louvain, https://github.com/vtraag/leidenalg

Community detection. Given a graph, both algorithms assign every node to a cluster by maximizing a modularity score. Output is a node → community-id mapping you can use to colour a graph, count clusters, or detect "this entity is closer to cluster A than expected." Louvain is the classic; **Leiden is stricter and generally preferred now** (fixes Louvain's known issue of producing disconnected-within-cluster groups, and corrects for the resolution limit). `python-louvain` plugs into NetworkX; `leidenalg` is built on `igraph`.

**PyGOD** — https://github.com/pygod-team/pygod

Graph anomaly detection — PyOD's graph sibling. Detects structurally unusual nodes and subgraphs using graph neural networks and classical methods. Reach for this on *"which nodes in this network look weird?"* rather than on specific-pattern queries (use NetworkX for those).

---

## Pattern mining and indicator libraries

**mlxtend** — https://github.com/rasbt/mlxtend

Association rule mining (Apriori, FP-Growth). Give it a list of "transactions" — each transaction is a set of items (e.g., set of vendors that appeared in one ministry's fiscal-year of spending) — and it tells you which item combinations co-occur more than random chance, with support/confidence/lift metrics. Useful for spotting "vendor X and vendor Y nearly always appear together" or "this set of expense categories is unusually tightly coupled."

---

## Change detection and time series

**ruptures** — https://github.com/deepcharles/ruptures

Change-point detection. Answers *"when did this series start behaving differently?"* — unit-cost shifts, volume changes, regime transitions. Several algorithms (Pelt, binary segmentation, window-based) under one API.

**For point anomalies in a time series** (individual spikes, rare values), PyOD's core detectors work fine on windowed features — reach for it the same way you would on tabular data. Different from ruptures: PyOD answers "is this point weird?" while ruptures answers "where does the whole regime change?" — use both if you care about both questions.

---

## Classical techniques

**benford_py** — https://github.com/milcent/benford_py

First-digit distribution (Benford's Law) analysis. Useful as a **flag to investigate further**, not as evidence on its own — Benford deviations have many benign explanations. Fast to run, low cost to include as part of a screening pass.

Install note: `pip install benford-py`, but the import name is `benford`.

---

## Cross-referencing and external data

**OpenSanctions** — https://github.com/opensanctions/opensanctions

Sanctions lists, politically-exposed persons (PEPs), and adverse entity registers in structured form. Standard first check before investing time into an entity of interest. **Access pattern:** the public REST match/search API requires a (free) API key as of 2026; the flat-file downloads at `data.opensanctions.org/datasets/latest/*/targets.simple.csv` are public and unauthenticated, which is usually easier for batch use. The default dataset is globally focused — for Canadian-only use cases the match rate on orgs is low; PEP coverage of Canadian individuals is better.

**OCCRP Aleph / OpenAleph** — https://github.com/alephdata/aleph, https://github.com/dataresearchcenter/openaleph

Investigative data platform (not a Python library) with corporate registries, leaks, company ownership graphs, and cross-referencing. Used either via the hosted public instance at `aleph.occrp.org` (search interface + limited API) or by self-hosting from the repo. Worth knowing about for entity enrichment when a name search on OpenSanctions comes up empty but the entity might show up in leaked databases or corporate filings.

---

## Data wrangling

**DuckDB** — https://github.com/duckdb/duckdb

Embedded analytics SQL on CSV, Parquet, or in-memory data. No server, no install beyond a pip or npm line. Useful when you want to pull a slice of the Postgres data to a local file and iterate on it, or join external data (sanctions lists, your own spreadsheets) against the core tables. Also the default backend for Splink.

---

## Quick decision guide

| You're asking... | Start here |
|------------------|-----------|
| Are there outliers in this table? | PyOD |
| Do these two records refer to the same entity? | Splink |
| Are there cycles / clusters / central nodes in this network? | NetworkX |
| Do any nodes in this graph look structurally weird? | PyGOD |
| When did this series start behaving differently? | ruptures |
| Which things co-occur more than chance? | mlxtend |
| Is this entity on a watchlist? | OpenSanctions |

---

## Principle

This toolbox is a starting point, not a recommendation. If one of these libraries fits your task, using it saves reimplementation and surfaces known gotchas. If your task is better served by custom code — including because you know the problem deeply and these libraries make the wrong tradeoffs — write the custom code.
