"""Device list editor — the Devices tab of the Settings dialog.

Renders one card per configured device. The connection fields on a card are
generated from the device type's ``fields`` (an MFC has a Modbus address row, a
chiller does not), which is why this is a column of per-device widgets rather
than a table with fixed columns.
"""

from typing import Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from src.devices import discovery, registry as reg
from src.gui.widgets.discovery_dialog import DiscoveryDialog


def _port_value(combo: QComboBox) -> str:
    """The bare port name behind a port combo.

    Detected ports are listed as "COM23 — USB Serial Port" so the user can tell
    one cable from another, but the spec must hold just "COM23". A picked entry
    carries the port name as its item data; anything typed by hand is taken as
    written, minus any description the user pasted along with it.
    """
    text = combo.currentText().strip()
    index = combo.findText(text)
    if index >= 0:
        return combo.itemData(index) or text
    return text.split("—")[0].strip()


class DeviceCard(QFrame):
    """Editor for a single device spec."""

    def __init__(self, spec: dict, on_remove, on_role_changed, ports=None,
                 parent=None):
        super().__init__(parent)
        self.spec = dict(spec)
        self.dtype = reg.DEVICE_TYPES[self.spec["type"]]
        self._on_role_changed = on_role_changed

        self.setFrameShape(QFrame.Shape.StyledPanel)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(4)

        # Header: enabled toggle + type + remove
        header = QHBoxLayout()
        self.chk_enabled = QCheckBox()
        self.chk_enabled.setChecked(bool(self.spec.get("enabled", True)))
        self.chk_enabled.setToolTip("Connect this device")
        type_lbl = QLabel(f"<b>{self.dtype.label}</b>")
        btn_remove = QPushButton("Remove")
        btn_remove.setMaximumWidth(80)
        btn_remove.clicked.connect(lambda: on_remove(self))
        header.addWidget(self.chk_enabled)
        header.addWidget(type_lbl)
        header.addStretch()
        header.addWidget(btn_remove)
        outer.addLayout(header)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)

        self.edit_tag = QLineEdit(self.spec.get("tag", ""))
        self.edit_tag.setToolTip(
            "Display name — used in the plot legend and the control panel.\n"
            "Renaming is safe: the CSV column prefix is fixed when the device "
            "is created."
        )
        form.addRow("Tag:", self.edit_tag)

        # An MFC needs a real role choice (wet vs dry can't be inferred).
        # Every other type has exactly one sensible role, so it is assigned
        # automatically and the only question is which device is primary when
        # several of the same kind are fitted.
        current = self.spec.get("role", reg.ROLE_NONE)
        self.combo_role = None
        self.chk_primary = None

        if self.dtype.role_is_a_choice:
            self.combo_role = QComboBox()
            for role in self.dtype.roles():
                self.combo_role.addItem(reg.ROLE_LABELS[role], role)
            idx = self.combo_role.findData(current)
            self.combo_role.setCurrentIndex(idx if idx >= 0 else 0)
            self.combo_role.setToolTip(
                "Which line this MFC feeds. The RH loop and the ramp experiment "
                "drive the wet/dry pair; any other MFC is set manually only."
            )
            self.combo_role.currentIndexChanged.connect(
                lambda _: self._on_role_changed(self)
            )
            form.addRow("Role:", self.combo_role)
        else:
            natural = self.dtype.natural_role or reg.ROLE_NONE
            self.chk_primary = QCheckBox(reg.ROLE_DUTIES[natural])
            self.chk_primary.setChecked(current == self.dtype.natural_role)
            self.chk_primary.setToolTip(
                "Every device measures and logs on its own — this does not "
                "change what it reads or plots.\n"
                "It only picks which one the control loop acts on, and which "
                "one fills the fixed-name CSV columns that analysis scripts "
                "expect. Exactly one device of each kind holds it."
            )
            self.chk_primary.toggled.connect(lambda _: self._on_role_changed(self))
            form.addRow("", self.chk_primary)

        # Type-specific connection fields, generated from the registry.
        self.field_widgets: Dict[str, QWidget] = {}
        for field in self.dtype.fields:
            value = self.spec.get(field.key, field.default)
            if field.kind == "int":
                widget = QSpinBox()
                widget.setRange(field.minimum, field.maximum)
                widget.setValue(int(value))
            elif field.kind == "port":
                widget = QComboBox()
                widget.setEditable(True)
                widget.setToolTip(
                    "Pick a detected port, or type one if the device is "
                    "currently unplugged.\n"
                    "Use “Detect devices” below to find it automatically."
                )
                self._fill_ports(widget, ports or [], str(value))
            else:
                widget = QLineEdit(str(value))
            self.field_widgets[field.key] = widget
            form.addRow(f"{field.label}:", widget)

        outer.addLayout(form)

    @property
    def role(self) -> str:
        """Exactly one of the two editors exists — see __init__."""
        if self.combo_role is not None:
            return self.combo_role.currentData() or reg.ROLE_NONE
        if self.chk_primary is not None and self.chk_primary.isChecked():
            return self.dtype.natural_role or reg.ROLE_NONE
        return reg.ROLE_NONE

    def set_primary(self, primary: bool):
        """Check/uncheck the primary box without re-triggering the swap."""
        if self.chk_primary is None:
            return
        self.chk_primary.blockSignals(True)
        self.chk_primary.setChecked(primary)
        self.chk_primary.blockSignals(False)

    def clear_role(self):
        """Drop this card's role — used when another device claims it."""
        if self.chk_primary is not None:
            self.set_primary(False)
            return
        if self.combo_role is None:
            return
        idx = self.combo_role.findData(reg.ROLE_NONE)
        if idx >= 0:
            self.combo_role.blockSignals(True)
            self.combo_role.setCurrentIndex(idx)
            self.combo_role.blockSignals(False)

    @staticmethod
    def _fill_ports(combo: QComboBox, ports, current: str):
        """List the detected ports, keeping whatever the spec already holds.

        A configured port that is not currently present is added anyway — an
        unplugged instrument must not silently lose its port when the dialog
        is opened.
        """
        combo.blockSignals(True)
        combo.clear()
        names = []
        for port in ports:
            combo.addItem(port.label, port.device)
            names.append(port.device)
        if current and current not in names:
            combo.addItem(current, current)
        index = combo.findData(current) if current else -1
        if index >= 0:
            combo.setCurrentIndex(index)
        else:
            combo.setCurrentText(current or "")
        combo.blockSignals(False)

    def refresh_ports(self, ports):
        """Re-list the detected ports without disturbing the current choice."""
        for field in self.dtype.fields:
            if field.kind != "port":
                continue
            combo = self.field_widgets.get(field.key)
            if isinstance(combo, QComboBox):
                self._fill_ports(combo, ports, _port_value(combo))

    def set_connection(self, updates: dict):
        """Fill in connection fields discovered by a scan."""
        for key, value in updates.items():
            widget = self.field_widgets.get(key)
            if isinstance(widget, QSpinBox):
                widget.setValue(int(value))
            elif isinstance(widget, QComboBox):
                index = widget.findData(str(value))
                widget.setCurrentText(widget.itemText(index) if index >= 0
                                      else str(value))
            elif isinstance(widget, QLineEdit):
                widget.setText(str(value))

    def to_spec(self) -> dict:
        spec = dict(self.spec)
        spec.update({
            "tag": self.edit_tag.text().strip(),
            "role": self.role,
            "enabled": bool(self.chk_enabled.isChecked()),
        })
        for key, widget in self.field_widgets.items():
            if isinstance(widget, QSpinBox):
                spec[key] = widget.value()
            elif isinstance(widget, QComboBox):
                spec[key] = _port_value(widget)
            elif isinstance(widget, QLineEdit):
                spec[key] = widget.text().strip()
        return spec


