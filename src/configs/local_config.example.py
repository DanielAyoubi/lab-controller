# local_config.py — machine-specific settings (gitignored)
#
# Copy this file to src/configs/local_config.py and set the correct COM ports for this machine.
# This file is never pushed to git, so each machine keeps its own copy permanently.
#
# COM ports are NOT defined in config.py — this is the only place to set them.

LOCAL_CONFIG = {
    "dry_mfc_port": "COM6",
    "wet_mfc_port": "COM7",
    "hygrometer_port": "COM9",
    "chiller_port": "COM8",
}
