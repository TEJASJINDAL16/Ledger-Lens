"""MCC Imputation module (Phase 4).

Implements Tier 5 of the Merchant Resolution algorithm:
If the MCC is missing, infer it from the modal MCC of the resolved merchant.
If still missing (or unresolved), default to 9999 (Unclassified).
Always sets mcc_imputed_flag when modifying to preserve data lineage.
"""

import logging
import pandas as pd

log = logging.getLogger(__name__)


def impute_mcc(df: pd.DataFrame) -> pd.DataFrame:
    """Impute missing MCCs based on resolved merchant IDs.
    
    Args:
        df: The DataFrame containing 'mcc' and 'merchant_id'.
        
    Returns:
        DataFrame with filled 'mcc' and new 'mcc_imputed_flag'.
    """
    df = df.copy()
    
    # 1. Identify rows needing imputation
    # MCCs can be actual nulls, or sentinels like "0000" that weren't caught
    # We will treat None/NaN and "0000" as missing
    is_missing = df["mcc"].isna() | (df["mcc"].astype(str) == "0000")
    
    df["mcc_imputed_flag"] = False
    
    if not is_missing.any():
        return df
        
    log.info("Imputing MCCs for %d rows...", is_missing.sum())
    
    # 2. Compute modal MCC per merchant_id
    # We group by merchant_id and find the most common non-missing MCC
    valid_mcc_df = df[~is_missing & df["merchant_id"].notna()]
    
    if len(valid_mcc_df) > 0:
        # mode() returns a Series of modes, we take the first one .iloc[0] if there's a tie
        modal_mccs = valid_mcc_df.groupby("merchant_id")["mcc"].apply(
            lambda x: x.mode().iloc[0] if not x.mode().empty else None
        )
    else:
        modal_mccs = pd.Series(dtype=str)
        
    # 3. Impute where possible
    # We can only impute if merchant_id is not null
    can_impute = is_missing & df["merchant_id"].notna()
    
    if can_impute.any():
        # Map the merchant_id to the modal MCC
        imputed_vals = df.loc[can_impute, "merchant_id"].map(modal_mccs)
        
        # Only apply where the map actually found a mode
        actually_imputed = can_impute & imputed_vals.notna()
        df.loc[actually_imputed, "mcc"] = imputed_vals[actually_imputed]
        df.loc[actually_imputed, "mcc_imputed_flag"] = True
        
        log.info("Successfully imputed %d MCCs from merchant history.", actually_imputed.sum())
        
    # 4. Fallback for the rest
    still_missing = df["mcc"].isna() | (df["mcc"].astype(str) == "0000")
    if still_missing.any():
        df.loc[still_missing, "mcc"] = "9999"
        df.loc[still_missing, "mcc_imputed_flag"] = True
        log.info("Defaulted %d unresolvable MCCs to '9999'.", still_missing.sum())
        
    return df