class DeviceListEditor(QWidget):
    """Scrollable list of device cards plus the add-device row."""

    def __init__(self, devices: List[dict], busy_ports=None, parent=None):
        super().__init__(parent)
        self.cards: List[DeviceCard] = []
        # Ports held open by a live driver: a scan must not try to reopen them,
        # and on Windows it could not anyway.
        self.busy_ports = list(busy_ports or [])
        self.ports = discovery.list_serial_ports()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        hint = QLabel(
            "Each device needs a port and a tag — the tag is what labels it in "
            "the plot and the controls. Probes, chillers and O₂ meters take "
            "their role automatically; only the MFCs need telling which is the "
            "<b>wet</b> and which the <b>dry</b> line.<br>"
            "Not sure of a port or a Modbus address? Use <b>Detect devices</b> "
            "to find them."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #555555; font-size: 11px;")
        layout.addWidget(hint)

        self._card_host = QWidget()
        self._card_layout = QVBoxLayout(self._card_host)
        self._card_layout.setContentsMargins(0, 0, 0, 0)
        self._card_layout.setSpacing(6)
        self._card_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(self._card_host)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(scroll)

        add_row = QHBoxLayout()
        self.combo_new_type = QComboBox()
        for key, dtype in reg.DEVICE_TYPES.items():
            self.combo_new_type.addItem(dtype.label, key)
        btn_add = QPushButton("+ Add device")
        btn_add.clicked.connect(self._add_from_combo)
        add_row.addWidget(self.combo_new_type, 1)
        add_row.addWidget(btn_add)
        layout.addLayout(add_row)

        btn_detect = QPushButton("Detect devices…")
        btn_detect.setToolTip(
            "Scan the serial ports and fill in the ports, baudrates and "
            "Modbus addresses of whatever answers."
        )
        btn_detect.clicked.connect(self.detect_devices)
        layout.addWidget(btn_detect)

        for spec in devices or []:
            if spec.get("type") in reg.DEVICE_TYPES:
                self._add_card(spec)

    # ── Cards ────────────────────────────────────────────────────────────────

    def _add_card(self, spec: dict):
        card = DeviceCard(spec, self._remove_card, self._enforce_unique_role,
                          ports=self.ports)
        self.cards.append(card)
        # Insert before the trailing stretch so cards stay top-aligned.
        self._card_layout.insertWidget(self._card_layout.count() - 1, card)

    def _remove_card(self, card: DeviceCard):
        self.cards.remove(card)
        self._card_layout.removeWidget(card)
        card.setParent(None)
        card.deleteLater()

    def _new_spec(self, type_key: str) -> Optional[dict]:
        """A fresh spec for one more device of ``type_key``, or None if full."""
        dtype = reg.DEVICE_TYPES[type_key]
        same_type = [c for c in self.cards if c.spec["type"] == type_key]
        if len(same_type) >= reg.MAX_PER_TYPE:
            QMessageBox.warning(
                self, "Too many devices",
                f"At most {reg.MAX_PER_TYPE} × {dtype.label} are supported.",
            )
            return None

        tag = dtype.label if not same_type else f"{dtype.label} {len(same_type) + 1}"
        taken = [c.spec["id"] for c in self.cards]
        spec = {
            "id": reg.make_id(tag, taken),
            "type": type_key,
            "tag": tag,
            # A first probe/chiller/O2 meter takes its natural role right away,
            # so the common single-device case needs no role interaction at all.
            "role": self._first_free_role(dtype),
            "enabled": True,
        }
        spec.update(dtype.defaults())
        return spec

    def _add_from_combo(self):
        spec = self._new_spec(self.combo_new_type.currentData())
        if spec is not None:
            self._add_card(spec)

    # ── Detection ────────────────────────────────────────────────────────────

    def detect_devices(self):
        """Scan the serial ports and fold what answers into the card list."""
        dialog = DiscoveryDialog(self.get_devices(), self.busy_ports, self)
        accepted = dialog.exec()

        # Cables may have been plugged or pulled while the dialog was open, and
        # the scan is the most recent word on what is out there either way.
        self.ports = discovery.list_serial_ports()
        for card in self.cards:
            card.refresh_ports(self.ports)

        if accepted:
            self._apply_discovered(dialog.selected_devices())

    def _adoptable(self, found) -> Optional[DeviceCard]:
        """The card that is almost certainly ``found`` under a new COM number.

        Windows renumbers COM ports when adapters are moved between USB sockets,
        which silently breaks a working config. If a card of the same type has
        the same Modbus address but points at a port that no longer exists, it
        is the same instrument and should be re-pointed rather than duplicated.
        Only an unambiguous single candidate is adopted — with two identical
        stale MFCs there is no way to tell which is which, so both are left for
        the user to sort out.
        """
        present = {p.device for p in self.ports}
        address_key = reg.DEVICE_TYPES[found.type_key].discovery.address_key
        candidates = []
        for card in self.cards:
            spec = card.to_spec()
            if spec.get("type") != found.type_key:
                continue
            if spec.get("port") in present:
                continue    # its port still exists, so it is not a stale entry
            if address_key is not None:
                try:
                    if int(spec.get(address_key, -1)) != found.address:
                        continue
                except (TypeError, ValueError):
                    continue
            candidates.append(card)
        return candidates[0] if len(candidates) == 1 else None

    def _apply_discovered(self, found: List):
        added, adopted = [], []
        for item in found:
            if any(item.matches(card.to_spec()) for card in self.cards):
                continue
            card = self._adoptable(item)
            if card is not None:
                card.set_connection(item.spec_updates())
                adopted.append(f"{card.to_spec().get('tag')} → {item.port}")
                continue
            spec = self._new_spec(item.type_key)
            if spec is None:
                continue
            spec.update(item.spec_updates())
            self._add_card(spec)
            added.append(item.label)

        if not added and not adopted:
            QMessageBox.information(
                self, "Nothing to add",
                "Every selected device is already in the list.")
            return

        lines = []
        if added:
            lines.append("Added:\n  " + "\n  ".join(added))
        if adopted:
            lines.append("Moved to a new port:\n  " + "\n  ".join(adopted))
        lines.append("Give the new devices a tag, and set which MFC is wet and "
                     "which is dry, before saving.")
        QMessageBox.information(self, "Devices detected", "\n\n".join(lines))

    def _enforce_unique_role(self, changed: DeviceCard):
        """A role belongs to one device — claiming it releases the previous holder."""
        role = changed.role
        if role != reg.ROLE_NONE:
            for card in self.cards:
                if card is not changed and card.role == role:
                    card.clear_role()
            return

        # Un-setting primary on the last device of its kind would leave nothing
        # feeding the control loops or the standard CSV columns, so it takes the
        # role straight back — for these types the role is implied, not optional.
        natural = changed.dtype.natural_role
        if natural and not any(c.role == natural for c in self.cards):
            changed.set_primary(True)

    def _first_free_role(self, dtype) -> str:
        """Natural role for a newly added device, if no one holds it yet."""
        natural = dtype.natural_role
        if natural and not any(c.role == natural for c in self.cards):
            return natural
        return reg.ROLE_NONE

    # ── Result ───────────────────────────────────────────────────────────────

    def get_devices(self) -> List[dict]:
        # assign_default_roles is the backstop for the implied roles: enabling a
        # device, or disabling the one that held a role, must never leave the
        # standard CSV columns without a source.
        return reg.assign_default_roles([card.to_spec() for card in self.cards])

    def validate(self) -> Optional[str]:
        """Returns an error message, or None when the list is usable.

        Duplicate ports are deliberately *not* an error: two Modbus MFCs
        legitimately share one RS-485 bus at different addresses.
        """
        specs = self.get_devices()

        tags = [s["tag"] for s in specs]
        if any(not t for t in tags):
            return "Every device needs a tag."
        duplicates = {t for t in tags if tags.count(t) > 1}
        if duplicates:
            return f"Duplicate tags: {', '.join(sorted(duplicates))}"

        for type_key, dtype in reg.DEVICE_TYPES.items():
            n = sum(1 for s in specs if s["type"] == type_key)
            if n > reg.MAX_PER_TYPE:
                return f"At most {reg.MAX_PER_TYPE} × {dtype.label} are supported."

        enabled = [s for s in specs if s.get("enabled")]
        if any(not s.get("port") for s in enabled):
            return "Every enabled device needs a port."

        roles = [s["role"] for s in enabled if s["role"] != reg.ROLE_NONE]
        clashing = {r for r in roles if roles.count(r) > 1}
        if clashing:
            return ("Each role can only be assigned once: "
                    f"{', '.join(reg.ROLE_LABELS[r] for r in sorted(clashing))}")

        return None

    def port_warning(self) -> Optional[str]:
        """Non-blocking heads-up when enabled devices share a COM port."""
        ports = [s["port"] for s in self.get_devices()
                 if s.get("enabled") and s.get("port")]
        shared = sorted({p for p in ports if ports.count(p) > 1})
        if not shared:
            return None
        return ("These ports are used by more than one device: "
                f"{', '.join(shared)}.\nThat is fine for Modbus devices sharing a "
                "bus at different addresses, but not for plain serial devices.")
