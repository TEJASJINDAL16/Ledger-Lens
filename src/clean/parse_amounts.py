"""Amount parsing and cleaning module.

Converts dirty string amounts into floats. Strips currency symbols ($/₹),
removes commas and whitespace, and converts negative-in-parentheses notation
(e.g., '(1,240.00)') into negative floats (-1240.00). Unparseable rows are 
flagged for quarantine.
"""

import pandas as pd


def clean_amounts(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Parse the 'amount' column into a clean float.
    
    Args:
        df: The DataFrame containing an 'amount' string column.
        
    Returns:
        A tuple of (cleaned_df, quarantine_mask).
    """
    df = df.copy()
    
    # 1. Fill missing strings with empty so string methods work
    s = df["amount"].fillna("").astype(str).str.strip()
    
    # 2. Check for negative parens e.g. "(1,240.00)" or "(₹ 1,240.00)"
    is_paren_negative = s.str.startswith("(") & s.str.endswith(")")
    
    # 3. Strip all non-numeric/non-decimal/non-sign characters
    # We keep digits, periods (.), and minus signs (-)
    # We first replace parens with minus if it was a paren negative
    s = s.where(~is_paren_negative, "-" + s.str[1:-1])
    
    # Remove commas, currency symbols, and spaces
    # regex=True replaces anything that isn't a digit, period, or minus sign
    s = s.replace(r'[^\d\.-]', '', regex=True)
    
    # 4. Convert to float
    parsed = pd.to_numeric(s, errors='coerce')
    
    # 5. Identify unparseable rows
    # A row is unparseable if to_numeric yielded NaN, BUT we must be careful 
    # about rows that were already empty (they should be quarantined too).
    quarantine_mask = parsed.isna()
    
    # 6. Assign back
    df["amount"] = parsed
    
    return df, quarantine_mask
