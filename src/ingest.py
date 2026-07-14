"""Data ingestion module.

Reads raw CSV data exactly as it arrived, enforcing all-string ingestion
(dtype=str) to prevent pandas from prematurely guessing types and mangling
messy strings. Every row is preserved at this stage.
"""

import logging

import pandas as pd

from src.config import PROJECT_ROOT, load_config

log = logging.getLogger(__name__)


def ingest_raw_data(cfg: dict) -> pd.DataFrame:
    """Read the raw transaction CSV as strings.
    
    Args:
        cfg: The parsed pipeline configuration dictionary.
        
    Returns:
        DataFrame containing the raw, untyped strings.
    """
    raw_path = PROJECT_ROOT / cfg["paths"]["raw_csv"]
    log.info("Ingesting raw data from %s (dtype=str)", raw_path)
    
    # Read everything as string to prevent early type casting errors
    df = pd.read_csv(raw_path, dtype=str)
    
    # Fill actual nulls (e.g. from empty trailing commas) with empty string 
    # to maintain the all-string contract
    df = df.fillna("")
    
    log.info("Ingested %d rows, %d columns", len(df), len(df.columns))
    return df
