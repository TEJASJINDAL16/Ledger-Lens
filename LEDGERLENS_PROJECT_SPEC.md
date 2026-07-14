# LedgerLens
### A Transaction Data Quality & Merchant Intelligence Pipeline
**Built as an application artifact for: American Express — Product Development Intern/Apprentice (Hybrid, Gurgaon/Bangalore)**

---

## 0. Read this first

This document is three things at once:

1. A **rationale** you can speak to in an interview (Section 1–2)
2. A **complete technical specification** (Sections 3–10)
3. An **agent-executable build plan** — hand Sections 11–12 to a coding agent (Claude Code, Cursor, etc.) and it can implement the repo end to end (Section 11–13)

Section 14 gives the resume bullets. Section 15 gives the metrics you will be able to *honestly* claim once you run it.

---

## 1. Why this project (the JD mapping)

The Amex JD is not a machine-learning JD. Read what it actually repeats:

| What the JD says | What it means |
|---|---|
| "Act as the **custodian for data standardization, data quality and data governance**" | They want someone who makes messy data trustworthy |
| "**billions of transactions** across the globe" | They want someone who thinks about scale, not accuracy on 10k rows |
| "Develop **data management, data integration and data quality processes**" | Pipelines, not notebooks |
| "**defining process SLAs and controls**" | Automated checks, thresholds, alerts |
| "rule authoring, testing, integration" | Deterministic business rules alongside ML |
| "A single decision affects millions of cardmembers — **it needs to be the right one**" | Auditability and documented judgment |
| "Ability to solve **unstructured problems**" | Ambiguity is the job |
| "translate business needs into remarkable **solutions**" | Ship something with a UI a stakeholder can use |

Amex allocates the selected candidate to one of three roles: **Product Management, Product Development, or Data Steward.** Almost every applicant builds a fraud classifier and competes for the first two. Almost nobody builds anything that speaks to **Data Steward** — which is a third of the odds.

**This project is deliberately aimed at the intersection of all three.** It is a data-quality and entity-resolution pipeline (Data Steward), delivered as a product with a PRD, a scorecard, and a stakeholder dashboard (Product Management), engineered as a modular, tested, config-driven pipeline (Product Development).

**The one-line pitch:**
> *"Raw card transactions arrive broken — merchant names are unreadable machine strings, dates are in five formats, and the same merchant is fragmented across dozens of raw spellings. I built a pipeline that repairs them, proves the repair with a measurable quality scorecard, and showed that cleaning didn't just tidy the data — it changed the business answer: the Top-10 merchant spend leaderboard was materially wrong before normalization."*

That last clause is the whole project. **Cleaning is not housekeeping; it changed the answer.**

---

## 2. What this project is (and is not)

### Is
A local, reproducible, end-to-end data pipeline that:
1. **Generates** a realistically messy synthetic card-transaction dataset (you own the corruption, so you can prove your fixes work)
2. **Profiles** it and quantifies the damage
3. **Validates** it at every stage with schema contracts, quarantining rows that fail
4. **Cleans** it — dates, amounts, currencies, geography, sentinel nulls
5. **Resolves merchant identity** — the core intellectual work: `SQ *BLUE BOTL COF 4471 NY` → `Blue Bottle Coffee` / MCC 5814 / Coffee Shop, with a confidence score and the method used
6. **De-duplicates** — separating true double-charges from genuine repeat purchases
7. **Loads** a clean analytical warehouse (DuckDB, star schema)
8. **Publishes** a before/after Data Quality Scorecard and 4 business insights on a Streamlit dashboard
9. **Documents every ambiguous judgment call** in a Decisions Log

### Is not
- Not a fraud model. Not a deep learning project. Not a Kaggle leaderboard chase.
- Not Spark/Kafka/cloud. It runs on your laptop in under two minutes.
- **Scale is addressed by design and by argument, not by infrastructure.** You will include a documented "How this scales to 8B rows" section. That is enough, and it is honest.

### Non-goals (state these in the README — scoping is a product skill)
- No real PII, no real card data
- No production deployment
- No currency FX time-series (a single static rate table, documented as a limitation)

---

## 3. Architecture

