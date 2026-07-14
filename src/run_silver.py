"""Silver stage runner.

Executes the Phase 3 Silver cleaning logic: parses dates, parses amounts,
normalizes currencies to INR, canonicalizes geo locations, and handles sentinels.
Rows that fail parsing (e.g., completely unparseable amounts or dates) are 
quarantined to data/quarantine/silver_rejects.csv.
"""

import logging
import sys

import pandas as pd

from src.config import PROJECT_ROOT, load_config, setup_logging
from src.clean.parse_dates import clean_dates
from src.clean.parse_amounts import clean_amounts
from src.clean.normalize_currency import normalize_currency
from src.clean.canonicalize_geo import canonicalize_geo
from src.clean.sentinel_nulls import map_sentinels

log = logging.getLogger(__name__)


def main() -> None:
    cfg = load_config()
    setup_logging(str(PROJECT_ROOT / cfg["paths"]["log_dir"]))
    
    log.info("Starting Silver stage (Cleaning)")
    
    # 1. Load data that passed the Bronze gate
    # We load the full raw csv again, but we should really load from interim/bronze.parquet.
    # Wait, Phase 2 didn't save a bronze parquet, it just logged the output of run_bronze.
    # We need to either modify run_bronze to save it, or re-run bronze gate here.
    # Let's import the bronze gate logic to get the good rows.
    from src.ingest import ingest_raw_data
    from src.validate.schemas import BronzeSchema
    from src.validate.quarantine import enforce_and_quarantine
    
    raw_df = ingest_raw_data(cfg)
    bronze_quarantine_path = cfg["paths"]["quarantine_dir"] + "/bronze_rejects.csv"
    df = enforce_and_quarantine(raw_df, BronzeSchema, bronze_quarantine_path, "Bronze (re-run)")
    
    total_bronze = len(df)
    log.info("Starting Silver cleaning on %d Bronze rows", total_bronze)
    
    # Keep a copy of raw columns for the currency inference (Data Safety Rule)
    df_raw_bronze = df.copy()
    
    # 2. Parse Dates
    formats = cfg.get("date_formats", [])
    df, date_quarantine_mask = clean_dates(df, formats)
    
    # 3. Parse Amounts
    df, amount_quarantine_mask = clean_amounts(df)
    
    # 4. Quarantine unparseable rows
    # A row is rejected if either date or amount failed parsing
    silver_quarantine_mask = date_quarantine_mask | amount_quarantine_mask
    
    if silver_quarantine_mask.any():
        quarantine_df = df[silver_quarantine_mask].copy()
        
        # Add reasons
        reasons = []
        for i in quarantine_df.index:
            r = []
            if date_quarantine_mask.loc[i]:
                r.append("unparseable_date")
            if amount_quarantine_mask.loc[i]:
                r.append("unparseable_amount")
            reasons.append(" | ".join(r))
            
        quarantine_df["reject_reason"] = reasons
        
        # Save to silver quarantine
        silver_quarantine_path = PROJECT_ROOT / cfg["paths"]["quarantine_dir"] / "silver_rejects.csv"
        quarantine_df.to_csv(silver_quarantine_path, index=False)
        log.warning("[Silver] Quarantined %d rows with unparseable fields to silver_rejects.csv", len(quarantine_df))
        
        # Filter good rows
        df = df[~silver_quarantine_mask]
        df_raw_bronze = df_raw_bronze[~silver_quarantine_mask]
    
    # 5. Normalize Currencies
    df = normalize_currency(df, df_raw_bronze, cfg)
    
    # 6. Canonicalize Geo
    df = canonicalize_geo(df, cfg)
    
    # 7. Map Sentinels
    df = map_sentinels(df)
    
    # 8. Merchant Resolution & MCC Imputation
    from src.resolve.merchant_resolver import resolve_merchants
    from src.resolve.impute_mcc import impute_mcc
    
    df = resolve_merchants(df, cfg)
    df = impute_mcc(df)
    
    # 9. Deduplication and Outliers (Phase 5)
    from src.clean.dedupe import handle_duplicates
    from src.clean.outliers import flag_outliers
    
    df = handle_duplicates(df, cfg)
    df = flag_outliers(df, cfg)
    
    # 10. Silver Gate Validation
    from src.validate.schemas import SilverSchema
    
    silver_quarantine_path2 = cfg["paths"]["quarantine_dir"] + "/silver_rejects_gate2.csv"
    df = enforce_and_quarantine(df, SilverSchema, silver_quarantine_path2, "Silver (Gate 2)")
    
    # 11. Verify Conservation of Rows
    passed_count = len(df)
    
    # 12. Save Silver dataset to Parquet
    silver_out = PROJECT_ROOT / cfg["paths"]["silver_parquet"]
    silver_out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(silver_out, index=False)
    
    log.info("Silver stage complete. %d rows saved to %s", passed_count, silver_out.name)


if __name__ == "__main__":
    main()
