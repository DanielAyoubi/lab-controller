import json
import os

from PyQt6.QtCore import QSettings, Qt
from PyQt6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QScrollArea, QSplitter, QTabWidget,
    QVBoxLayout, QWidget,
)

from devices import DEVICE_TYPES
from gui.devices_dialog import DevicesDialog
from gui.experiment_panel import ExperimentPanel, spin_box
from gui.plot import LivePlot
from worker import Worker, data_units

DEFAULT_SETUP = os.path.join("setups", "humidity.json")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("ACME", "ACME-controller")
        self.worker = None
        self.setup = None
        self.setup_path = None
        self.status_dots = {}
        self.value_labels = {}
        self.units = {}
        self.rh_hold = None  # stays None when the setup has no two MFCs to split the flow between
        self.column_width = None  # set once the handle is dragged, and then left alone

        file_menu = self.menuBar().addMenu("File")
        self.open_action = file_menu.addAction("Open from setup catalog…")
        self.open_action.triggered.connect(self.open_setup)
        file_menu.addAction("Save setup as…").triggered.connect(self.save_setup_as)

        self.setup_label = QLabel()
        self.devices_button = QPushButton("Devices…")
        self.devices_button.clicked.connect(self.edit_devices)
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self.toggle_connection)
        top_row = QHBoxLayout()
        top_row.addWidget(self.setup_label)
        top_row.addStretch()
        top_row.addWidget(self.devices_button)
        top_row.addWidget(self.connect_button)

        self.left_column = QScrollArea()
        self.left_column.setWidgetResizable(True)

        self.plot = LivePlot()
        clear_button = QPushButton("Clear plot")
        clear_button.clicked.connect(self.plot.clear_data)
        self.experiment_status = QLabel()
        self.experiment_status.setWordWrap(True)  # a long line wraps rather than widening the window
        plot_bottom_row = QHBoxLayout()
        plot_bottom_row.addWidget(self.experiment_status, 1)
        plot_bottom_row.addWidget(clear_button)
        plot_tab = QWidget()
        plot_layout = QVBoxLayout(plot_tab)
        plot_layout.addWidget(self.plot)
        plot_layout.addLayout(plot_bottom_row)
        self.experiment_panel = ExperimentPanel(self.send)
        tabs = QTabWidget()
        tabs.addTab(plot_tab, "Plot")
        tabs.addTab(self.experiment_panel, "Experiment")

        # A splitter, so the column can be dragged away from the width rebuild() gives it.
        self.body = QSplitter(Qt.Orientation.Horizontal)
        self.body.addWidget(self.left_column)
        self.body.addWidget(tabs)
        self.body.setStretchFactor(1, 1)  # a wider window gives the extra width to the tabs
        self.body.splitterMoved.connect(self.column_dragged)
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(top_row)
        layout.addWidget(self.body)
        self.setCentralWidget(central)

        path = self.settings.value("setup_path", DEFAULT_SETUP)
        if not os.path.exists(path):
            path = DEFAULT_SETUP
        self.load_setup(path)

    def load_setup(self, path):
        try:
            with open(path, encoding="utf-8") as file:
                setup = json.load(file)
            # Fill in anything a hand-written setup file left out.
            setup.setdefault("log_folder", "data")
            setup.setdefault("poll_interval", 2.0)
            setup.setdefault("devices", [])
            setup.setdefault("computed_rh", [])
            setup.setdefault("rh_control", {"source": "", "humid_mfc": "", "dry_mfc": "", "target": 50.0,
                                            "total_flow": 2.0, "kp": 1.0, "ki": 0.03, "kd": 0.0})
            for device in setup["devices"]:
                if device["type"] not in DEVICE_TYPES:
                    raise ValueError(f"Unknown device type '{device['type']}'")
        except Exception as error:
            QMessageBox.warning(self, "Open setup", f"Could not open {path}:\n{error}")
            return
        self.setup = setup
        self.setup_path = path
        self.settings.setValue("setup_path", path)
        self.rebuild()

    def save_setup(self):
        with open(self.setup_path, "w", encoding="utf-8") as file:
            json.dump(self.setup, file, indent=2, ensure_ascii=False)

    def open_setup(self):
        path, _ = QFileDialog.getOpenFileName(self, "Setup catalog", "setups", "Setup files (*.json)")
        if path:
            self.load_setup(path)

    def save_setup_as(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save into setup catalog", "setups", "Setup files (*.json)")
        if path:
            self.setup_path = path
            self.settings.setValue("setup_path", path)
            self.save_setup()
            self.rebuild()

    def edit_devices(self):
        dialog = DevicesDialog(self.setup, self)
        if dialog.exec():
            self.setup = dialog.setup
            self.save_setup()
            self.rebuild()

    def rebuild(self):
        """Build the device-dependent parts of the window from the current setup."""
        self.setup_label.setText(f"Setup: {os.path.basename(self.setup_path)}")
        self.units = data_units(self.setup)
        panel = QWidget()
        layout = QVBoxLayout(panel)

        devices_group = QGroupBox("Devices")
        devices_grid = QGridLayout(devices_group)
        self.status_dots = {}
        for row, device in enumerate(self.setup["devices"]):
            dot = QLabel("●")
            dot.setStyleSheet("color: gray")
            self.status_dots[device["name"]] = dot
            devices_grid.addWidget(dot, row, 0)
            devices_grid.addWidget(QLabel(device["name"]), row, 1)
            devices_grid.addWidget(QLabel(DEVICE_TYPES[device["type"]].label), row, 2)
        if not self.setup["devices"]:
            devices_grid.addWidget(QLabel("No devices yet. Click Devices… to add them."), 0, 0)
        devices_grid.setColumnStretch(1, 1)
        layout.addWidget(devices_group)

        readings_group = QGroupBox("Latest readings")
        readings_form = QFormLayout(readings_group)
        self.value_labels = {}
        for column in self.units:
            self.value_labels[column] = QLabel("–")
            readings_form.addRow(column, self.value_labels[column])
        layout.addWidget(readings_group)

        self.control_group = QGroupBox("Manual control")
        control_grid = QGridLayout(self.control_group)
        row = 0
        for device in self.setup["devices"]:
            for control, unit in DEVICE_TYPES[device["type"]].controls.items():
                value_box = QDoubleSpinBox()
                value_box.setRange(-1000, 10000)
                value_box.setDecimals(2)
                value_box.setSingleStep(0.1)
                value_box.setSuffix(f" {unit}")
                set_button = QPushButton("Set")
                # The default arguments freeze this row's device, control and box inside the lambda.
                set_button.clicked.connect(
                    lambda checked, name=device["name"], control=control, box=value_box:
                    self.send(("set", name, control, box.value())))
                control_grid.addWidget(QLabel(f"{device['name']} {control}"), row, 0)
                control_grid.addWidget(value_box, row, 1)
                control_grid.addWidget(set_button, row, 2)
                row += 1
        if row > 0:
            layout.addWidget(self.control_group)

        self.rh_hold = None
        flow_devices = [device["name"] for device in self.setup["devices"]
                        if "flow" in DEVICE_TYPES[device["type"]].controls]
        if len(flow_devices) > 1:
            layout.addWidget(self.rh_control_box(flow_devices))

        layout.addStretch()
        self.left_column.setWidget(panel)
        width = self.column_width
        if width is None:
            width = panel.sizeHint().width() + self.left_column.verticalScrollBar().sizeHint().width()
        self.body.setSizes([width, max(width, self.body.width() - width)])
        self.plot.configure(self.units)
        self.experiment_panel.configure(self.setup)

    def column_dragged(self, position, index):
        self.column_width = position

    def rh_control_box(self, flow_devices):
        settings = self.setup["rh_control"]
        self.rh_source = QComboBox()
        # Every RH-like column: a device's "rh" reading, or an RH worked out from a dew point.
        computed = [entry["name"] for entry in self.setup["computed_rh"]]
        self.rh_source.addItems([column for column in self.units
                                 if column.endswith(" RH") or column in computed])
        self.rh_source.setCurrentText(settings["source"])
        self.rh_humid = QComboBox()
        self.rh_humid.addItems(flow_devices)
        self.rh_humid.setCurrentText(settings["humid_mfc"])
        self.rh_dry = QComboBox()
        self.rh_dry.addItems(flow_devices)
        self.rh_dry.setCurrentText(settings["dry_mfc"])
        self.rh_target = spin_box(0, 100, settings["target"], " %")
        self.rh_total = spin_box(0, 100, settings["total_flow"], " L/min", step=0.1)
        self.rh_hold = QPushButton("Hold RH")
        self.rh_hold.setCheckable(True)
        self.rh_status = QLabel("off")

        form = QFormLayout()
        form.addRow("RH source", self.rh_source)
        form.addRow("Humid MFC", self.rh_humid)
        form.addRow("Dry MFC", self.rh_dry)
        form.addRow("Target RH", self.rh_target)
        form.addRow("Total flow", self.rh_total)
        form.addRow(self.rh_hold)
        form.addRow(self.rh_status)
        box = QGroupBox("RH control")
        box.setLayout(form)

        # Connect only now, so filling in the saved values above did not count as an edit.
        for widget in (self.rh_source, self.rh_humid, self.rh_dry):
            widget.currentIndexChanged.connect(self.rh_changed)
        for widget in (self.rh_target, self.rh_total):
            widget.editingFinished.connect(self.rh_changed)
        self.rh_hold.clicked.connect(self.rh_changed)
        return box

    def rh_changed(self):
        """Save what the RH control box shows, and hand it to a running worker."""
        # Spread first: the PID gains have no widgets and are only edited in the setup file.
        self.setup["rh_control"] = {
            **self.setup["rh_control"],
            "source": self.rh_source.currentText(),
            "humid_mfc": self.rh_humid.currentText(),
            "dry_mfc": self.rh_dry.currentText(),
            "target": self.rh_target.value(),
            "total_flow": self.rh_total.value(),
        }
        self.save_setup()
        if self.worker is None:
            self.rh_hold.setChecked(False)
        self.send(("rh_control", self.setup["rh_control"], self.rh_hold.isChecked()))

    def send(self, command):
        if self.worker is None:
            self.statusBar().showMessage("Connect first.")
            return
        self.worker.commands.put(command)

    def toggle_connection(self):
        if self.worker is None:
            # Rebuild first, so the worker starts from the setup exactly as the window shows it.
            self.rebuild()
            self.worker = Worker(self.setup)
            self.worker.new_data.connect(self.show_data)
            self.worker.message.connect(self.statusBar().showMessage)
            self.worker.connection_failed.connect(self.connection_failed)
            if self.rh_hold is not None:
                self.worker.rh_control_state.connect(self.rh_hold.setChecked)
            self.worker.start()
            self.statusBar().showMessage("Connecting…")
            self.connect_button.setText("Disconnect")
        else:
            self.statusBar().showMessage("Disconnecting…")
            self.worker.running = False
            self.worker.wait()
            self.worker = None
            self.connect_button.setText("Connect")
            self.experiment_status.clear()
            self.lock_manual_control(False)
            for dot in self.status_dots.values():
                dot.setStyleSheet("color: gray")
        connected = self.worker is not None
        # The device list must not change under a running worker.
        self.devices_button.setEnabled(not connected)
        self.open_action.setEnabled(not connected)
        self.experiment_panel.set_connected(connected)
        if self.rh_hold is not None:
            # These three name a column and two devices the loop reads, so they must not
            # change under a running worker.
            self.rh_source.setEnabled(not connected)
            self.rh_humid.setEnabled(not connected)
            self.rh_dry.setEnabled(not connected)

    def lock_manual_control(self, locked):
        """An experiment sets the flows and setpoints itself, so nothing else may change them meanwhile."""
        self.control_group.setEnabled(not locked)
        self.control_group.setTitle("Manual control (locked during the experiment)" if locked else "Manual control")
        if self.rh_hold is not None:
            self.rh_hold.setEnabled(not locked)

    def connection_failed(self, text):
        if self.worker is None:
            return  # the user disconnected before the worker gave up
        self.toggle_connection()  # the worker has already stopped; this puts the window back
        self.statusBar().showMessage(text)

    def show_data(self, row):
        if self.worker is None:
            return  # a last row that arrived after disconnecting
        for device in self.setup["devices"]:
            has_values = False
            for reading in DEVICE_TYPES[device["type"]].readings:
                if row[f"{device['name']} {reading}"] is not None:
                    has_values = True
            if has_values:
                self.status_dots[device["name"]].setStyleSheet("color: green")
            else:
                self.status_dots[device["name"]].setStyleSheet("color: red")
        for column, label in self.value_labels.items():
            if row[column] is None:
                label.setText("–")
            else:
                label.setText(f"{row[column]:.2f} {self.units[column]}")
        self.plot.add(row)
        self.experiment_panel.show_step(row["step"])
        self.lock_manual_control(row["step"] != "")
        self.experiment_status.setText(self.experiment_panel.progress(row["step"], row.get("step end")))
        if self.rh_hold is not None:
            if row.get("RH control setpoint") is None:
                self.rh_status.setText("off")
            elif row.get("RH control share") is None:
                self.rh_status.setText("holding, waiting for a reading")
            else:
                self.rh_status.setText(f"holding {row['RH control setpoint']:g} %, "
                                       f"humid share {row['RH control share']:.1f} %")

    def closeEvent(self, event):
        if self.worker is not None:
            self.toggle_connection()
        event.accept()
