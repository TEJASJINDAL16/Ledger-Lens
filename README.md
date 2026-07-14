# 💳 LedgerLens

**LedgerLens** is an end-to-end data engineering pipeline and analytics dashboard designed to solve the "Merchant Fragmentation" problem in payment processing data. 

It takes raw, noisy, highly-corrupted transaction logs and passes them through a strict Bronze/Silver/Gold architecture, resolving messy descriptors (e.g., `SQ *BLUE BOTL COF 4471 NY`) into canonical merchant identities using a 5-tier fuzzy matching and clustering algorithm.

## 🚀 Quickstart

Ensure you have Python 3.10+ installed and a virtual environment activated.

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the entire pipeline (Generates Data -> Bronze -> Silver -> Gold)
make all

# 3. Launch the Streamlit Dashboard
make dashboard
```

## 🏗 Architecture

The pipeline follows a strict Medallion architecture:

1. **Generation (`src/generate/`):** Generates 250,000 realistic Amex transactions, deliberately injecting 14 specific classes of data corruption (sentinel nulls, parens negatives, trailing store numbers).
2. **Bronze (`src/run_bronze.py`):** Ingestion gate. Casts all columns to strings. Enforces schema via Pandera. Impossible dates and schema drifts are quarantined, never silently dropped.
3. **Silver (`src/run_silver.py`):** The heavy lifting.
   - Parses dates (5 formats) and amounts (stripping symbols).
   - Replaces sentinel strings (`"NA"`, `"-"`) with true nulls.
   - Executes the **5-Tier Merchant Resolver** (Regex → Exact → Fuzzy → DBSCAN Cluster → Unresolved).
   - Imputes missing MCCs based on historical merchant modes.
   - Flags extreme outliers (MAD Z-scores) and near-duplicates (120-second windows).
4. **Gold (`src/load_warehouse.py`):** Loads the clean `silver.parquet` into a **DuckDB** embedded warehouse. Models it into a Star Schema (`dim_merchant`, `fct_transactions`) and builds 4 analytical views.
5. **Presentation (`app/dashboard.py`):** A beautiful, high-contrast Streamlit dashboard exposing the ROI of the pipeline.

## 📚 Documentation

For deep-dives into the product rationale, architecture, and data contracts, see:
* [Product Requirements Document (PRD)](docs/PRD.md)
* [Data Dictionary](docs/DATA_DICTIONARY.md)
* [Architectural Decisions Log](docs/DECISIONS.md)
