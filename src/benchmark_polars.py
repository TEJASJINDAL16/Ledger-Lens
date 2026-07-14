"""Pandas vs Polars Benchmark (Phase 7).

Benchmarks a heavy data transformation (amount parsing) in Pandas
vs Polars to demonstrate performance awareness.
"""

import time
import logging
import pandas as pd
import polars as pl
from tabulate import tabulate

from src.config import load_config, setup_logging, PROJECT_ROOT
from src.clean.parse_amounts import clean_amounts

log = logging.getLogger(__name__)


def benchmark():
    cfg = load_config()
    setup_logging(str(PROJECT_ROOT / cfg["paths"]["log_dir"]))
    
    raw_path = PROJECT_ROOT / cfg["paths"]["raw_csv"]
    
    log.info("Loading raw data for benchmark...")
    
    # ---------------------------------------------------------
    # Pandas Benchmark
    # ---------------------------------------------------------
    start_pd_load = time.time()
    df_pd = pd.read_csv(raw_path, dtype=str)
    load_pd_time = time.time() - start_pd_load
    
    log.info("Running Pandas amount parsing...")
    start_pd_calc = time.time()
    df_pd_clean, _ = clean_amounts(df_pd)
    calc_pd_time = time.time() - start_pd_calc
    
    # ---------------------------------------------------------
    # Polars Benchmark
    # ---------------------------------------------------------
    start_pl_load = time.time()
    df_pl = pl.read_csv(raw_path, schema_overrides={"amount": pl.Utf8})
    load_pl_time = time.time() - start_pl_load
    
    log.info("Running Polars amount parsing...")
    start_pl_calc = time.time()
    
    # Replicate the logic: strip whitespace, remove commas and symbols, handle parenthesis
    df_pl_clean = df_pl.with_columns(
        pl.col("amount")
        .str.strip_chars()
        .str.replace_all(r"[,₹$€£]", "")
        .str.replace(r"^\((.*)\)$", "-$1")
        .cast(pl.Float64, strict=False)
        .alias("amount_parsed")
    )
    
    # Force execution
    _ = df_pl_clean.head()
    calc_pl_time = time.time() - start_pl_calc
    
    # ---------------------------------------------------------
    # Report
    # ---------------------------------------------------------
    speedup = calc_pd_time / calc_pl_time if calc_pl_time > 0 else 0
    
    table = [
        ["Pandas", f"{load_pd_time:.3f}s", f"{calc_pd_time:.3f}s"],
        ["Polars", f"{load_pl_time:.3f}s", f"{calc_pl_time:.3f}s"],
    ]
    
    headers = ["Engine", "I/O Load Time", "Compute Time (Amount Parsing)"]
    print("\n" + tabulate(table, headers, tablefmt="github") + "\n")
    print(f"Result: Polars compute is {speedup:.1f}x faster than Pandas.")
    
    # We could write this to a file if needed, but printing is sufficient for the spec.

if __name__ == "__main__":
    benchmark()
