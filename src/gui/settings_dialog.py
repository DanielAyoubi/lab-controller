from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, 
    QSpinBox, QDoubleSpinBox, QDialogButtonBox, 
    QTabWidget, QWidget, QCheckBox
)

class SettingsDialog(QDialog):
    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(600, 400)
        self.config = config

        layout = QVBoxLayout(self)
        
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        
        self._create_general_tab()
        self._create_devices_tab()
        self._create_experiment_tab()
        
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | 
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

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
        tab = QWidget()
        layout = QFormLayout(tab)
        # Enable / disable toggles
        self.dry_mfc_enabled = QCheckBox("Dry MFC enabled")
        self.dry_mfc_enabled.setChecked(bool(self.config.get("dry_mfc_enabled", True)))
        layout.addRow(self.dry_mfc_enabled)

        self.wet_mfc_enabled = QCheckBox("Wet MFC enabled")
        self.wet_mfc_enabled.setChecked(bool(self.config.get("wet_mfc_enabled", True)))
        layout.addRow(self.wet_mfc_enabled)

        self.hygrometer_enabled = QCheckBox("Hygrometer enabled")
        self.hygrometer_enabled.setChecked(bool(self.config.get("hygrometer_enabled", True)))
        layout.addRow(self.hygrometer_enabled)

        self.chiller_enabled = QCheckBox("Chiller enabled")
        self.chiller_enabled.setChecked(bool(self.config.get("chiller_enabled", True)))
        layout.addRow(self.chiller_enabled)
        
        self.dry_mfc_port = QLineEdit(self.config.get("dry_mfc_port", "COM6"))
        layout.addRow("Dry MFC Port:", self.dry_mfc_port)
        
        self.wet_mfc_port = QLineEdit(self.config.get("wet_mfc_port", "COM7"))
        layout.addRow("Wet MFC Port:", self.wet_mfc_port)
        
        self.hygrometer_port = QLineEdit(self.config.get("hygrometer_port", "COM9"))
        layout.addRow("Hygrometer Port:", self.hygrometer_port)
        
        self.mfc_baudrate = QSpinBox()
        self.mfc_baudrate.setRange(1200, 115200)
        self.mfc_baudrate.setValue(self.config.get("mfc_baudrate", 9600))
        layout.addRow("MFC Baudrate:", self.mfc_baudrate)
        
        self.hygrometer_baudrate = QSpinBox()
        self.hygrometer_baudrate.setRange(1200, 115200)
        self.hygrometer_baudrate.setValue(self.config.get("hygrometer_baudrate", 19200))
        layout.addRow("Hygrometer Baudrate:", self.hygrometer_baudrate)
        
        self.tabs.addTab(tab, "Devices")

    def _create_experiment_tab(self):
        tab = QWidget()
        layout = QFormLayout(tab)

        self.experiment_step_size = QDoubleSpinBox()
        self.experiment_step_size.setDecimals(1)
        self.experiment_step_size.setRange(0.5, 50.0)
        self.experiment_step_size.setSingleStep(0.5)
        self.experiment_step_size.setValue(self.config.get("experiment_step_size", 5.0))
        self.experiment_step_size.setSuffix(" %")
        layout.addRow("Step Size:", self.experiment_step_size)

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

        # ── RH PI Controller ────────────────────────────────────────────────
        from PyQt6.QtWidgets import QLabel
        layout.addRow(QLabel("── RH PI Controller ──"))

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

        self.rh_max_step = QDoubleSpinBox()
        self.rh_max_step.setDecimals(3)
        self.rh_max_step.setRange(0.001, 0.5)
        self.rh_max_step.setSingleStep(0.005)
        self.rh_max_step.setValue(self.config.get("rh_max_step", 0.05))
        layout.addRow("Max step at ±100% error:", self.rh_max_step)

        self.rh_kp = QDoubleSpinBox()
        self.rh_kp.setDecimals(4)
        self.rh_kp.setRange(0.0001, 1.0)
        self.rh_kp.setSingleStep(0.001)
        self.rh_kp.setValue(self.config.get("rh_kp", 0.02))
        layout.addRow("Kp:", self.rh_kp)

        self.rh_ki = QDoubleSpinBox()
        self.rh_ki.setDecimals(5)
        self.rh_ki.setRange(0.00001, 0.1)
        self.rh_ki.setSingleStep(0.0001)
        self.rh_ki.setValue(self.config.get("rh_ki", 0.001))
        layout.addRow("Ki:", self.rh_ki)

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

        self.tabs.addTab(tab, "Experiment")

    def get_settings(self):
        return {
            "log_dir": self.log_dir.text(),
            "log_prefix": self.log_prefix.text(),
            "max_plot_points": self.max_plot_points.value(),
            "control_interval": int(self.control_interval.value()),
            "dry_mfc_enabled": bool(self.dry_mfc_enabled.isChecked()),
            "wet_mfc_enabled": bool(self.wet_mfc_enabled.isChecked()),
            "hygrometer_enabled": bool(self.hygrometer_enabled.isChecked()),
            "chiller_enabled": bool(self.chiller_enabled.isChecked()),
            "dry_mfc_port": self.dry_mfc_port.text(),
            "wet_mfc_port": self.wet_mfc_port.text(),
            "hygrometer_port": self.hygrometer_port.text(),
            "mfc_baudrate": self.mfc_baudrate.value(),
            "hygrometer_baudrate": self.hygrometer_baudrate.value(),
            "experiment_step_size": self.experiment_step_size.value(),
            "experiment_hold_time": self.experiment_hold_time.value(),
            "max_flow": self.max_flow.value(),
            "rh_settling_time": self.rh_settling_time.value(),
            "rh_settling_time_min": self.rh_settling_time_min.value(),
            "rh_deadband": self.rh_deadband.value(),
            "rh_max_step": self.rh_max_step.value(),
            "rh_kp": self.rh_kp.value(),
            "rh_ki": self.rh_ki.value(),
            "rh_kd": self.rh_kd.value(),
            "rh_derivative_filter_tau": self.rh_derivative_filter_tau.value(),
        }
