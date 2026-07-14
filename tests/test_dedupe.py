"""Tests for deduplication logic."""

import pandas as pd
import pytest

from src.clean.dedupe import handle_duplicates


def test_handle_duplicates():
    """Verify that exact duplicates are dropped and near duplicates are flagged."""
    cfg = {"near_dup_window_seconds": 120, "paths": {"log_dir": "logs"}}
    
    # 5 rows total:
    # 0 & 1 are exact dupes
    # 2 & 3 are near dupes (same account/merchant/amount, 90 seconds apart)
    # 4 is totally normal
    
    raw_data = {
        "transaction_id": ["id1", "id2", "id3", "id4", "id5"],
        "account_id": ["A1", "A1", "A2", "A2", "A3"],
        "merchant_id": ["M1", "M1", "M2", "M2", "M3"],
        "amount_inr": [100.0, 100.0, 50.0, 50.0, 20.0],
        "txn_timestamp": [
            pd.Timestamp("2024-01-01 10:00:00"),
            pd.Timestamp("2024-01-01 10:00:00"),
            pd.Timestamp("2024-01-01 11:00:00"),
            pd.Timestamp("2024-01-01 11:01:30"),  # 90 seconds later -> near dupe
            pd.Timestamp("2024-01-01 12:00:00"),
        ],
        "mcc_imputed_flag": [False, False, False, False, False],
        "descriptor_clean": ["D1", "D1", "D2", "D2", "D3"],
        "match_method": ["exact", "exact", "exact", "exact", "exact"],
        "match_confidence": [1.0, 1.0, 1.0, 1.0, 1.0],
    }
    
    df = pd.DataFrame(raw_data)
    
    processed = handle_duplicates(df, cfg)
    
    # Should have dropped 1 exact duplicate (row 1)
    assert len(processed) == 4, "Exact duplicate was not dropped"
    
    # Check that near dupes are flagged correctly
    # Rows with account A2 are near dupes
    near_dupes = processed[processed["is_near_duplicate"]]
    assert len(near_dupes) == 2, "Near duplicates were not flagged correctly"
    assert (near_dupes["account_id"] == "A2").all()
    
    # The normal row and the remaining exact dupe shouldn't be flagged as near dupes
    normal_rows = processed[~processed["is_near_duplicate"]]
    assert len(normal_rows) == 2
    assert "A1" in normal_rows["account_id"].values
    assert "A3" in normal_rows["account_id"].values
