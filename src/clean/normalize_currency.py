"""Currency normalization module.

Handles missing currency values by inferring them from original amount strings
or the country column. Converts all amounts to INR using FX rates from config.
Strictly adheres to the data safety rule: never overwrite source values.
"""

import logging
import pandas as pd

from src.config import PROJECT_ROOT

log = logging.getLogger(__name__)


def _load_fx_rates(cfg: dict) -> dict[str, float]:
    """Load FX rates as currency -> rate_to_inr."""
    fx_path = PROJECT_ROOT / cfg["paths"]["fx_rates"]
    df = pd.read_csv(fx_path)
    return dict(zip(df["currency"], df["rate_to_inr"]))


def normalize_currency(df: pd.DataFrame, df_raw: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Infer missing currencies and calculate amount_inr.
    
    Args:
        df: The partially cleaned DataFrame (contains parsed float 'amount').
        df_raw: The original raw DataFrame (contains original string 'amount').
        cfg: Pipeline configuration.
        
    Returns:
        DataFrame with new columns 'amount_original', 'currency_original',
        'currency_inferred', and 'amount_inr'.
    """
    df = df.copy()
    fx_rates = _load_fx_rates(cfg)
    
    # 1. Preserve original columns (Data Safety Rule)
    df["amount_original"] = df_raw["amount"]
    df["currency_original"] = df_raw["currency"]
    
    # 2. Infer missing currencies
    # We work on a new column so we don't overwrite currency_original
    curr = df_raw["currency"].copy().fillna("").astype(str).str.strip()
    missing_mask = curr == ""
    
    # Inference Strategy A: Check original amount string for currency symbols
    raw_amounts = df_raw["amount"].fillna("").astype(str)
    has_rupee = raw_amounts.str.contains("₹")
    has_dollar = raw_amounts.str.contains(r"\$")
    
    curr = curr.mask(missing_mask & has_rupee, "INR")
    curr = curr.mask(missing_mask & has_dollar, "USD")
    
    # Inference Strategy B: Fallback to country
    missing_mask_after_a = curr == ""
    country = df["country"].fillna("").astype(str).str.upper()
    
    # Check for variants of India and US
    is_india = country.isin(["IN", "INDIA", "IND"])
    is_us = country.isin(["US", "USA"])
    
    curr = curr.mask(missing_mask_after_a & is_india, "INR")
    curr = curr.mask(missing_mask_after_a & is_us, "USD")
    
    # If STILL missing (e.g., country was also a sentinel null), default to INR
    # with a warning log, since 88% of our data is INR.
    still_missing = curr == ""
    if still_missing.any():
        count = still_missing.sum()
        log.warning("Could not infer currency for %d rows. Defaulting to INR.", count)
        curr = curr.mask(still_missing, "INR")
        
    df["currency_inferred"] = curr
    
    # 3. Compute amount_inr
    # Ensure amount column is float (from parse_amounts)
    amount_float = df["amount"].astype(float)
    
    # Map inferred currency to exchange rate
    rate_map = curr.map(fx_rates)
    # If there's an unknown currency string not in fx_rates, default to 1.0 (INR)
    rate_map = rate_map.fillna(1.0)
    
    df["amount_inr"] = amount_float * rate_map
    
    # We round to 2 decimals for currency
    df["amount_inr"] = df["amount_inr"].round(2)
    
    return df
