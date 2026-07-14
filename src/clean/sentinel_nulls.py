"""Sentinel null mapping module.

Scans all string columns in the DataFrame and maps known sentinel
values (e.g., 'NA', 'N/A', '-', 'NULL', '-999', '') to true pd.NA.
Logs the counts of mapped nulls per column.
"""

import logging
import pandas as pd

log = logging.getLogger(__name__)

# The specific sentinels defined by the project spec
SENTINELS = {"NA", "N/A", "-", "NULL", "-999", ""}


def map_sentinels(df: pd.DataFrame) -> pd.DataFrame:
    """Map string sentinel values to pd.NA across all object/string columns.
    
    Args:
        df: The DataFrame.
        
    Returns:
        DataFrame with sentinels replaced by true NaNs.
    """
    df = df.copy()
    
    # Identify which columns to process (mostly string columns, though amount/timestamp 
    # were already converted to float/datetime). We'll safely process object/string cols.
    string_cols = df.select_dtypes(include=['object', 'string']).columns
    
    for col in string_cols:
        # We use .isin() for exact matching. Since strings could have leading/trailing 
        # whitespace, we strip them for the comparison but only replace exact matches 
        # (or stripped matches) to pd.NA.
        # To be safe, we'll replace based on the stripped value.
        stripped_col = df[col].astype(str).str.strip()
        mask = stripped_col.isin(SENTINELS)
        
        count = mask.sum()
        if count > 0:
            log.info("Mapped %d sentinel nulls in column '%s'", count, col)
            # Use pd.NA which is pandas' modern missing value type for strings,
            # or just None which pandas handles well for object arrays.
            # Using None works best for compatibility across pandas versions for string cols.
            df.loc[mask, col] = None
            
    return df
