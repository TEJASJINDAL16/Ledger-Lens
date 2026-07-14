"""Quarantine handler for data validation.

Intercepts Pandera validation errors, isolates the failing rows,
annotates them with the rejection reason, and writes them to the
quarantine directory. The passing rows are returned to continue
down the pipeline.
"""

import logging
from pathlib import Path

import pandas as pd
import pandera as pa
from pandera.errors import SchemaErrors

from src.config import PROJECT_ROOT

log = logging.getLogger(__name__)


def enforce_and_quarantine(
    df: pd.DataFrame, 
    schema: pa.DataFrameSchema, 
    quarantine_path: str,
    stage_name: str,
) -> pd.DataFrame:
    """Validate DataFrame against a schema and quarantine failures.
    
    Args:
        df: The DataFrame to validate.
        schema: The Pandera schema to enforce.
        quarantine_path: Where to save the rejected rows (relative to PROJECT_ROOT).
        stage_name: Name of the pipeline stage (e.g., "bronze", "silver").
        
    Returns:
        DataFrame containing only the rows that passed validation.
    """
    try:
        # lazy=True collects all errors instead of raising on the first one
        valid_df = schema.validate(df, lazy=True)
        log.info("[%s] All %d rows passed validation", stage_name, len(valid_df))
        return valid_df
        
    except SchemaErrors as err:
        failure_cases = err.failure_cases
        
        # Identify the indices of all failing rows
        # Pandas indices might be duplicated or non-sequential if we didn't reset_index,
        # but the failure_cases 'index' column corresponds to the DataFrame index.
        failing_indices = failure_cases["index"].dropna().unique()
        
        # Build the quarantine dataframe
        quarantine_df = df.loc[failing_indices].copy()
        
        # Map indices to their failure reasons
        # A row might fail multiple checks; we combine the reasons
        reasons = failure_cases.groupby("index")["check"].apply(lambda x: " | ".join(x))
        quarantine_df["reject_reason"] = quarantine_df.index.map(reasons)
        
        # The good rows are the ones NOT in the failing indices
        valid_df = df.drop(index=failing_indices)
        
        # Save quarantined rows
        out_path = PROJECT_ROOT / quarantine_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        quarantine_df.to_csv(out_path, index=False)
        
        log.warning(
            "[%s] Validation caught %d failed rows. Quarantined to %s",
            stage_name, len(quarantine_df), out_path.name
        )
        log.info("[%s] %d rows passed validation and continue", stage_name, len(valid_df))
        
        return valid_df