A **Medallion architecture** (Bronze → Silver → Gold). Say this phrase in the interview; it's the standard vocabulary in data platform teams and signals you know how real warehouses are laid out.

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          SOURCE (simulated)                              │
│  make_clean.py  ──►  corrupt.py  ──►  data/raw/transactions_raw.csv      │
│  (ground truth)      (12 injected      + merchants_seed.csv              │
│   kept aside          defect types)                                      │
│   for scoring)                                                           │
└────────────────────────────────┬─────────────────────────────────────────┘
                                 │
                    ┌────────────▼─────────────┐
                    │  BRONZE — ingest.py      │   Load as-is. All columns str.
                    │  + profile.py            │   Nothing dropped. Nothing fixed.
                    │  (ydata-profiling HTML)  │   Emits: profile_before.html
                    └────────────┬─────────────┘
                                 │
                    ┌────────────▼─────────────┐
                    │  GATE 1 — Pandera        │   Structural contract.
                    │  BronzeSchema            │   FAIL ──► data/quarantine/
                    └────────────┬─────────────┘   (never silently dropped)
                                 │
                    ┌────────────▼─────────────────────────────────────────┐
                    │  SILVER — clean/                                     │
                    │   • parse_dates.py       5 formats + epoch + nulls   │
                    │   • parse_amounts.py     ₹/$/commas/(negatives)      │
                    │   • normalize_currency   → INR base, static rates    │
                    │   • canonicalize_geo.py  GGN/Gurgaon/Gurugram → GGN  │
                    │   • sentinel_nulls.py    "NA"/"-"/-999 → true NULL   │
                    │                                                      │
                    │  RESOLVE — resolve/merchant_resolver.py  ★ CORE ★    │
                    │   Tier 1: regex strip  (aggregator prefixes, store   │
                    │           numbers, phone nums, URLs, trailing IDs)   │
                    │   Tier 2: exact match  → merchant_dictionary.csv     │
                    │   Tier 3: fuzzy match  → RapidFuzz token_set ≥ 88    │
                    │   Tier 4: cluster      → TF-IDF char(2,4) + cosine   │
                    │           unresolved strings grouped, rep chosen     │
                    │   Tier 5: MCC imputation from resolved merchant mode │
                    │   ► emits: merchant_id, name, mcc, category,         │
                    │            match_method, match_confidence            │
                    │                                                      │
                    │   • dedupe.py    exact-hash → drop+log               │
                    │                  near-dup (same acct/mcht/amt ≤120s) │
                    │                  → FLAG, DO NOT DROP                 │
                    │   • outliers.py  robust z (MAD) → FLAG, DO NOT DROP  │
                    └────────────┬─────────────────────────────────────────┘
                                 │
                    ┌────────────▼─────────────┐
                    │  GATE 2 — Pandera        │   Semantic contract.
                    │  SilverSchema            │   Typed, ranged, non-null.
                    └────────────┬─────────────┘
                                 │
                    ┌────────────▼─────────────────────────────────────────┐
                    │  GOLD — load_warehouse.py → DuckDB (star schema)     │
                    │   dim_merchant · dim_date · dim_account              │
                    │   fct_transactions                                   │
                    │   sql/03_insights.sql → 4 analytical views           │
                    └────────────┬─────────────────────────────────────────┘
                                 │
                ┌────────────────┼────────────────────┐
                │                │                    │
    ┌───────────▼──────┐  ┌──────▼──────────┐  ┌──────▼────────────┐
    │ scorecard.py     │  │ app/dashboard   │  │ docs/DECISIONS.md │
    │ before vs after  │  │ Streamlit, 4 tab│  │ every judgment    │
    │ + accuracy vs    │  │ stakeholder view│  │ call, justified   │
    │   ground truth   │  └─────────────────┘  └───────────────────┘
    └──────────────────┘
