import copy
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
    QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox, QProgressDialog,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
)
from serial.tools import list_ports

from devices import DEVICE_TYPES
from devices.scan import scan

LOGO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "logo.png")
LOGO_HEIGHT = 160


def logo_widget(ratio):
    picture = QPixmap(LOGO)
    if picture.isNull():
        return None
    picture = picture.scaledToHeight(round(LOGO_HEIGHT * ratio), Qt.TransformationMode.SmoothTransformation)
    picture.setDevicePixelRatio(ratio)
    logo = QLabel()
    logo.setPixmap(picture)
    return logo


class DevicesDialog(QDialog):
    def __init__(self, setup, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Devices")
        self.resize(900, 800)
        self.setup = copy.deepcopy(setup)
        self.ports = [port.device for port in list_ports.comports()]

        # One column per connection setting used by any device type, so a new driver
        # with a new setting shows up here without changing this dialog.
        self.setting_names = []
        for device_class in DEVICE_TYPES.values():
            for key in device_class.settings:
                if key not in self.setting_names:
                    self.setting_names.append(key)

        self.table = QTableWidget(0, 2 + len(self.setting_names))
        self.table.setHorizontalHeaderLabels(["Name", "Type"] + [key.capitalize() for key in self.setting_names])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(self.refresh_rh_sources)

        self.new_type = QComboBox()
        for type_key, device_class in DEVICE_TYPES.items():
            self.new_type.addItem(device_class.label, type_key)
        add_button = QPushButton("Add")
        add_button.clicked.connect(self.add_new_device)
        remove_button = QPushButton("Remove selected")
        remove_button.clicked.connect(self.remove_device)
        detect_button = QPushButton("Detect devices…")
        detect_button.clicked.connect(self.detect_devices)
        table_buttons = QHBoxLayout()
        table_buttons.addWidget(QLabel("Device catalog:"))
        table_buttons.addWidget(self.new_type)
        table_buttons.addWidget(add_button)
        table_buttons.addWidget(remove_button)
        table_buttons.addStretch()
        table_buttons.addWidget(detect_button)

        # One row per RH worked out from a temperature and a dew point with the Magnus formula.
        self.rh_table = QTableWidget(0, 4)
        self.rh_table.setHorizontalHeaderLabels(
            ["Name", "Temperature from", "Dew point from", "Calibrated"])
        self.rh_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        add_rh_button = QPushButton("Add")
        add_rh_button.clicked.connect(self.add_new_rh)
        remove_rh_button = QPushButton("Remove selected")
        remove_rh_button.clicked.connect(self.remove_rh)
        rh_buttons = QHBoxLayout()
        rh_buttons.addWidget(QLabel("Computed RH:"))
        rh_buttons.addWidget(add_rh_button)
        rh_buttons.addWidget(remove_rh_button)
        rh_buttons.addStretch()

        self.poll_interval = QDoubleSpinBox()
        self.poll_interval.setRange(0.5, 3600)
        self.poll_interval.setSuffix(" s")
        self.poll_interval.setValue(self.setup["poll_interval"])
        self.log_folder = QLineEdit(self.setup["log_folder"])
        browse_button = QPushButton("Browse…")
        browse_button.clicked.connect(self.browse_log_folder)
        log_folder_row = QHBoxLayout()
        log_folder_row.addWidget(self.log_folder)
        log_folder_row.addWidget(browse_button)

        form = QFormLayout()
        form.addRow("Poll interval", self.poll_interval)
        form.addRow("Log folder", log_folder_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save_and_close)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        logo = logo_widget(self.devicePixelRatioF())
        if logo is not None:
            header = QHBoxLayout()
            header.addStretch()
            header.addWidget(logo)
            header.addStretch()
            layout.addLayout(header)
        layout.addWidget(self.table)
        layout.addLayout(table_buttons)
        layout.addWidget(self.rh_table)
        layout.addLayout(rh_buttons)
        layout.addLayout(form)
        layout.addWidget(buttons)

        for device in self.setup["devices"]:
            self.add_row(device)
        for entry in self.setup["computed_rh"]:
            self.add_rh_row(entry)

    def add_row(self, device):
        device_class = DEVICE_TYPES[device["type"]]
        # Signals stay blocked until the row is complete, so refresh_rh_sources never sees half a row.
        self.table.blockSignals(True)
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(device["name"]))
        type_item = QTableWidgetItem(device_class.label)
        type_item.setData(Qt.ItemDataRole.UserRole, device["type"])
        type_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.table.setItem(row, 1, type_item)

        for column, key in enumerate(self.setting_names, start=2):
            if key not in device_class.settings:
                empty = QTableWidgetItem("")
                empty.setFlags(Qt.ItemFlag.NoItemFlags)
                self.table.setItem(row, column, empty)
                continue
            value = device.get(key, device_class.settings[key])
            if key == "port":
                editor = QComboBox()
                editor.setEditable(True)  # a device may be unplugged while you edit
                editor.addItems(self.ports)
                editor.setCurrentText(value)
            elif isinstance(value, int):
                editor = QSpinBox()
                editor.setRange(0, 10_000_000)
                editor.setValue(value)
            elif isinstance(value, float):
                editor = QDoubleSpinBox()
                editor.setRange(-1e6, 1e6)
                editor.setDecimals(3)
                editor.setValue(value)
            else:
                editor = QLineEdit(str(value))
            self.table.setCellWidget(row, column, editor)
        self.table.blockSignals(False)
        self.refresh_rh_sources()

    def devices_from_table(self):
        devices = []
        for row in range(self.table.rowCount()):
            type_key = self.table.item(row, 1).data(Qt.ItemDataRole.UserRole)
            device = {"name": self.table.item(row, 0).text().strip(), "type": type_key}
            for column, key in enumerate(self.setting_names, start=2):
                editor = self.table.cellWidget(row, column)
                if editor is None:
                    continue
                if isinstance(editor, QComboBox):
                    device[key] = editor.currentText().strip()
                elif isinstance(editor, QLineEdit):
                    device[key] = editor.text().strip()
                else:
                    device[key] = editor.value()
            devices.append(device)
        return devices

    def add_new_device(self):
        type_key = self.new_type.currentData()
        device_class = DEVICE_TYPES[type_key]
        name = f"{device_class.label} {self.table.rowCount() + 1}"
        self.add_row({"name": name, "type": type_key, **device_class.settings})

    def remove_device(self):
        if self.table.currentRow() >= 0:
            self.table.removeRow(self.table.currentRow())
            self.refresh_rh_sources()

    def add_rh_row(self, entry):
        # itemChanged on this table is not watched, so only the name column needs care here.
        self.rh_table.blockSignals(True)
        row = self.rh_table.rowCount()
        self.rh_table.insertRow(row)
        self.rh_table.setItem(row, 0, QTableWidgetItem(entry["name"]))
        for column in (1, 2):
            self.rh_table.setCellWidget(row, column, QComboBox())
        calibrated = QTableWidgetItem()
        calibrated.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
        calibrated.setCheckState(Qt.CheckState.Checked if entry["calibrated"] else Qt.CheckState.Unchecked)
        self.rh_table.setItem(row, 3, calibrated)
        self.rh_table.blockSignals(False)
        self.refresh_rh_sources()
        self.rh_table.cellWidget(row, 1).setCurrentText(entry["temperature_from"])
        self.rh_table.cellWidget(row, 2).setCurrentText(entry["dewpoint_from"])

    def add_new_rh(self):
        self.add_rh_row({"name": f"RH {self.rh_table.rowCount() + 1}", "temperature_from": "",
                         "dewpoint_from": "", "calibrated": False})

    def remove_rh(self):
        if self.rh_table.currentRow() >= 0:
            self.rh_table.removeRow(self.rh_table.currentRow())

    def computed_rh_from_table(self):
        entries = []
        for row in range(self.rh_table.rowCount()):
            entries.append({
                "name": self.rh_table.item(row, 0).text().strip(),
                "temperature_from": self.rh_table.cellWidget(row, 1).currentText(),
                "dewpoint_from": self.rh_table.cellWidget(row, 2).currentText(),
                "calibrated": self.rh_table.item(row, 3).checkState() == Qt.CheckState.Checked,
            })
        return entries

    def refresh_rh_sources(self):
        """Offer, in every computed RH row, only the devices that report what that column needs."""
        devices = self.devices_from_table()
        for row in range(self.rh_table.rowCount()):
            for column, reading in ((1, "temperature"), (2, "dewpoint")):
                combo = self.rh_table.cellWidget(row, column)
                current = combo.currentText()
                combo.clear()
                combo.addItem("")
                for device in devices:
                    if reading in DEVICE_TYPES[device["type"]].readings:
                        combo.addItem(device["name"])
                combo.setCurrentText(current)

    def browse_log_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Log folder", self.log_folder.text())
        if folder:
            self.log_folder.setText(folder)

    def detect_devices(self):
        choices = ["Quick: default and already used addresses", "Deep: all Modbus addresses (minutes per port)"]
        choice, ok = QInputDialog.getItem(self, "Detect devices", "Scan type:", choices, 0, False)
        if not ok:
            return
        devices = self.devices_from_table()
        known_addresses = [device["address"] for device in devices if "address" in device]

        port_count = len(list_ports.comports())
        progress = QProgressDialog("Scanning…", "Cancel", 0, port_count, self)
        progress.setWindowTitle("Detect devices")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)

        def on_progress(port_number, text):
            progress.setValue(port_number)
            progress.setLabelText(text)
            QApplication.processEvents()
            return not progress.wasCanceled()

        found = scan(choice.startswith("Deep"), known_addresses, on_progress)
        progress.close()

        added = 0
        for device in found:
            already_listed = False
            for existing in devices:
                if (existing["type"] == device["type"] and existing["port"] == device["port"]
                        and existing.get("address") == device.get("address")):
                    already_listed = True
                    break
            if already_listed:
                continue
            name = f"{DEVICE_TYPES[device['type']].label} ({device['port']})"
            if "address" in device:
                name = f"{DEVICE_TYPES[device['type']].label} ({device['port']}, {device['address']})"
            self.add_row({"name": name, **device})
            added += 1
        QMessageBox.information(self, "Detect devices", f"Found {len(found)} device(s), added {added} new.")

    def save_and_close(self):
        devices = self.devices_from_table()
        names = [device["name"] for device in devices]
        if "" in names or len(set(names)) != len(names):
            QMessageBox.warning(self, "Devices", "Every device needs a name, and names must be unique.")
            return
        computed_rh = self.computed_rh_from_table()
        rh_names = [entry["name"] for entry in computed_rh]
        taken = [f"{device['name']} {reading}" for device in devices
                 for reading in DEVICE_TYPES[device["type"]].readings]
        if "" in rh_names or len(set(rh_names)) != len(rh_names) or set(rh_names) & set(taken):
            QMessageBox.warning(self, "Computed RH",
                                "Every computed RH needs a name, and names must be unique "
                                "and different from a device reading.")
            return
        self.setup["devices"] = devices
        self.setup["computed_rh"] = computed_rh
        self.setup["poll_interval"] = self.poll_interval.value()
        self.setup["log_folder"] = self.log_folder.text().strip()
        self.accept()
