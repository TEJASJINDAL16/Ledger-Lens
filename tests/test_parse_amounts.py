"""Tests for the amount parsing module."""

import pandas as pd
import pytest

from src.clean.parse_amounts import clean_amounts


def test_clean_amounts_edge_cases():
    """Verify that all edge cases in amount parsing are handled exactly as expected."""
    raw_data = {
        "amount": [
            "(1,240.00)",   # negative parens with comma
            "₹ 18.99 ",     # symbol, spaces
            "-999",         # standard negative string
            " 1,240.00 ",   # spaces, commas, no symbol
            "$1,240.00",    # USD symbol
            "(₹ 1,240.00)", # negative parens with symbol
            "1240",         # no decimals
            "",             # empty string (should quarantine)
            "ABC",          # total garbage (should quarantine)
        ]
    }
    df = pd.DataFrame(raw_data)
    
    cleaned_df, quarantine_mask = clean_amounts(df)
    
    # Verify successfully parsed values
    assert cleaned_df["amount"].iloc[0] == -1240.00
    assert cleaned_df["amount"].iloc[1] == 18.99
    assert cleaned_df["amount"].iloc[2] == -999.00
    assert cleaned_df["amount"].iloc[3] == 1240.00
    assert cleaned_df["amount"].iloc[4] == 1240.00
    assert cleaned_df["amount"].iloc[5] == -1240.00
    assert cleaned_df["amount"].iloc[6] == 1240.00
    
    # First 7 should pass
    assert quarantine_mask.iloc[:7].sum() == 0, "Valid amounts were quarantined"
    
    # Last 2 should be quarantined
    assert quarantine_mask.iloc[7:].all(), "Invalid amounts were not quarantined"
    
    # Verify unparseable rows are NaN
    assert pd.isna(cleaned_df["amount"].iloc[7])
    assert pd.isna(cleaned_df["amount"].iloc[8])
