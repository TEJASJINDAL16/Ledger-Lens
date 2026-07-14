# Architectural Decisions Log

This document records the critical engineering, data safety, and product judgment calls made during the LedgerLens pipeline development. 
Governance is a feature, and all compromises or assumptions are explicitly documented here.

| # | Decision | Options considered | Chosen | Rationale | Risk accepted |
|---|---|---|---|---|---|
| 1 | Near-duplicate transactions | Drop / Flag / Merge | **Flag** | A second identical coffee 90s later is plausible. Dropping would understate merchant revenue and could suppress a genuine cardmember charge. | Downstream consumers must handle the flag; documented in data dictionary. |
| 2 | Extreme outliers (>3.5 MAD) | Drop / Winsorize / Flag | **Flag** | High-value spend is legitimate on corporate cards. Removing it biases merchant revenue ranking. | Aggregations are sensitive to real outliers; a `_excl_outliers` variant view is provided. |
| 3 | Missing MCC | Drop row / Impute / Leave null | **Impute from merchant mode + flag** | Preserves 25% of rows; the flag preserves honesty. | Imputation error propagates to category mix; quantified in scorecard. |
| 4 | Fuzzy threshold = 88 | 80 / 85 / 88 / 92 | **88** | F1 peak on ground-truth sweep. Below 85, distinct merchants collapse; above 92, recall craters. | Merchant-specific tuning would beat a global threshold; noted as future work. |
| 5 | Quarantine vs drop | Drop / Quarantine | **Quarantine** | Data destruction is irreversible and unauditable in a regulated context. | Storage cost; quarantine table must be triaged. |
| 6 | Database Engine | Postgres / SQLite / DuckDB | **DuckDB** | Embedded, columnar, perfectly suited for analytical OLAP workloads on a single node without external dependencies. | No concurrent multi-writer support (acceptable for this batch pipeline). |
| 7 | Profiling Fallback | ydata-profiling / pandas.describe | **pandas.describe (to HTML)** | `ydata-profiling` has strict numba dependencies that conflict with Python 3.14 on macOS. | Loss of some interactive histograms in the profiling step; velocity prioritized. |
| 8 | Tier 3 Unresolved Clustering | K-Means / DBSCAN / No Cluster | **DBSCAN** | Can find arbitrarily shaped clusters and properly identify noise (singletons), whereas K-Means forces all points into clusters. | O(n²) complexity on distinct descriptors; mitigated by only clustering unique unresolved strings. |
| 9 | Original Column Preservation | Overwrite / Add New Columns | **Add New Columns** | Strict Data Safety Rule: we never overwrite raw `amount` or `currency`, we create `amount_inr` and `currency_original`. | Slight increase in table width and storage size. |
| 10 | Sentinel Null Mapping | Leave as strings / Map to None/NaN | **Map to true nulls** | Prevents string 'NA' from being treated as a valid category or disrupting downstream aggregations. | Loss of the specific raw string (though it can be queried from the raw table). |
