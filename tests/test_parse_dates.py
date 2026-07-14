"""Tests for the date parsing module."""

import pandas as pd
import pytest

from src.clean.parse_dates import clean_dates


def test_clean_dates_all_formats():
    """Verify that all 5 date formats and epoch integers are correctly parsed."""
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%m-%d-%Y %H:%M:%S",
        "%d %b %Y %H:%M",
        "%Y%m%dT%H%M%S",
    ]
    
    # 5 valid formats + 1 valid epoch + 2 invalid strings
    raw_data = {
        "txn_timestamp": [
            "2024-05-12 14:30:00",   # 1
            "12/05/2024 14:30",      # 2
            "05-12-2024 14:30:00",   # 3
            "12 May 2024 14:30",     # 4
            "20240512T143000",       # 5
            "1715524200",            # epoch (matches 2024-05-12 14:30:00)
            "Not a date at all",     # invalid text
            "",                      # empty string
        ]
    }
    df = pd.DataFrame(raw_data)
    
    cleaned_df, quarantine_mask = clean_dates(df, formats)
    
    # The first 6 should be successfully parsed
    assert quarantine_mask.iloc[:6].sum() == 0, "Valid dates were quarantined"
    
    # The last 2 should be quarantined
    assert quarantine_mask.iloc[6:].all(), "Invalid dates were not quarantined"
    
    # Verify the parsed datetimes are correct
    expected_dt = pd.Timestamp("2024-05-12 14:30:00")
    for i in range(6):
        assert cleaned_df["txn_timestamp"].iloc[i] == expected_dt, f"Failed to parse row {i} correctly"

    # Verify unparseable rows have NaT
    assert pd.isna(cleaned_df["txn_timestamp"].iloc[6])
    assert pd.isna(cleaned_df["txn_timestamp"].iloc[7])
