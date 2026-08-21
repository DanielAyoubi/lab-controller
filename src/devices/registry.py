"""Device type registry — the single source of truth for the modular setup.

The user declares their rig in ``config.json`` as a list of device specs::

    {"id": "wet_mfc", "type": "vogtlin_mfc", "tag": "Wet MFC",
     "role": "wet_flow", "enabled": true, "port": "COM4", "address": 1}

Everything downstream is *generated* from that list plus the type descriptions
here: the Settings form rows, the driver instances, the plot panels and legend
labels, and the CSV columns. Adding support for a new instrument means adding a
driver plus one ``DeviceType`` entry — no changes to the controller or GUI.

Two orthogonal ideas, deliberately kept apart:

* **tag**  — free-text display name. Drives legend/widget labels and the CSV
  column prefix (via the stable ``id`` slug derived from it). Cosmetic.
* **role** — fixed enum. Drives *behaviour*: which MFC the RH loop moves, which
  probe it reads back, and which columns additionally get the legacy canonical
  names so existing analysis scripts keep working. At most one device per role;
  ``none`` devices are still connected, plotted and logged.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.devices.chillers import JulaboChiller
from src.devices.mass_flow_controllers import VogtlinMFC
from src.devices.O2_monitors import FireStingO2
from src.devices.RH_probes import EdgeTechHygrometer, VaisalaRHProbe

# Keeps the Settings UI (and the poll loop) sane on a single serial host.
MAX_PER_TYPE = 8

# Plot panels, top to bottom. The values are the ``Channel.panel`` keys.
PANEL_FLOW = "flow"
PANEL_TEMPERATURE = "temperature"
PANEL_PERCENT = "percent"

# (key, title, y-axis label)
PANELS: Tuple[Tuple[str, str, str], ...] = (
    (PANEL_FLOW, "Flows", "Flow (L/min)"),
    (PANEL_TEMPERATURE, "Temperature", "Temp (°C)"),
    (PANEL_PERCENT, "Percentages", "%"),
)


# ── Roles ─────────────────────────────────────────────────────────────────────

ROLE_NONE = "none"
ROLE_WET_FLOW = "wet_flow"
ROLE_DRY_FLOW = "dry_flow"
ROLE_RH_SOURCE = "rh_source"
ROLE_TEMP_SOURCE = "temp_source"
ROLE_O2_SOURCE = "o2_source"

ROLE_LABELS: Dict[str, str] = {
    ROLE_NONE: "— none (monitor only)",
    ROLE_WET_FLOW: "Wet flow",
    ROLE_DRY_FLOW: "Dry flow",
    ROLE_RH_SOURCE: "RH source",
    ROLE_TEMP_SOURCE: "Temperature source",
    ROLE_O2_SOURCE: "O₂ source",
}

# What holding an implied role actually *does*, for the Settings checkbox.
# Every device measures and logs independently regardless of its role — the
# role only picks which reading the control loop acts on and which device fills
# the fixed-name columns that analysis scripts expect.
ROLE_DUTIES: Dict[str, str] = {
    ROLE_RH_SOURCE: "Use this probe's reading for RH control",
    ROLE_TEMP_SOURCE: "Use this temperature for RH calculations",
    ROLE_O2_SOURCE: "Use this meter for the standard O₂ column",
}

# (role, channel) -> legacy canonical CSV column. These are the names the old
# fixed schema used; emitting them keeps calibrate_feedforward.py, plot_saver
# and existing analysis notebooks working against the new dynamic logs.
ROLE_ALIASES: Dict[str, Dict[str, str]] = {
    ROLE_WET_FLOW: {"flow": "wet_flow", "setpoint": "wet_flow_setpoint"},
    ROLE_DRY_FLOW: {"flow": "dry_flow", "setpoint": "dry_flow_setpoint"},
    ROLE_RH_SOURCE: {"dewpoint": "dewpoint_temp", "temp": "hygrometer_temp",
                     "rh": "rh_probe"},
    ROLE_TEMP_SOURCE: {"temp": "chiller_temp", "setpoint": "chiller_setpoint"},
    ROLE_O2_SOURCE: {"oxygen": "oxygen"},
}


# ── Type descriptions ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Channel:
    """One value a device produces per poll."""
    key: str              # what driver.read() keys it by
    label: str            # legend becomes f"{tag} {label}"
    unit: str
    panel: str
    dashed: bool = False  # setpoint traces are drawn dashed


@dataclass(frozen=True)
class Field:
    """One editable connection parameter, rendered as a row in Settings."""
    key: str
    label: str
    kind: str             # "text" | "int"
    default: Any
    minimum: int = 0
    maximum: int = 0


@dataclass(frozen=True)
class DeviceType:
    """A supported instrument.

    ``natural_role`` is the only role this type can meaningfully take: an RH
    probe measures RH, a chiller provides a temperature, an O₂ meter measures
    O₂. For those types the role is not a question worth asking the user — it
    is assigned automatically, and the only remaining choice (when several of
    the same type are fitted, e.g. probes before and after a flow cell) is
    *which* one is primary. An MFC is the exception: wet vs dry cannot be
    inferred, so it declares ``natural_role = None`` and offers a real choice
    through ``allowed_roles``.
    """
    key: str
    # Shown in the add-device picker and the card header, and used as the
    # default tag for a new device — which in turn seeds its CSV column prefix.
    # Keep it short: "Vaisala", not "Vaisala HMP110 RH probe".
    label: str
    factory: Callable[[dict], Any]
    channels: Tuple[Channel, ...]
    fields: Tuple[Field, ...]
    natural_role: Optional[str] = None
    allowed_roles: Tuple[str, ...] = ()
    caps: frozenset = field(default_factory=frozenset)

    @property
    def role_is_a_choice(self) -> bool:
        """True when the user must pick the role (MFCs), False when implied."""
        return self.natural_role is None

    def roles(self) -> Tuple[str, ...]:
        if self.natural_role is not None:
            return (ROLE_NONE, self.natural_role)
        return self.allowed_roles

    def defaults(self) -> Dict[str, Any]:
        return {f.key: f.default for f in self.fields}

    def channel_keys(self) -> set:
        return {c.key for c in self.channels}


_PORT = Field("port", "Port", "text", "COM1")


def _baud(default: int = 9600) -> Field:
    return Field("baudrate", "Baudrate", "int", default, 1200, 115200)


DEVICE_TYPES: Dict[str, DeviceType] = {
    "vogtlin_mfc": DeviceType(
        key="vogtlin_mfc",
        label="Vögtlin MFC",
        factory=lambda s: VogtlinMFC(
            port=s.get("port", ""),
            address=int(s.get("address", 1)),
            baudrate=int(s.get("baudrate", 9600)),
            name=s.get("tag", "MFC"),
        ),
        channels=(
            Channel("flow", "Flow", "L/min", PANEL_FLOW),
            Channel("setpoint", "Setpoint", "L/min", PANEL_FLOW, dashed=True),
        ),
        fields=(_PORT, _baud(9600),
                Field("address", "Modbus address", "int", 1, 1, 247)),
        allowed_roles=(ROLE_NONE, ROLE_WET_FLOW, ROLE_DRY_FLOW),
        caps=frozenset({"flow_setpoint"}),
    ),
    "dewmaster_hygrometer": DeviceType(
        key="dewmaster_hygrometer",
        label="DewMaster",
        factory=lambda s: EdgeTechHygrometer(
            port=s.get("port", ""),
            baudrate=int(s.get("baudrate", 19200)),
            name=s.get("tag", "DewMaster"),
        ),
        channels=(
            Channel("dewpoint", "Dewpoint", "°C", PANEL_TEMPERATURE),
            Channel("temp", "Temp", "°C", PANEL_TEMPERATURE),
        ),
        fields=(_PORT, _baud(19200)),
        natural_role=ROLE_RH_SOURCE,
    ),
    "vaisala_rh": DeviceType(
        key="vaisala_rh",
        label="Vaisala",
        factory=lambda s: VaisalaRHProbe(
            port=s.get("port", ""),
            slave_addr=int(s.get("address", 240)),
            baudrate=int(s.get("baudrate", 19200)),
            name=s.get("tag", "Vaisala"),
        ),
        channels=(
            Channel("rh", "RH", "%", PANEL_PERCENT),
            Channel("temp", "Temp", "°C", PANEL_TEMPERATURE),
            Channel("dewpoint", "Dewpoint", "°C", PANEL_TEMPERATURE),
        ),
        fields=(_PORT, _baud(19200),
                Field("address", "Modbus address", "int", 240, 1, 247)),
        natural_role=ROLE_RH_SOURCE,
    ),
    "julabo_chiller": DeviceType(
        key="julabo_chiller",
        label="Julabo",
        factory=lambda s: JulaboChiller(
            port=s.get("port", ""),
            baudrate=int(s.get("baudrate", 9600)),
            name=s.get("tag", "Julabo"),
        ),
        channels=(
            Channel("temp", "Temp", "°C", PANEL_TEMPERATURE),
            Channel("setpoint", "Setpoint", "°C", PANEL_TEMPERATURE, dashed=True),
        ),
        fields=(_PORT, _baud(9600)),
        natural_role=ROLE_TEMP_SOURCE,
        caps=frozenset({"temp_setpoint"}),
    ),
    "firesting_o2": DeviceType(
        key="firesting_o2",
        label="FireSting",
        factory=lambda s: FireStingO2(
            port=s.get("port", ""),
            baudrate=int(s.get("baudrate", 19200)),
            name=s.get("tag", "FireSting"),
        ),
        channels=(Channel("oxygen", "O₂", "%", PANEL_PERCENT),),
        fields=(_PORT, _baud(19200)),
        natural_role=ROLE_O2_SOURCE,
    ),
}


# ── Derived series ────────────────────────────────────────────────────────────

# Columns the controller computes rather than reads. Each names the roles it
# needs, so it is only logged/plotted when those roles are actually assigned.
DERIVED_SERIES: Tuple[Dict[str, Any], ...] = (
    # Only worth computing for a dew-point-only probe (the DewMaster). A probe
    # that reports RH directly (Vaisala) already gives this exact quantity on
    # its own `rh` channel — deriving it again from that probe's dew point and
    # temperature just draws the same curve twice.
    {"column": "rh_hygrometer", "panel": PANEL_PERCENT,
     "requires": (ROLE_RH_SOURCE,), "label": "RH (probe T)",
     "redundant_if_source_reports": "rh"},
    {"column": "rh_chiller", "panel": PANEL_PERCENT,
     "requires": (ROLE_RH_SOURCE, ROLE_TEMP_SOURCE), "label": "RH (external T)"},
    {"column": "rh_chiller_calibrated", "panel": PANEL_PERCENT,
     "requires": (ROLE_RH_SOURCE, ROLE_TEMP_SOURCE),
     "label": "RH (external T, calib.)"},
)


# ── Helpers over a device-spec list ───────────────────────────────────────────

# Every column name the legacy/derived schema owns. A device id must never
# generate one of these: the alias is written by whichever device holds the
# role, so a same-named per-device column would silently overwrite it.
RESERVED_COLUMNS = frozenset(
    [a for aliases in ROLE_ALIASES.values() for a in aliases.values()]
    + [d["column"] for d in DERIVED_SERIES]
    + ["timestamp"]
)


def slugify(tag: str, taken: Optional[List[str]] = None) -> str:
    """Stable, unique, CSV-safe id derived from a tag.

    Accents are folded rather than dropped, so "Vögtlin MFC" becomes
    ``vogtlin_mfc`` instead of ``v_gtlin_mfc``.
    """
    folded = unicodedata.normalize("NFKD", tag or "device")
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    base = re.sub(r"[^a-z0-9]+", "_", folded.lower()).strip("_") or "device"
    taken = taken or []
    if base not in taken:
        return base
    n = 2
    while f"{base}_{n}" in taken:
        n += 1
    return f"{base}_{n}"


def make_id(tag: str, taken: Optional[List[str]] = None) -> str:
    """Unique runtime id for a new device.

    The id is the device's *identity* — health tracking, widget keys, role
    lookups — and is assigned once at creation. It is deliberately not the CSV
    column prefix (that comes from the tag, see :func:`column_prefixes`), so it
    never has to change and nothing breaks when a device is renamed.
    """
    return slugify(tag, list(taken or []))


def get_type(spec: dict) -> Optional[DeviceType]:
    return DEVICE_TYPES.get(spec.get("type", ""))


def require_type(spec: dict) -> DeviceType:
    """Type of a spec already known to be valid.

    Use after ``enabled_specs()`` or ``role_holder()``, both of which filter out
    unknown types — this states that invariant instead of re-checking it.
    """
    dtype = get_type(spec)
    if dtype is None:
        raise KeyError(f"Unknown device type {spec.get('type')!r} "
                       f"for device {spec.get('id')!r}")
    return dtype


def enabled_specs(specs: List[dict]) -> List[dict]:
    return [s for s in (specs or []) if s.get("enabled", True) and get_type(s)]


def role_holder(specs: List[dict], role: str) -> Optional[dict]:
    """First enabled device holding ``role`` (roles are unique by construction)."""
    for s in enabled_specs(specs):
        if s.get("role") == role:
            return s
    return None


def assign_default_roles(specs: List[dict]) -> List[dict]:
    """Fill in the roles the user should never have to think about.

    An RH probe is always the RH source, a chiller always the temperature
    source, an O₂ meter always the O₂ source. So for every such role that no
    enabled device currently holds, hand it to the first enabled device that
    can take it. Extra devices of the same type — a second probe after the flow
    cell, say — keep ``role: none`` and are logged and plotted under their tag.

    MFCs are untouched: wet vs dry is a genuine choice that cannot be inferred.
    Mutates and returns ``specs``.
    """
    for role in (ROLE_RH_SOURCE, ROLE_TEMP_SOURCE, ROLE_O2_SOURCE):
        holders = [s for s in specs if s.get("role") == role and get_type(s)]
        # Exactly one spec may carry an implied role, and it must be a live one:
        # otherwise disabling the holder would leave the role stranded on a
        # device that is not being read, and re-enabling it later would produce
        # two claimants.
        keep = next((s for s in holders if s.get("enabled", True)), None)
        for spec in holders:
            if spec is not keep:
                spec["role"] = ROLE_NONE
        if keep is not None:
            continue
        for spec in enabled_specs(specs):
            if require_type(spec).natural_role == role:
                spec["role"] = role
                break
    return specs


def column_prefixes(specs: List[dict]) -> Dict[str, str]:
    """Map device id -> CSV column prefix, derived from each device's **tag**.

    The tag is what the user reads in the plot and the controls, so it is also
    what the log columns are named after: tag "RH before cell" gives
    ``rh_before_cell_rh``. Renaming a device therefore renames its columns —
    intentional, but it means a rename mid-run changes the log schema, so
    callers holding an open log must reopen it (see ``MainWindow.open_settings``).

    ``id`` stays the runtime identity (health tracking, widget keys, role
    lookups) and is unaffected by renames.

    Two guards, applied in config order so the result is deterministic:
    prefixes are de-duplicated against each other, and never allowed to collide
    with a reserved legacy column (a device tagged "Wet" must not generate
    ``wet_flow`` and silently overwrite the role-holder's alias).
    """
    prefixes: Dict[str, str] = {}
    taken: List[str] = []
    for spec in enabled_specs(specs):
        dtype = require_type(spec)
        prefix = slugify(spec.get("tag") or spec["id"], taken)
        while any(f"{prefix}_{c.key}" in RESERVED_COLUMNS for c in dtype.channels):
            prefix = slugify(f"{prefix}_dev", taken)
        taken.append(prefix)
        prefixes[spec["id"]] = prefix
    return prefixes


def column_name(spec: dict, channel_key: str,
                prefixes: Optional[Dict[str, str]] = None) -> str:
    """CSV column for one device channel. Pass ``prefixes`` from
    :func:`column_prefixes` so uniqueness is resolved across the whole set."""
    if prefixes is not None and spec["id"] in prefixes:
        return f"{prefixes[spec['id']]}_{channel_key}"
    return f"{slugify(spec.get('tag') or spec['id'])}_{channel_key}"


def alias_for(spec: dict, channel_key: str) -> Optional[str]:
    """Legacy canonical column this device/channel also writes, if any."""
    return ROLE_ALIASES.get(spec.get("role", ROLE_NONE), {}).get(channel_key)


def build_manifest(specs: List[dict]) -> List[Dict[str, Any]]:
    """Plottable series for the current setup.

    One entry per (device, channel) plus the derived RH columns. The legacy
    alias columns are deliberately *not* included — they duplicate the
    per-device columns and would draw every role-holder's line twice.
    """
    manifest: List[Dict[str, Any]] = []
    prefixes = column_prefixes(specs)
    for spec in enabled_specs(specs):
        dtype = require_type(spec)
        tag = spec.get("tag", spec["id"])
        for ch in dtype.channels:
            manifest.append({
                "column": column_name(spec, ch.key, prefixes),
                "label": f"{tag} {ch.label}",
                "panel": ch.panel,
                "dashed": ch.dashed,
                # All of a device's channels share one group, so a renderer can
                # give them one colour and distinguish flow from setpoint by
                # line style — see src/utility/series_style.py.
                "group": spec["id"],
            })

    holders = {
        ROLE_RH_SOURCE: role_holder(specs, ROLE_RH_SOURCE),
        ROLE_TEMP_SOURCE: role_holder(specs, ROLE_TEMP_SOURCE),
    }
    rh_src = holders[ROLE_RH_SOURCE]
    if rh_src is None:
        return manifest   # every derived series is computed from the RH source
    rh_channels = require_type(rh_src).channel_keys()
    for d in DERIVED_SERIES:
        if any(holders.get(r) is None for r in d["requires"]):
            continue
        if d.get("redundant_if_source_reports") in rh_channels:
            continue
        manifest.append({
            "column": d["column"],
            "label": f"{rh_src.get('tag', 'RH')} — {d['label']}",
            "panel": d["panel"],
            "dashed": False,
            # Each derived column is its own quantity, not another channel of
            # the probe, so it gets its own colour rather than the source's.
            "group": f"derived:{d['column']}",
        })
    return manifest


def build_log_fields(specs: List[dict]) -> List[str]:
    """CSV columns: timestamp, legacy aliases, derived, then per-device."""
    fields = ["timestamp"]

    # Legacy canonical names, in the order the old fixed schema used them.
    legacy_order = [
        (ROLE_DRY_FLOW, "flow"), (ROLE_WET_FLOW, "flow"),
        (ROLE_DRY_FLOW, "setpoint"), (ROLE_WET_FLOW, "setpoint"),
        (ROLE_RH_SOURCE, "temp"), (ROLE_RH_SOURCE, "dewpoint"),
        (ROLE_RH_SOURCE, "rh"),
        (ROLE_TEMP_SOURCE, "temp"), (ROLE_TEMP_SOURCE, "setpoint"),
        (ROLE_O2_SOURCE, "oxygen"),
    ]
    for role, ch_key in legacy_order:
        holder = role_holder(specs, role)
        if holder is None or ch_key not in require_type(holder).channel_keys():
            continue
        alias = ROLE_ALIASES[role].get(ch_key)
        if alias and alias not in fields:
            fields.append(alias)

    for entry in build_manifest(specs):
        if entry["column"] not in fields:
            fields.append(entry["column"])

    return fields
