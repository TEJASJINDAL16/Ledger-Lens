"""Outlier detection module.

Identifies extreme outliers based on the Median Absolute Deviation (MAD)
of the transaction amount within each merchant category. Outliers are
flagged (is_outlier=True) and strictly retained to avoid biasing aggregates.
"""

import logging
import numpy as pd
import pandas as pd

log = logging.getLogger(__name__)


def flag_outliers(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Identify and flag extreme amount outliers using MAD.
    
    Args:
        df: The DataFrame.
        cfg: Pipeline configuration.
        
    Returns:
        DataFrame with new boolean column 'is_outlier'.
    """
    df = df.copy()
    
    mad_z_thresh = cfg.get("outlier_mad_z", 3.5)
    
    # We need merchant_category to group by. If it's not present, we use MCC or fallback
    # The dictionary has 'category', let's see if we merged it. 
    # Ah, the resolver maps to merchant_id, but we need to map to category.
    # If category is not present in df, we must merge it or group by mcc.
    # Let's group by MCC as a proxy for category if category isn't there, but the spec says `merchant_category`.
    # I'll try 'merchant_category' if it exists, else 'mcc'.
    group_col = "merchant_category" if "merchant_category" in df.columns else "mcc"
    
    # We only calculate MAD on valid positive amounts
    valid_mask = (df["amount_inr"] > 0) & df[group_col].notna()
    valid_df = df[valid_mask]
    
    # Calculate Median per group
    group_median = valid_df.groupby(group_col)["amount_inr"].transform("median")
    
    # Calculate absolute deviation from median
    abs_dev = (valid_df["amount_inr"] - group_median).abs()
    
    # Calculate MAD (Median of Absolute Deviations) per group
    # We use groupby again because we need the median of the absolute deviations
    mad_df = pd.DataFrame({group_col: valid_df[group_col], "abs_dev": abs_dev})
    group_mad = mad_df.groupby(group_col)["abs_dev"].transform("median")
    
    # Robust Z-score formula: 0.6745 * (x - median) / MAD
    # If MAD is 0, we avoid division by zero
    mad_safe = group_mad.replace(0, 1.0)
    
    robust_z = 0.6745 * abs_dev / mad_safe
    
    # Identify outliers
    is_outlier_valid = robust_z > mad_z_thresh
    
    # Map back to main dataframe
    df["is_outlier"] = False
    df.loc[valid_mask, "is_outlier"] = is_outlier_valid
    
    num_outliers = df["is_outlier"].sum()
    if num_outliers > 0:
        log.warning("Flagged %d extreme outliers (retained in dataset).", num_outliers)
        
    return df
