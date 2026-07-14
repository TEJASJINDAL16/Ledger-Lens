"""Deduplication module.

Identifies exact duplicates (same business columns) and near duplicates
(same account, merchant, and amount within a short time window).
Exact duplicates are dropped and logged. Near duplicates are strictly
flagged (is_near_duplicate=True) and retained.
"""

import logging
import pandas as pd

from src.config import PROJECT_ROOT

log = logging.getLogger(__name__)


def handle_duplicates(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Identify, flag, and drop duplicates as appropriate.
    
    Args:
        df: The DataFrame.
        cfg: Pipeline configuration.
        
    Returns:
        DataFrame with exact duplicates removed and near duplicates flagged.
    """
    df = df.copy()
    
    # 1. Exact Duplicates
    # We define "exact" as matching on all business columns (excluding transaction_id)
    # We exclude internal processing flags as well, but this is early enough that we just exclude ID
    business_cols = [c for c in df.columns if c not in ["transaction_id", "mcc_imputed_flag", "descriptor_clean", "match_method", "match_confidence"]]
    
    # Find exact dupes (keep the first occurrence, drop subsequent)
    exact_dupes_mask = df.duplicated(subset=business_cols, keep="first")
    
    if exact_dupes_mask.any():
        num_exact = exact_dupes_mask.sum()
        dropped_df = df[exact_dupes_mask].copy()
        
        # Save to log file
        log_path = PROJECT_ROOT / cfg["paths"]["log_dir"] / "dropped_exact_dupes.csv"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        dropped_df.to_csv(log_path, index=False)
        
        # Drop them from the dataset
        df = df[~exact_dupes_mask]
        log.warning("Dropped %d exact duplicates. Logged to %s", num_exact, log_path.name)
        
    # 2. Near Duplicates
    # Same account_id, merchant_id, amount_inr, within NEAR_DUP_WINDOW_SECONDS
    window_sec = cfg.get("near_dup_window_seconds", 120)
    
    # Sort by account, merchant, and time to enable window comparison
    # We must be careful about null dates or merchants.
    df = df.sort_values(by=["account_id", "merchant_id", "txn_timestamp"])
    
    # We find groups of account + merchant + amount_inr
    # Within each group, if the time diff between consecutive rows <= window, they are near dupes
    # We flag BOTH rows in the pair as near dupes
    
    # Only consider rows with valid timestamps
    valid_time_mask = df["txn_timestamp"].notna()
    
    group_cols = ["account_id", "merchant_id", "amount_inr"]
    
    # Time diff to previous row in group
    diff_prev = df.groupby(group_cols)["txn_timestamp"].diff().dt.total_seconds().abs()
    
    # Time diff to next row in group
    # diff(-1) gives difference to next row
    diff_next = df.groupby(group_cols)["txn_timestamp"].diff(-1).dt.total_seconds().abs()
    
    # A row is a near duplicate if it's close to the previous OR the next transaction in its group
    is_near = valid_time_mask & ((diff_prev <= window_sec) | (diff_next <= window_sec))
    
    df["is_near_duplicate"] = is_near
    
    if is_near.any():
        num_near = is_near.sum()
        log.warning("Flagged %d near-duplicates (retained in dataset).", num_near)
        
    # Restore original index order just in case, though it doesn't strictly matter for SQL
    df = df.sort_index()
        
    return df
