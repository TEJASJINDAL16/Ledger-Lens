# Product Requirements Document (PRD): LedgerLens

## 1. Problem Statement
Financial institutions receive transaction logs from thousands of different upstream payment gateways and point-of-sale terminals. These systems truncate, abbreviate, and append random characters (store numbers, POS IDs) to the merchant name. 
For example, `UBER EATS`, `UBER EATS 123`, and `UBR* EATS AMSTERDAM` are all the same merchant, but traditional SQL `GROUP BY` statements treat them as distinct entities. This fragmentation makes it impossible to accurately answer simple business questions like, "What were our top 10 merchants by spend last month?"

Furthermore, raw data contains impossible dates (e.g., `2024-02-30`), negative amounts trapped in parenthesis `(12.50)`, sentinel nulls disguised as strings (`"NA"`, `"-"`), and missing Merchant Category Codes (MCC).

## 2. Solution Overview
**LedgerLens** is a batch data engineering pipeline designed to ingest, validate, clean, and resolve these transactions into a pristine Star Schema.

### 2.1 Core Objectives
1. **Zero Silent Drops:** Bad data must be quarantined and logged, never silently discarded.
2. **Merchant Resolution:** Condense heavily fragmented raw descriptor strings into canonical merchant identities with an F1 score > 0.85.
3. **Data Imputation:** Intelligently infer missing MCCs based on the resolved merchant's historical behavior.
4. **Honest Analytics:** Expose the exact ROI of the pipeline by comparing the analytical views "Before" and "After" cleaning.

## 3. Key Features
- **5-Tier Merchant Resolver:** A cascading algorithm that balances precision and recall:
  - *Tier 0:* Regex Normalization (stripping state codes, store numbers, aggregator prefixes).
  - *Tier 1:* Exact Dictionary Match.
  - *Tier 2:* Fuzzy Match (RapidFuzz Jaro-Winkler) against the dictionary.
  - *Tier 3:* Unsupervised Clustering (TF-IDF + DBSCAN) to discover new merchants not in the dictionary.
  - *Tier 4:* Unresolved (fallback).
- **Embedded Warehouse:** Uses DuckDB to build a Star Schema locally without external dependencies.
- **Visual Dashboard:** A Streamlit app providing stakeholders with Data Health metrics, a Merchant Dictionary lookup, and ROI Insights.

## 4. Non-Functional Requirements
- **Performance:** The pipeline must process 250,000 rows in under 2 minutes on a standard laptop.
- **Reproducibility:** A single `make all` command must execute the entire pipeline end-to-end.
- **Safety:** Original monetary values and currencies must be preserved in the final fact table alongside their converted/cleaned counterparts.
