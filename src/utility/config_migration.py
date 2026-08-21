"""One-shot migration from the old flat config keys to the ``devices`` list.

Before the modular rewrite, ``config.json`` described exactly five devices
through flat keys (``dry_mfc_port``, ``hygrometer_enabled``, …). This module
converts such a file into the new ``devices`` array on first load, preserving
the previous behaviour exactly: the same ports, addresses and enabled flags,
with the roles the hardcoded controller used to imply.

Ids are hand-picked here (rather than slugified from the tag) so the CSV column
prefixes are readable and never collide with a legacy alias column — see
``registry.RESERVED_COLUMNS``.
"""

from typing import Dict, List

from src.devices import registry as reg

# (id, tag, type, role, legacy key prefix, extra legacy keys)
_LEGACY_DEVICES = [
    ("dry_mfc", "Dry MFC", "vogtlin_mfc", reg.ROLE_DRY_FLOW, "dry_mfc",
     {"baudrate": "mfc_baudrate", "address": "dry_mfc_address"}),
    ("wet_mfc", "Wet MFC", "vogtlin_mfc", reg.ROLE_WET_FLOW, "wet_mfc",
     {"baudrate": "mfc_baudrate", "address": "wet_mfc_address"}),
    ("hygro", "Hygrometer", "dewmaster_hygrometer", reg.ROLE_RH_SOURCE, "hygrometer",
     {"baudrate": "hygrometer_baudrate"}),
    ("julabo", "Chiller", "julabo_chiller", reg.ROLE_TEMP_SOURCE, "chiller",
     {"baudrate": "chiller_baudrate"}),
    ("firesting", "O2", "firesting_o2", reg.ROLE_O2_SOURCE, "firesting",
     {"baudrate": "firesting_baudrate"}),
    # The Vaisala probe was configured but never wired into the controller, so
    # it migrates as a monitor-only device rather than stealing the RH role.
    ("vaisala", "Vaisala RH", "vaisala_rh", reg.ROLE_NONE, "vaisala_RH",
     {"baudrate": "vaisala_RH_baudrate"}),
]


def needs_migration(config: dict) -> bool:
    return not isinstance(config.get("devices"), list)


def migrate(config: dict) -> List[Dict]:
    """Build a ``devices`` list from the legacy flat keys.

    Only devices whose port key is present are carried over — that was already
    the gate ``connect_devices()`` used. Returns the new list (also written into
    ``config["devices"]``).
    """
    devices: List[Dict] = []
    for dev_id, tag, type_key, role, prefix, extra in _LEGACY_DEVICES:
        port_key = f"{prefix}_port"
        if port_key not in config:
            continue
        dtype = reg.DEVICE_TYPES[type_key]
        spec = {
            "id": dev_id,
            "type": type_key,
            "tag": tag,
            "role": role,
            "enabled": bool(config.get(f"{prefix}_enabled", True)),
            "port": config[port_key],
        }
        for field_key, default in dtype.defaults().items():
            if field_key == "port":
                continue
            legacy_key = extra.get(field_key)
            spec[field_key] = config.get(legacy_key, default) if legacy_key else default
        devices.append(spec)

    # A legacy rig had one probe/chiller/O2 meter each, so the roles above are
    # already right; this only matters if a device was missing from the file.
    reg.assign_default_roles(devices)
    config["devices"] = devices
    return devices
