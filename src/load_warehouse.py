"""DuckDB Warehouse loader (Phase 6).

Loads the Silver dataset into a DuckDB warehouse, creating a Star Schema
by executing the SQL files in sql/.
"""

import logging
import duckdb
from pathlib import Path

from src.config import load_config, setup_logging, PROJECT_ROOT

log = logging.getLogger(__name__)


def main():
    cfg = load_config()
    setup_logging(str(PROJECT_ROOT / cfg["paths"]["log_dir"]))
    
    db_path = PROJECT_ROOT / cfg["paths"]["warehouse_db"]
    silver_path = PROJECT_ROOT / cfg["paths"]["silver_parquet"]
    
    log.info("Starting Gold stage (Warehouse Load)")
    
    if not silver_path.exists():
        log.error("Silver parquet not found at %s. Run the pipeline first.", silver_path)
        return
        
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Connect to DuckDB
    con = duckdb.connect(str(db_path))
    
    try:
        # Load silver parquet into a temporary view
        log.info("Mounting silver.parquet as stg_transactions")
        con.execute(f"CREATE OR REPLACE VIEW stg_transactions AS SELECT * FROM read_parquet('{silver_path}')")
        
        # Execute SQL scripts in order
        sql_dir = PROJECT_ROOT / "sql"
        sql_files = ["01_dims.sql", "02_fct_transactions.sql", "03_insights.sql"]
        
        for file in sql_files:
            file_path = sql_dir / file
            if file_path.exists():
                log.info("Executing %s...", file)
                sql_script = file_path.read_text()
                con.execute(sql_script)
            else:
                log.warning("SQL script %s not found.", file)
                
        log.info("Warehouse loaded successfully!")
        
        # Verify the top merchants view
        res = con.execute("SELECT * FROM v_top_merchants_before_after").df()
        log.info("Top Merchants Before vs After view contains %d rows.", len(res))
        
    finally:
        con.close()

if __name__ == "__main__":
    main()
