"""Data profiling module.

Generates a simple exploratory data analysis HTML report using pandas
describe(). We bypass ydata-profiling here to maintain pipeline velocity 
due to environment incompatibilities (Python 3.14).
"""

import logging

from src.config import PROJECT_ROOT, load_config, setup_logging
from src.ingest import ingest_raw_data

log = logging.getLogger(__name__)


def profile_raw_data(cfg: dict) -> None:
    """Generate and save an HTML profiling report of the raw data.
    
    Args:
        cfg: The parsed pipeline configuration dictionary.
    """
    df = ingest_raw_data(cfg)
    
    log.info("Generating basic pandas profile report on %d rows...", len(df))
    
    # Generate a simple HTML report describing the raw strings
    html_content = f"<h1>LedgerLens Raw Data Profile</h1><br>{df.describe().to_html()}"
    
    out_path = PROJECT_ROOT / cfg["paths"]["profile_html"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    
    log.info("Saved simple profiling report to %s", out_path)


def main() -> None:
    cfg = load_config()
    setup_logging(str(PROJECT_ROOT / cfg["paths"]["log_dir"]))
    profile_raw_data(cfg)


if __name__ == "__main__":
    main()
