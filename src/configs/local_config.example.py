# local_config.py — machine-specific settings (gitignored)
#
# Copy this file to src/configs/local_config.py and fill in the values for this machine.
# This file is never pushed to git, so each machine keeps its own copy permanently.
# Values here override the matching keys in config.py at startup.

LOCAL_CONFIG = {
    # ── COM ports ─────────────────────────────────────────────────────────────
    "dry_mfc_port":    "COM6",   # Vögtlin dry-air MFC
    "wet_mfc_port":    "COM7",   # Vögtlin wet-air MFC
    "hygrometer_port": "COM9",   # DewMaster hygrometer
    "chiller_port":    "COM8",   # Julabo chiller

    # ── Baud rates ────────────────────────────────────────────────────────────
    "mfc_baudrate":        9600,
    "hygrometer_baudrate": 19200,
    "chiller_baudrate":    9600,

    # ── Modbus addresses ──────────────────────────────────────────────────────
    "dry_mfc_address": 1,
    "wet_mfc_address": 247,

    # ── Enable / disable devices ──────────────────────────────────────────────
    "dry_mfc_enabled":    True,
    "wet_mfc_enabled":    True,
    "hygrometer_enabled": True,
    "chiller_enabled":    True,
}