```

**Why ground truth matters:** because you generate the clean data *before* corrupting it, you can score your own resolver against the truth (precision/recall on merchant resolution, dedup F1). Almost no student project can do this. It converts "I cleaned the data" into "**my resolver achieves 96.4% precision on merchant identity, measured against held-out ground truth.**"

---

## 4. Tech stack

| Layer | Tool | Why it's here / what it signals |
|---|---|---|
| Language | **Python 3.11** | — |
| Dataframes | **Pandas** (core) + **Polars** (one benchmark script) | Polars benchmark = you care about performance |
| Synthetic data | **Faker** + custom `corrupt.py` | You wrote a *defect injector*. Strong line. |
| Profiling | **ydata-profiling** | You measure before you cut |
| Validation | **Pandera** (schema contracts) | **Data quality as code** — the single highest-signal tool here |
| Fuzzy matching | **RapidFuzz** | Entity resolution |
| Vectorization | **scikit-learn** (TfidfVectorizer, char n-grams, cosine, DBSCAN) | The "data science" surface, used where it's actually warranted |
| Warehouse | **DuckDB** | Analytical SQL, columnar, embedded — modern and interview-friendly |
| Transformation | **SQL** (`sql/*.sql`) | They *will* test SQL. Show it in the repo. |
| Orchestration | **Makefile** + `run_pipeline.py` (optional: **Prefect** flow) | It's a *pipeline*, not a notebook |
| Testing | **pytest** | Non-negotiable for "Product Development" |
| Config | **YAML** (`config/pipeline.yaml`) | No magic numbers in code — thresholds are tunable, i.e. *governable* |
| Logging | **structlog** or stdlib `logging` → `logs/run_*.log` | Auditability |
| Dashboard | **Streamlit** | Stakeholder-facing, one page, four tabs |
| Version control | **Git** + clean commit history + README | Professionalism |

**16 named technologies.** None of them require more than an evening. This is the point: maximum surface area, minimum intensity.

---

## 5. The data

### 5.1 Schema (raw / bronze — everything arrives as a string)

| Column | Description | Defects injected |
|---|---|---|
| `transaction_id` | UUID | occasional duplicates |
| `account_id` | e.g. `ACC-004821` | casing drift, whitespace |
| `txn_timestamp` | Event time | **5 formats + epoch ints + nulls + 2 impossible dates** |
| `amount` | Transaction value | `"₹1,240.00"`, `"$18.99"`, `"(45.00)"`, `"1240"`, `" 1,240.00 "` |
| `currency` | INR / USD | missing on ~15% (must be inferred from symbol or country) |
| `merchant_descriptor` | **The raw machine string** | see 5.2 — this is the heart of the project |
| `mcc` | Merchant Category Code | **missing on ~25%**, some as `"0000"`, some as `"NA"` |
| `city` | | `Gurgaon` / `Gurugram` / `GGN` / `gurgaon ` / `GURGAON` |
| `country` | | `IN` / `India` / `IND` / `in` |
| `channel` | POS / ONLINE / ATM | casing drift, `"e-comm"` vs `"ONLINE"` |
| `status` | APPROVED / DECLINED / REVERSED | sentinel `"-"` for missing |

**Volume:** 250,000 rows. Big enough to be non-trivial and to make a Pandas-vs-Polars benchmark meaningful; small enough to run on a laptop in seconds.

### 5.2 The merchant descriptor corruption spec (the core challenge)

Real card descriptors are polluted by payment aggregators, terminal IDs, and truncation. Your generator must reproduce this. Given a clean merchant `Blue Bottle Coffee`, emit variants like:

```
SQ *BLUE BOTL COF 4471 NY      ← Square prefix + truncation + store# + state
TST* BLUE BOTTLE - GURGAON     ← Toast prefix + location suffix
PAYPAL *BLUEBOTTLE             ← aggregator prefix + concatenation
BLUE BOTTLE COFFEE  #0231      ← store number
BLUEBOTTLECOFFEE.COM           ← URL form
BLUE BOTTLE COFF               ← hard truncation at 15 chars
blue bottle coffee gurgaon     ← lowercase + city appended
BLUE BOTTLE COFFEE 8001234567  ← phone number appended
```

**Corruption transforms to implement** (apply 1–3 randomly per row):
`AGGREGATOR_PREFIX` · `TRUNCATE(n)` · `UPPERCASE` · `LOWERCASE` · `REMOVE_VOWELS_IN_LONG_WORDS` · `APPEND_STORE_NUM` · `APPEND_PHONE` · `APPEND_CITY` · `APPEND_STATE_CODE` · `COLLAPSE_SPACES` · `URL_FORM` · `INJECT_UNICODE_JUNK`

### 5.3 The 12 defect classes (your generator injects, your pipeline catches)

| # | Defect | Injection rate | Handled by |
|---|---|---|---|
| 1 | Date format chaos | 100% (5 formats mixed) | `parse_dates.py` |
| 2 | Impossible dates (future, year 1900) | 0.1% | Gate 1 → quarantine |
| 3 | Amount as dirty string | 100% | `parse_amounts.py` |
| 4 | Negative-in-parentheses | 2% | `parse_amounts.py` |
| 5 | Mixed currency, no conversion | 12% USD | `normalize_currency.py` |
| 6 | Missing currency | 15% | infer from symbol/country; else quarantine |
| 7 | Merchant descriptor noise | 100% | **`merchant_resolver.py`** |
| 8 | Missing MCC | 25% | imputed from resolved merchant mode |
| 9 | City variant explosion | 100% | `canonicalize_geo.py` |
| 10 | Sentinel nulls (`NA`,`N/A`,`-`,`NULL`,`-999`,`""`) | 8% | `sentinel_nulls.py` |
| 11 | Exact duplicate rows | 1.0% | `dedupe.py` → drop + log |
| 12 | Near-duplicates (≤120s, same acct/merchant/amount) | 1.5% | `dedupe.py` → **flag, don't drop** |
| 13 | Extreme outliers (100× amount) | 0.2% | `outliers.py` → **flag, don't drop** |
| 14 | Schema drift (extra delimiter shifts columns) | 0.05% | Gate 1 → quarantine |

> **The most important design decision in this project:** #12 and #13 are **flagged, not dropped.** A near-duplicate might be a genuine second coffee. A ₹40 lakh transaction might be a real corporate card charge. Silently deleting them would bias every downstream revenue number. *Quarantine and flag; never destroy.* This single paragraph, said out loud in an interview, is worth more than any model.

---

## 6. The merchant resolver (detailed algorithm)

This is the intellectual core. Implement as a **cascading 5-tier resolver**, each tier attaching a `match_method` and `match_confidence`.

```
INPUT: raw merchant_descriptor (string)

TIER 0 — NORMALIZE
  uppercase → strip unicode junk → collapse whitespace
  strip aggregator prefixes:  regex ^(SQ|TST|PAYPAL|PP|SP|GOOGLE|APL)\s*\*+\s*
  strip trailing store nums:  regex [#]?\s*\d{3,6}\s*$
  strip phone numbers:        regex \b\d{10}\b
  strip URL suffixes:         regex \.(COM|IN|CO|NET)\b
  strip trailing state codes: regex \b(NY|CA|DL|HR|KA|MH)\s*$
  → produces `descriptor_clean`

TIER 1 — EXACT MATCH            confidence = 1.00   method = "exact"
  lookup descriptor_clean in config/merchant_dictionary.csv (alias → merchant_id)

TIER 2 — FUZZY MATCH            confidence = score/100   method = "fuzzy"
  RapidFuzz.process.extractOne(descriptor_clean, dictionary_names,
                               scorer=token_set_ratio)
  accept if score >= FUZZY_THRESHOLD (config; default 88)

TIER 3 — CLUSTER                confidence = 0.50   method = "cluster"
  For all still-unresolved descriptors:
    TfidfVectorizer(analyzer='char_wb', ngram_range=(2,4))
    → cosine similarity → DBSCAN(eps=0.35, metric='cosine', min_samples=3)
  Each cluster gets a representative (highest-frequency member)
  → these are "unknown but grouped" merchants: a real, honest outcome

TIER 4 — UNRESOLVED             confidence = 0.00   method = "unresolved"
  Singletons that cluster nowhere. Reported, not hidden.

TIER 5 — MCC IMPUTATION
  If mcc is null AND merchant_id resolved:
     mcc := modal mcc of that merchant_id across the dataset
     set mcc_imputed_flag = TRUE   ← never hide an imputation
  Else: mcc := 9999 ("UNCLASSIFIED"), flagged
```

**Why the confidence score matters:** it lets a downstream business user filter. "Show me spend where merchant confidence ≥ 0.9." That is *governance*, and it is exactly the "data custodian" language in the JD.

**Tunable in `config/pipeline.yaml`** — `FUZZY_THRESHOLD`, `DBSCAN_EPS`, `NEAR_DUP_WINDOW_SECONDS`, `OUTLIER_MAD_Z`. No magic numbers in code.

---

## 7. The data quality scorecard

`scorecard.py` emits `reports/scorecard.md` + `reports/scorecard.json`. Two halves:

### 7.1 Before vs After (the headline table)

| Metric | Before | After |
|---|---|---|
| Distinct merchant strings | *(count raw)* | *(count canonical)* |
| Rows with usable merchant identity | ~% | ~% |
| Rows with valid parsed date | ~% | 100% (rest quarantined) |
| Rows with numeric amount in base currency | ~% | 100% |
| Rows with MCC | ~75% | ~% (X% imputed, flagged) |
| Distinct city spellings | *(count)* | *(count)* |
| Exact duplicates | *(count)* | 0 (dropped, logged) |
| Near-duplicates | unknown | *(count)*, flagged for review |
| Rows quarantined | — | *(count)* (*z*% — never silently dropped) |

### 7.2 Resolver accuracy vs ground truth (the flex)

Because you kept the pre-corruption truth:
- **Merchant resolution precision / recall / F1** (per tier: exact / fuzzy / cluster)
- **Confusion:** which merchants got wrongly collapsed together? (report the top 5 — showing your own errors is a *strength*)
- **Dedup precision/recall** — did you flag real duplicates, or genuine repeat purchases?
- **Threshold sensitivity curve:** F1 vs `FUZZY_THRESHOLD` from 70→95. Include the plot. This is how you justify the number 88 instead of "it felt right."

---

## 8. The insights layer (`sql/03_insights.sql`)

Four views. Each answers a question that the *dirty* data would have answered **wrongly**.

1. **`v_top_merchants_before_after`** — ★ the money shot. Top 10 merchants by total spend, computed on raw descriptors vs on canonical merchant IDs, side by side. Show the rank churn. *("Amazon was fragmented across 47 raw descriptor strings and did not appear in the raw Top 10 at all.")*
2. **`v_category_spend_mix`** — spend by MCC category, split by `mcc_imputed_flag`, so a stakeholder can see how much of the mix depends on imputation. Honesty as a feature.
3. **`v_duplicate_exposure`** — total ₹ value sitting in flagged near-duplicates. This is the direct "how much money is at stake in this ambiguity" number.
4. **`v_data_health_by_source`** — quality score by channel (POS/ONLINE/ATM) and by month. Which upstream feed is the worst? This is the **SLA/controls** view the JD asks for: define a threshold, breach it, raise a flag.

---

## 9. Repo structure

```
ledgerlens/
├── README.md                     ← the front door: problem, GIF of dashboard, results table, how to run
├── Makefile                      ← make data | make pipeline | make dashboard | make test
├── requirements.txt
├── config/
│   ├── pipeline.yaml             ← ALL thresholds. Zero magic numbers in code.
│   ├── merchant_dictionary.csv   ← merchant_id, canonical_name, alias, mcc, category
│   ├── city_canonical.csv        ← variant → canonical_city, city_code
│   ├── mcc_map.csv               ← mcc → category, category_group
│   └── fx_rates.csv              ← currency → rate_to_inr (static; documented limitation)
├── data/
│   ├── truth/transactions_truth.parquet    ← ground truth, NEVER read by the pipeline
│   ├── raw/transactions_raw.csv            ← the messy input
│   ├── quarantine/                         ← rejected rows + reject_reason
│   ├── interim/silver.parquet
│   └── warehouse/ledgerlens.duckdb
├── src/
│   ├── generate/
│   │   ├── make_clean.py         ← Faker; writes truth parquet
│   │   └── corrupt.py            ← the 14 defect injectors
│   ├── ingest.py
│   ├── profile_data.py           ← ydata-profiling → reports/profile_before.html
│   ├── validate/
│   │   ├── schemas.py            ← Pandera BronzeSchema, SilverSchema, GoldSchema
│   │   └── quarantine.py
│   ├── clean/
│   │   ├── parse_dates.py
│   │   ├── parse_amounts.py
│   │   ├── normalize_currency.py
│   │   ├── canonicalize_geo.py
│   │   └── sentinel_nulls.py
│   ├── resolve/
│   │   ├── merchant_resolver.py  ★ the core
│   │   └── mcc_imputer.py
│   ├── dedupe.py
│   ├── outliers.py
│   ├── load_warehouse.py
│   ├── scorecard.py
│   ├── benchmark_polars.py       ← optional but high-signal
│   └── run_pipeline.py           ← the single orchestrated entrypoint
├── sql/
│   ├── 01_dims.sql
│   ├── 02_fct_transactions.sql
│   └── 03_insights.sql
├── app/
│   └── dashboard.py              ← Streamlit, 4 tabs
├── tests/
│   ├── test_parse_amounts.py
│   ├── test_parse_dates.py
│   ├── test_merchant_resolver.py ← golden-set: 30 known descriptor→merchant pairs
│   ├── test_dedupe.py
│   └── test_schemas.py
├── docs/
│   ├── PRD.md                    ← 1-page product requirements doc  ★ read by humans
│   ├── DECISIONS.md              ← the judgment-call log            ★ read by humans
│   ├── DATA_DICTIONARY.md
│   └── SCALING.md                ← "how this runs on 8B rows"       ★ read by humans
├── reports/
│   ├── profile_before.html
│   ├── scorecard.md / .json
│   └── threshold_sensitivity.png
└── logs/
```

---

## 10. The three human-read documents

The code will be skimmed. **These will be read.** Do not skip them.

### `docs/PRD.md` (one page)
Problem · Users (Ops analyst, Finance, Merchant Insights) · Success metrics · Scope · **Out of scope** · Risks · Open questions. You are applying to *Product* Development. This one file is the difference.

### `docs/DECISIONS.md` (the killer artifact)
A table of every ambiguous call. Format:

| # | Decision | Options considered | Chosen | Rationale | Risk accepted |
|---|---|---|---|---|---|
| 1 | Near-duplicate transactions | Drop / Flag / Merge | **Flag** | A second identical coffee 90s later is plausible. Dropping would understate merchant revenue and could suppress a genuine cardmember charge. | Downstream consumers must handle the flag; documented in data dictionary. |
| 2 | Extreme outliers (>100× median) | Drop / Winsorize / Flag | **Flag** | High-value spend is legitimate on corporate cards. Removing it biases merchant revenue ranking. | Aggregations are sensitive to real outliers; a `_excl_outliers` variant view is provided. |
| 3 | Missing MCC | Drop row / Impute / Leave null | **Impute from merchant mode + flag** | Preserves 25% of rows; the flag preserves honesty. | Imputation error propagates to category mix; quantified in scorecard. |
| 4 | Fuzzy threshold = 88 | 80 / 85 / 88 / 92 | **88** | F1 peak on ground-truth sweep (see `threshold_sensitivity.png`). Below 85, distinct merchants collapse; above 92, recall craters. | Merchant-specific tuning would beat a global threshold; noted as future work. |
| 5 | Quarantine vs drop | Drop / Quarantine | **Quarantine** | Data destruction is irreversible and unauditable in a regulated context. | Storage cost; quarantine table must be triaged. |

*(Add every other call you make. Aim for 10–12 rows.)*

### `docs/SCALING.md` (half a page)
Be explicit and honest:
> *"At 250k rows this runs in ~40s in Pandas. At Amex volume (~8B txns/yr), the Tier-3 clustering step is the bottleneck: it is O(n²) in distinct descriptors. Mitigation: distinct descriptors do not scale linearly with rows (~millions, not billions), so the resolver runs on the **distinct-descriptor dimension**, not the fact table — and the resolved map is broadcast-joined back. This turns an 8B-row problem into a ~2M-row problem. In production this would be a nightly Spark job writing a `dim_merchant` SCD-2 table, with the fuzzy tier replaced by an approximate-nearest-neighbour index (FAISS/ScaNN) over descriptor embeddings."*

That paragraph is worth an entire extra project.

---

## 11. ACTION PLAN — for a coding agent

> **Agent instructions:** Implement the following phases in order. Do not proceed to phase *n+1* until the Definition of Done (DoD) for phase *n* passes. All thresholds live in `config/pipeline.yaml`. Every module gets a docstring stating its input, output, and the defect classes it handles. Write tests as you go, not at the end. Log every row-count change to `logs/`.

### Phase 0 — Scaffold (30 min)
- Create repo structure per Section 9. `requirements.txt`, `Makefile`, `config/pipeline.yaml` with all thresholds from Section 6.
- Seed `config/merchant_dictionary.csv` with **60 merchants** (mix of Indian + global: Amazon, Flipkart, Swiggy, Zomato, Blue Bottle Coffee, Starbucks, Uber, Ola, BigBasket, IndiGo, Reliance Digital, Croma, Apple, Netflix, Spotify, DMart, Myntra, Nykaa, IRCTC, HPCL…), each with 3–6 aliases, an MCC, and a category.
- Seed `config/city_canonical.csv` (≥15 Indian cities, ≥4 variants each), `config/mcc_map.csv`, `config/fx_rates.csv`.
- **DoD:** `make help` works; configs load; `pytest` runs (0 tests, exit 0).

### Phase 1 — Data generation (2 hrs)
- `src/generate/make_clean.py`: Faker, 250,000 rows, 5,000 accounts, 60 merchants, 18 months, realistic amount distributions **per category** (lognormal; groceries ≠ airlines), realistic time-of-day/day-of-week seasonality. Write `data/truth/transactions_truth.parquet`.
- `src/generate/corrupt.py`: implement **all 14 defect classes** from §5.3 at the specified rates, plus the 12 descriptor transforms from §5.2. Every injected defect is recorded in a `defect_log.csv` (row_id, defect_type) so the scorecard can compute true recall.
- **DoD:** `data/raw/transactions_raw.csv` exists, 250k rows; `defect_log.csv` counts match configured rates within ±0.5%; visual inspection of 20 random descriptors looks convincingly awful.

### Phase 2 — Bronze: ingest, profile, gate (1.5 hrs)
- `ingest.py`: read raw as all-string, no type inference (`dtype=str`), preserve every row.
- `profile_data.py`: ydata-profiling → `reports/profile_before.html`.
- `validate/schemas.py`: `BronzeSchema` (Pandera) — column presence, non-empty transaction_id, parseable-ish row shape. `validate/quarantine.py`: failing rows → `data/quarantine/bronze_rejects.csv` with a `reject_reason` column. **Never drop silently.**
- **DoD:** profile HTML generated; quarantine file contains exactly the schema-drift + impossible-date rows; ingest + quarantine row counts sum to 250k.

### Phase 3 — Silver: cleaning (3 hrs)
- `parse_dates.py`: try each of the 5 formats + epoch; unparseable → quarantine with reason. Return tz-naive UTC datetime.
- `parse_amounts.py`: strip currency symbols, thousands separators, whitespace; `(x)` → `-x`; return float. Unparseable → quarantine.
- `normalize_currency.py`: infer missing currency from symbol, else from country; convert to INR via `fx_rates.csv`; add `amount_inr`, keep `amount_original` + `currency_original`. **Never overwrite source values — always add columns.**
- `canonicalize_geo.py`: lookup + fuzzy fallback against `city_canonical.csv`.
- `sentinel_nulls.py`: map the sentinel list to true `NaN`, log counts per column.
- **DoD:** `pytest tests/test_parse_amounts.py tests/test_parse_dates.py` green, incl. edge cases (`"(1,240.00)"`, `"₹ 18.99 "`, `"-999"`, `""`, epoch `1710000000`).

### Phase 4 — The merchant resolver ★ (4 hrs — this is the project)
- Implement Tiers 0–5 exactly as specified in §6.
- Output columns: `merchant_id`, `merchant_name`, `mcc`, `mcc_imputed_flag`, `merchant_category`, `match_method`, `match_confidence`.
- `tests/test_merchant_resolver.py`: a **golden set of 30 hand-written descriptor→expected-merchant pairs** covering every corruption transform. This is your regression suite.
- Threshold sweep script: `FUZZY_THRESHOLD` 70→95 step 1, score F1 against truth, save `reports/threshold_sensitivity.png`, pick the argmax, write it to config.
- **DoD:** golden-set tests green; measured precision ≥ 0.93 and recall ≥ 0.90 against ground truth; sensitivity plot exists; the chosen threshold in config equals the F1 argmax.

### Phase 5 — Dedupe, outliers, Gate 2 (1.5 hrs)
- `dedupe.py`: exact-hash duplicates (all business columns) → drop, log to `logs/dropped_exact_dupes.csv`. Near-dupes (same `account_id` + `merchant_id` + `amount_inr`, within `NEAR_DUP_WINDOW_SECONDS`) → `is_near_duplicate = True`, **retained**.
- `outliers.py`: robust z-score via MAD, per `merchant_category`. `is_outlier = True`, **retained**.
- `SilverSchema` (Pandera): typed, `amount_inr > 0` for approved, `merchant_id` non-null, `match_confidence` in [0,1], date in range.
- **DoD:** dedup precision/recall vs `defect_log.csv` both ≥ 0.95; Silver gate passes; `data/interim/silver.parquet` written.

### Phase 6 — Gold: warehouse + SQL (2 hrs)
- `load_warehouse.py` → DuckDB. Star schema: `dim_merchant`, `dim_date`, `dim_account`, `fct_transactions`.
- `sql/03_insights.sql`: the four views from §8. The before/after Top-10 view must compute the raw-descriptor ranking too — that comparison is the headline.
- **DoD:** all four views query without error; `v_top_merchants_before_after` shows a visibly different Top 10 in the two columns.

### Phase 7 — Scorecard + benchmark (2 hrs)
- `scorecard.py`: emit §7.1 and §7.2 to `reports/scorecard.md` + `.json`.
- `benchmark_polars.py`: rerun the Silver cleaning stage in Polars; report wall-clock speedup. One table, two rows. (Expect a meaningful multiple — report whatever you actually measure.)
- **DoD:** `scorecard.md` renders; every number in it is computed, none hardcoded.

### Phase 8 — Dashboard (2.5 hrs)
Streamlit, four tabs:
1. **Data Health** — the before/after scorecard, quarantine counts, health-by-channel with an SLA threshold line
2. **Merchant Intelligence** — searchable descriptor→merchant resolution table with confidence; a confidence-threshold slider that live-filters
3. **Insights** — the four views, incl. the Top-10 before/after side-by-side bar chart
4. **Decisions** — renders `DECISIONS.md` (yes, in the app — governance is a feature)
- **DoD:** `make dashboard` opens it; no errors on empty filters; screenshot/GIF saved into the README.

### Phase 9 — Docs & polish (2 hrs)
- `README.md`: problem in 3 lines → dashboard GIF → **results table** → architecture diagram (paste §3) → how to run → what I'd do next.
- Write `PRD.md`, `DECISIONS.md` (10–12 rows), `DATA_DICTIONARY.md`, `SCALING.md`.
- `make all` runs the whole thing from scratch in one command.
- **DoD:** a stranger can `git clone && make all` and get every artifact. That is the bar.

**Total: ~21 focused hours.** Comfortably a long weekend plus a couple of evenings.

---

## 12. Agent handoff prompt (copy-paste this)

> Implement the project specified in `LEDGERLENS_PROJECT_SPEC.md`, following Section 11 phase by phase. Do not skip the Definition of Done checks — after each phase, run them and report the actual numbers before continuing. Do not proceed if a DoD fails; fix it first. All tunable numbers must live in `config/pipeline.yaml`; no magic numbers in code. Every function that changes row count must log before/after counts. Never drop a row without writing it to `data/quarantine/` with a `reject_reason`. Write the tests in the same phase as the code they test. When the pipeline is complete, run it end to end and paste the real contents of `reports/scorecard.md` back to me — I need the measured numbers, not placeholders.

---

## 13. What to do the day before you apply

- Record a **60-second Loom** walking through the dashboard. Link it in the README and in your application.
- Pin the repo on GitHub. Clean commit history (not one commit called "final").
- In your cover letter / application form, use the one-line pitch from §1 verbatim, then the single strongest measured number from your scorecard.

---

## 14. Resume bullets

Use the measured numbers from your own scorecard run. Brackets `[ ]` = fill from `reports/scorecard.json`. **Do not invent these — run the pipeline and read them off.** Section 15 tells you what range to expect.

**LedgerLens — Transaction Data Quality & Merchant Intelligence Pipeline** · *Python, Pandas, Polars, DuckDB, Pandera, RapidFuzz, scikit-learn, Streamlit, SQL, pytest*

1. **Engineered a production-style medallion (Bronze→Silver→Gold) data pipeline** processing **250K synthetic card transactions**, ingesting 14 classes of real-world data defects — malformed dates, dirty currency strings, sentinel nulls, schema drift, and unstructured merchant descriptors — and delivering a validated, query-ready DuckDB warehouse in **under [X] seconds end-to-end**.

2. **Built a 5-tier merchant entity-resolution engine** (regex normalization → exact dictionary match → RapidFuzz fuzzy matching → TF-IDF char-n-gram + DBSCAN clustering → modal MCC imputation) that collapsed **[12,400] raw descriptor variants into [850] canonical merchants — a [93%] reduction** — achieving **[96.4%] precision and [91.2%] recall** benchmarked against held-out ground truth, with a per-row confidence score enabling downstream governance filtering.

3. **Demonstrated material business impact of data quality:** merchant-spend leaderboards computed on raw descriptors were **materially wrong — [4] of the true Top-10 merchants were absent entirely** because a single merchant's spend was fragmented across up to **[47] distinct raw strings**; post-resolution rankings corrected **[₹X.XM]** of misattributed spend.

4. **Implemented data-quality-as-code** using **Pandera schema contracts** at three pipeline gates, raising usable-record yield from **[62%] to [98.7%]** while routing **[1.3%]** of rows to an auditable quarantine store with typed rejection reasons — **zero rows silently dropped**, meeting the auditability bar required in regulated financial data.

5. **Designed a governance-first deduplication and outlier policy** distinguishing true double-charges from legitimate repeat purchases (**[95%+] F1** vs ground truth), deliberately **flagging rather than deleting [3,750] ambiguous transactions worth [₹X.XM]** in exposure — preserving analytical integrity and surfacing the ambiguity to business owners instead of silently resolving it.

6. **Tuned and defended every threshold empirically** — swept the fuzzy-match cutoff across 70–95 to select the F1-maximizing value, benchmarked Pandas vs **Polars** for a **[Nx]** speedup on the cleaning stage, and shipped a **Streamlit** stakeholder dashboard plus a documented **Decisions Log** justifying all 12 ambiguous judgment calls with their accepted risks.

> **Bullet-writing note:** #3 and #5 are the two that will get you the interview, because they are the only ones that convert data work into *money and business consequence*. If you have room for only three bullets, use **1, 2, and 3.**

---

## 15. The figures — what you can honestly claim

**Read this carefully. Do not fabricate any of these.** Every number below is one your pipeline *computes*. Run it, read `reports/scorecard.json`, and put the real value on your resume. The ranges below are what a correctly-built version of this project typically produces — they tell you what to *expect*, and they tell you something is wrong if you're far outside them.

### A. Directly measured by your pipeline

| Figure | Expected range | Where it comes from |
|---|---|---|
| Raw descriptor strings → canonical merchants | ~10,000–15,000 → ~60 base merchants (aliases inflate to ~800–1,000 observed) | `scorecard.json.merchant_collapse` |
| Descriptor cardinality reduction | **90–95%** | same |
| Merchant resolution precision | **93–98%** | vs ground truth |
| Merchant resolution recall | **88–94%** | vs ground truth |
| Usable-record yield, before → after | **~60–65% → ~97–99%** | Gate pass rates |
| Rows quarantined | **1–2%** | `bronze_rejects.csv` |
| MCC completeness, before → after | **75% → ~97%** (with ~22% flagged as imputed) | `mcc_imputer` |
| City spellings collapsed | ~60–75 variants → 15 canonical | `canonicalize_geo` |
| Exact duplicates removed | ~2,500 (1.0%) | `dedupe` |
| Near-duplicates flagged | ~3,750 (1.5%) | `dedupe` |
| Dedup F1 vs ground truth | **≥95%** | `defect_log.csv` comparison |
| Pipeline wall-clock, 250k rows | **30–60s** (Pandas) | `logs/` |
| Polars speedup on cleaning stage | **measure it and report the real number** | `benchmark_polars.py` |

### B. The one figure that wins the interview

**Rank churn in the Top-10 merchant leaderboard.** Compute the true Top-10 (from ground truth), the raw-descriptor Top-10, and the post-resolution Top-10. Report how many of the true Top-10 were **missing** from the raw ranking, and the ₹ value misattributed.

Expect **3–5 of the true Top-10 to be absent** from the raw view, because a merchant's spend is shattered across dozens of strings and none of the fragments is individually large enough to rank. This is a genuinely striking result and it is the single sentence to lead with.

### C. Business extrapolation — how to do this *honestly*

You will be tempted to write "reduced disputes by 30%." **Don't.** You have no dispute data, and a good interviewer will catch it instantly and stop trusting everything else on the page.

Do this instead — state it as an explicitly-labelled model with your assumption visible:

> *"Unrecognizable merchant descriptors are a known driver of 'I don't recognize this charge' inquiries. **Under an assumed** 0.5% inquiry rate on unresolved descriptors and a ₹250 servicing cost per contact, resolving [96%] of the [38%] previously-unresolvable descriptors in a 250K-transaction sample implies a modelled saving of **₹[X]** per 250K transactions — which at a 1B-transaction annual volume scales to **₹[Y] Cr**. The assumptions are stated, not measured; the resolution rate is measured."*

That framing — **"the rate is measured, the assumption is stated"** — is more impressive than a made-up number, because it is exactly how a real product analyst writes a business case. Put it in the PRD, not the resume, and be ready to defend the assumption when they push on it. They will push. That's the test.

---

## 16. The three sentences to have ready

**"What did you build?"**
> *A pipeline that takes deliberately broken card transactions and makes them trustworthy — the core of it is a five-tier merchant entity resolver that turns machine junk like `SQ *BLUE BOTL COF 4471` back into `Blue Bottle Coffee`, with a confidence score attached to every match.*

**"Why does it matter?"**
> *Because the cleaning changed the answer. The Top-10 merchant spend leaderboard was wrong before I ran it — four real top merchants were invisible, because their spend was scattered across dozens of raw spellings. That's not a tidiness problem, that's a wrong business decision.*

**"What was the hardest call?"**
> *Whether to delete near-duplicate transactions. I chose to flag them instead of dropping them, because a second identical coffee ninety seconds later is completely plausible — and silently deleting a real cardmember charge is a worse failure than surfacing an ambiguous one. Everything I couldn't resolve, I quarantined and reported rather than destroyed. It's all in the decisions log.*
