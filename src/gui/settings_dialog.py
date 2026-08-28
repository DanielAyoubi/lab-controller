from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit,
    QSpinBox, QDoubleSpinBox, QDialogButtonBox,
    QTabWidget, QWidget, QMessageBox, QLabel
)

from src.gui.widgets.device_editor import DeviceListEditor


class SettingsDialog(QDialog):
    def __init__(self, config: dict, parent=None, busy_ports=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(600, 400)
        self.config = config
        # Ports a live driver currently holds open. Device detection must leave
        # them alone; everything else in here is safe to edit while connected.
        self.busy_ports = list(busy_ports or [])

        layout = QVBoxLayout(self)
        
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        
        # Devices first: it is the tab that describes the rig, and the one
        # people actually come here to change.
        self._create_devices_tab()
        self._create_general_tab()
        self._create_experiment_tab()
        
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self):
        """Validate the device list before closing — a bad list breaks connect."""
        error = self.device_editor.validate()
        if error:
            QMessageBox.warning(self, "Invalid device setup", error)
            self.tabs.setCurrentWidget(self.device_editor)
            return

        warning = self.device_editor.port_warning()
        if warning:
            proceed = QMessageBox.question(
                self, "Shared port", warning + "\n\nSave anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if proceed != QMessageBox.StandardButton.Yes:
                self.tabs.setCurrentWidget(self.device_editor)
                return

        self.accept()

    def _create_general_tab(self):
        tab = QWidget()
        layout = QFormLayout(tab)
        
        self.log_dir = QLineEdit(self.config.get("log_dir", "data"))
        layout.addRow("Log Directory:", self.log_dir)
        
        self.log_prefix = QLineEdit(self.config.get("log_prefix", "nsim_log"))
        layout.addRow("Log Prefix:", self.log_prefix)
        
        self.max_plot_points = QSpinBox()
        self.max_plot_points.setRange(10, 10000)
        self.max_plot_points.setValue(self.config.get("max_plot_points", 500))
        layout.addRow("Max Plot Points:", self.max_plot_points)
        
        self.control_interval = QSpinBox()
        self.control_interval.setRange(100, 10000)
        self.control_interval.setSingleStep(100)
        # Value is in milliseconds
        self.control_interval.setValue(int(self.config.get("control_interval", 5000)))
        self.control_interval.setSuffix(" ms")
        layout.addRow("Control Interval:", self.control_interval)
        
        self.tabs.addTab(tab, "General")

    def _create_devices_tab(self):
        """Device list editor — see src/gui/widgets/device_editor.py."""
        self.device_editor = DeviceListEditor(self.config.get("devices", []),
                                             busy_ports=self.busy_ports)
        self.tabs.addTab(self.device_editor, "Devices")

    def _create_experiment_tab(self):
        tab = QWidget()
        layout = QFormLayout(tab)

        self.experiment_flow_start = QDoubleSpinBox()
        self.experiment_flow_start.setDecimals(3)
        self.experiment_flow_start.setRange(0.0, 10.0)
        self.experiment_flow_start.setSingleStep(0.05)
        self.experiment_flow_start.setValue(self.config.get("experiment_flow_start", 0.0))
        self.experiment_flow_start.setSuffix(" L/min")
        layout.addRow("Flow Start (flow mode):", self.experiment_flow_start)

        self.experiment_flow_end = QDoubleSpinBox()
        self.experiment_flow_end.setDecimals(3)
        self.experiment_flow_end.setRange(0.0, 10.0)
        self.experiment_flow_end.setSingleStep(0.05)
        self.experiment_flow_end.setValue(self.config.get("experiment_flow_end", 2.0))
        self.experiment_flow_end.setSuffix(" L/min")
        layout.addRow("Flow End (flow mode):", self.experiment_flow_end)

        self.experiment_flow_step = QDoubleSpinBox()
        self.experiment_flow_step.setDecimals(3)
        self.experiment_flow_step.setRange(0.001, 2.0)
        self.experiment_flow_step.setSingleStep(0.05)
        self.experiment_flow_step.setValue(self.config.get("experiment_flow_step", 0.1))
        self.experiment_flow_step.setSuffix(" L/min")
        layout.addRow("Flow Step (flow mode):", self.experiment_flow_step)

        self.experiment_rh_step = QDoubleSpinBox()
        self.experiment_rh_step.setDecimals(1)
        self.experiment_rh_step.setRange(0.1, 50.0)
        self.experiment_rh_step.setSingleStep(1.0)
        self.experiment_rh_step.setValue(self.config.get("experiment_rh_step", 5.0))
        self.experiment_rh_step.setSuffix(" %")
        layout.addRow("RH Step (RH mode):", self.experiment_rh_step)

        self.experiment_hold_time = QDoubleSpinBox()
        self.experiment_hold_time.setDecimals(0)
        self.experiment_hold_time.setRange(10.0, 3600.0)
        self.experiment_hold_time.setSingleStep(10.0)
        self.experiment_hold_time.setValue(self.config.get("experiment_hold_time", 180.0))
        self.experiment_hold_time.setSuffix(" s")
        layout.addRow("Step Wait Time:", self.experiment_hold_time)

        self.max_flow = QDoubleSpinBox()
        self.max_flow.setRange(0.1, 10.0)
        self.max_flow.setSingleStep(0.1)
        self.max_flow.setValue(self.config.get("max_flow", 2.0))
        self.max_flow.setSuffix(" L/min")
        layout.addRow("Max Flow:", self.max_flow)

        # ── RH Feedforward + PI Controller ──────────────────────────────────
        layout.addRow(QLabel("── RH Feedforward + PI Controller ──"))

        self.rh_dead_time = QDoubleSpinBox()
        self.rh_dead_time.setDecimals(0)
        self.rh_dead_time.setRange(0.0, 300.0)
        self.rh_dead_time.setSingleStep(5.0)
        self.rh_dead_time.setValue(self.config.get("rh_dead_time", 25.0))
        self.rh_dead_time.setSuffix(" s")
        layout.addRow("Transport dead time:", self.rh_dead_time)

        self.rh_trim_limit = QDoubleSpinBox()
        self.rh_trim_limit.setDecimals(2)
        self.rh_trim_limit.setRange(0.05, 1.0)
        self.rh_trim_limit.setSingleStep(0.05)
        self.rh_trim_limit.setValue(self.config.get("rh_trim_limit", 0.6))
        layout.addRow("Max feedback trim:", self.rh_trim_limit)

        self.rh_settling_time = QDoubleSpinBox()
        self.rh_settling_time.setRange(5.0, 600.0)
        self.rh_settling_time.setSingleStep(5.0)
        self.rh_settling_time.setValue(self.config.get("rh_settling_time", 180.0))
        self.rh_settling_time.setSuffix(" s")
        layout.addRow("Max settling time (full Δflow):", self.rh_settling_time)

        self.rh_settling_time_min = QDoubleSpinBox()
        self.rh_settling_time_min.setRange(1.0, 60.0)
        self.rh_settling_time_min.setSingleStep(1.0)
        self.rh_settling_time_min.setValue(self.config.get("rh_settling_time_min", 5.0))
        self.rh_settling_time_min.setSuffix(" s")
        layout.addRow("Min settling time (tiny Δflow):", self.rh_settling_time_min)

        self.rh_deadband = QDoubleSpinBox()
        self.rh_deadband.setDecimals(1)
        self.rh_deadband.setRange(0.1, 10.0)
        self.rh_deadband.setSingleStep(0.1)
        self.rh_deadband.setValue(self.config.get("rh_deadband", 1.0))
        self.rh_deadband.setSuffix(" %")
        layout.addRow("Deadband (±):", self.rh_deadband)

        self.rh_kp = QDoubleSpinBox()
        self.rh_kp.setDecimals(4)
        self.rh_kp.setRange(0.0001, 1.0)
        self.rh_kp.setSingleStep(0.001)
        self.rh_kp.setValue(self.config.get("rh_kp", 0.01))
        layout.addRow("Kp (trim):", self.rh_kp)

        self.rh_ki = QDoubleSpinBox()
        self.rh_ki.setDecimals(5)
        self.rh_ki.setRange(0.00001, 0.1)
        self.rh_ki.setSingleStep(0.0001)
        self.rh_ki.setValue(self.config.get("rh_ki", 0.002))
        layout.addRow("Ki (trim):", self.rh_ki)

        self.rh_kd = QDoubleSpinBox()
        self.rh_kd.setDecimals(4)
        self.rh_kd.setRange(0.0, 1.0)
        self.rh_kd.setSingleStep(0.005)
        self.rh_kd.setValue(self.config.get("rh_kd", 0.0))
        layout.addRow("Kd (0 = off):", self.rh_kd)

        self.rh_derivative_filter_tau = QDoubleSpinBox()
        self.rh_derivative_filter_tau.setDecimals(1)
        self.rh_derivative_filter_tau.setRange(1.0, 300.0)
        self.rh_derivative_filter_tau.setSingleStep(5.0)
        self.rh_derivative_filter_tau.setValue(self.config.get("rh_derivative_filter_tau", 30.0))
        self.rh_derivative_filter_tau.setSuffix(" s")
        layout.addRow("D filter τ:", self.rh_derivative_filter_tau)

        # ── Pre-conditioning stability ───────────────────────────────────────
        layout.addRow(QLabel("── Pre-conditioning stability ──"))

        self.experiment_stability_readings = QSpinBox()
        self.experiment_stability_readings.setRange(1, 20)
        self.experiment_stability_readings.setValue(
            int(self.config.get("experiment_stability_readings", 5))
        )
        layout.addRow("Stability readings (N in-deadband):", self.experiment_stability_readings)

        self.experiment_stability_timeout = QDoubleSpinBox()
        self.experiment_stability_timeout.setDecimals(0)
        self.experiment_stability_timeout.setRange(60.0, 3600.0)
        self.experiment_stability_timeout.setSingleStep(30.0)
        self.experiment_stability_timeout.setValue(
            float(self.config.get("experiment_stability_timeout", 600.0))
        )
        self.experiment_stability_timeout.setSuffix(" s")
        layout.addRow("Stability timeout:", self.experiment_stability_timeout)

        self.tabs.addTab(tab, "Experiment")

    def get_settings(self):
        return {
            "log_dir": self.log_dir.text(),
            "log_prefix": self.log_prefix.text(),
            "max_plot_points": self.max_plot_points.value(),
            "control_interval": int(self.control_interval.value()),
            "devices": self.device_editor.get_devices(),
            "experiment_flow_start": self.experiment_flow_start.value(),
            "experiment_flow_end": self.experiment_flow_end.value(),
            "experiment_flow_step": self.experiment_flow_step.value(),
            "experiment_rh_step": self.experiment_rh_step.value(),
            "experiment_hold_time": self.experiment_hold_time.value(),
            "max_flow": self.max_flow.value(),
            "rh_dead_time": self.rh_dead_time.value(),
            "rh_trim_limit": self.rh_trim_limit.value(),
            "rh_settling_time": self.rh_settling_time.value(),
            "rh_settling_time_min": self.rh_settling_time_min.value(),
            "rh_deadband": self.rh_deadband.value(),
            "rh_kp": self.rh_kp.value(),
            "rh_ki": self.rh_ki.value(),
            "rh_kd": self.rh_kd.value(),
            "rh_derivative_filter_tau": self.rh_derivative_filter_tau.value(),
            "experiment_stability_readings": self.experiment_stability_readings.value(),
            "experiment_stability_timeout": self.experiment_stability_timeout.value(),
        }
