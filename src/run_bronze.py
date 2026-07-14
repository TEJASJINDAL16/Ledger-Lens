"""Bronze stage runner.

Executes the Phase 2 Bronze gate: ingests raw data, applies the Bronze
schema, quarantines structural failures (drift, impossible dates), and
logs the pass/fail counts.
"""

import logging
import sys

from src.config import PROJECT_ROOT, load_config, setup_logging
from src.ingest import ingest_raw_data
from src.validate.quarantine import enforce_and_quarantine
from src.validate.schemas import BronzeSchema

log = logging.getLogger(__name__)


def main() -> None:
    cfg = load_config()
    setup_logging(str(PROJECT_ROOT / cfg["paths"]["log_dir"]))
    
    log.info("Starting Bronze stage")
    
    # 1. Ingest all-string raw data
    df_raw = ingest_raw_data(cfg)
    total_raw = len(df_raw)
    
    # 2. Enforce Bronze gate and quarantine rejects
    quarantine_path = cfg["paths"]["quarantine_dir"] + "/bronze_rejects.csv"
    df_bronze = enforce_and_quarantine(
        df=df_raw,
        schema=BronzeSchema,
        quarantine_path=quarantine_path,
        stage_name="Bronze"
    )
    
    passed_count = len(df_bronze)
    quarantined_count = total_raw - passed_count
    
    # Verify conservation of rows
    if passed_count + quarantined_count != total_raw:
        log.error("Row conservation failure: %d (pass) + %d (quarantine) != %d (total)",
                  passed_count, quarantined_count, total_raw)
        sys.exit(1)
        
    log.info("Bronze stage complete. %d passed, %d quarantined.", passed_count, quarantined_count)


if __name__ == "__main__":
    main()
