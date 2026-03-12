from pathlib import Path

def apply_settings(config: dict, new_config: dict, logger, pid) -> None:
    config.update(new_config)
    logger.output_dir = Path(config.get("log_dir", "data"))
    logger.filename_prefix = config.get("log_prefix", "nsim_log")
    logger.output_dir.mkdir(parents=True, exist_ok=True)
    pid.update_params(config)
