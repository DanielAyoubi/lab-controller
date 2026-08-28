import json
from pathlib import Path


def default_config_path() -> Path:
    """The config.json shipped in the source tree."""
    return Path(__file__).resolve().parents[1] / "configs" / "config.json"


def apply_settings(config: dict, logger, pid) -> None:
    """Push the (already merged) config into the logger and PID controller."""
    logger.output_dir = Path(config.get("log_dir", "data"))
    logger.filename_prefix = config.get("log_prefix", "nsim_log")
    logger.output_dir.mkdir(parents=True, exist_ok=True)
    pid.update_params(config)


def save_config_to_file(config: dict, dest_path) -> None:
    """Write the whole config back to disk as plain JSON."""
    Path(dest_path).write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
