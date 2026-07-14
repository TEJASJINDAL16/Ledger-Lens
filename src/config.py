"""Central configuration loader.

Reads config/pipeline.yaml once. All other modules import load_config()
and receive the parsed dict — no module reads the YAML independently.
"""

import logging
import pathlib
from datetime import datetime

import yaml

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_config() -> dict:
    """Parse config/pipeline.yaml and return the full config dict."""
    config_path = PROJECT_ROOT / "config" / "pipeline.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def setup_logging(log_dir: str | None = None) -> None:
    """Configure stdlib logging to a timestamped file and stdout.

    Called once at each entrypoint (make_clean, corrupt, run_pipeline).
    """
    if log_dir is None:
        log_dir = str(PROJECT_ROOT / "logs")
    pathlib.Path(log_dir).mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(f"{log_dir}/run_{timestamp}.log"),
            logging.StreamHandler(),
        ],
        force=True,
    )
