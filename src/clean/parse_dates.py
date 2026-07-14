"""Date parsing and cleaning module.

Attempts to parse messy transaction timestamps against a configured list
of expected formats, plus unix epoch seconds. Unparseable rows are marked
for quarantine.
"""

import pandas as pd


def clean_dates(df: pd.DataFrame, date_formats: list[str]) -> tuple[pd.DataFrame, pd.Series]:
    """Parse the 'txn_timestamp' column into a clean datetime.
    
    Args:
        df: The DataFrame containing a 'txn_timestamp' string column.
        date_formats: List of strftime formats to try.
        
    Returns:
        A tuple of (cleaned_df, quarantine_mask). 
        The cleaned_df contains the parsed 'txn_timestamp' as datetime64[ns].
        The quarantine_mask is a boolean Series where True means the row 
        failed to parse and should be quarantined.
    """
    df = df.copy()
    raw_col = df["txn_timestamp"]
    
    # We will accumulate successfully parsed dates here
    parsed = pd.Series(pd.NaT, index=df.index, dtype='datetime64[ns]')
    
    # 1. Try each configured string format
    for fmt in date_formats:
        # Only attempt on rows that haven't been successfully parsed yet
        unparsed_mask = parsed.isna()
        if not unparsed_mask.any():
            break
            
        current_attempt = pd.to_datetime(
            raw_col[unparsed_mask], 
            format=fmt, 
            errors='coerce'
        )
        parsed.update(current_attempt.dropna())
        
    # 2. Try epoch integers for whatever is left
    unparsed_mask = parsed.isna()
    if unparsed_mask.any():
        # First convert to numeric. Only integers that look like epochs (e.g. 10 digits)
        # Should we just try to_numeric on all unparsed?
        numeric_attempt = pd.to_numeric(raw_col[unparsed_mask], errors='coerce')
        # Filter to reasonable epoch values (e.g., > 1000000000, ~2001) to avoid 
        # interpreting "1234" as an epoch of 1970 if that somehow slipped in
        valid_epoch_mask = numeric_attempt.notna() & (numeric_attempt > 100000000)
        
        if valid_epoch_mask.any():
            epoch_dates = pd.to_datetime(
                numeric_attempt[valid_epoch_mask], 
                unit='s', 
                errors='coerce'
            )
            parsed.update(epoch_dates)

    # 3. Identify unparseable rows
    # Any row that is STILL NaT is unparseable
    quarantine_mask = parsed.isna()
    
    # 4. Assign the cleaned column back
    # For quarantined rows, keeping NaT is fine since they will be dropped from the main flow
    df["txn_timestamp"] = parsed
    
    return df, quarantine_mask
