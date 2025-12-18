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

        self.t_probe_enabled = QCheckBox("Thermocouple (t_probe) enabled")
        self.t_probe_enabled.setChecked(bool(self.config.get("t_probe_enabled", False)))
        layout.addRow(self.t_probe_enabled)

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
        
        self.experiment_steps = QSpinBox()
        self.experiment_steps.setRange(1, 100)
        self.experiment_steps.setValue(self.config.get("experiment_steps", 10))
        layout.addRow("Experiment Steps:", self.experiment_steps)
        
        self.max_flow = QDoubleSpinBox()
        self.max_flow.setRange(0.1, 10.0)
        self.max_flow.setSingleStep(0.1)
        self.max_flow.setValue(self.config.get("max_flow", 2.0))
        self.max_flow.setSuffix(" L/min")
        layout.addRow("Max Flow:", self.max_flow)
        
        # The single update parameter `control_interval` (seconds)
        # controls how often data are read and the GUI plot is refreshed.
        
        self.rh_tolerance = QDoubleSpinBox()
        self.rh_tolerance.setRange(0.1, 20.0)
        self.rh_tolerance.setValue(self.config.get("rh_tolerance", 5.0))
        self.rh_tolerance.setSuffix(" %")
        layout.addRow("RH Tolerance:", self.rh_tolerance)
        
        self.stabilization_time = QDoubleSpinBox()
        self.stabilization_time.setRange(0, 600.0)
        self.stabilization_time.setValue(self.config.get("stabilization_time", 60.0))
        self.stabilization_time.setSuffix(" s")
        layout.addRow("Stabilization Time:", self.stabilization_time)
        
        self.stabilization_tolerance = QDoubleSpinBox()
        self.stabilization_tolerance.setRange(0.1, 20.0)
        self.stabilization_tolerance.setValue(self.config.get("stabilization_tolerance", 2.0))
        self.stabilization_tolerance.setSuffix(" %")
        layout.addRow("Stabilization Tolerance:", self.stabilization_tolerance)
        
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
            "t_probe_enabled": bool(self.t_probe_enabled.isChecked()),
            "chiller_enabled": bool(self.chiller_enabled.isChecked()),
            "dry_mfc_port": self.dry_mfc_port.text(),
            "wet_mfc_port": self.wet_mfc_port.text(),
            "hygrometer_port": self.hygrometer_port.text(),
            "mfc_baudrate": self.mfc_baudrate.value(),
            "hygrometer_baudrate": self.hygrometer_baudrate.value(),
            "experiment_steps": self.experiment_steps.value(),
            "max_flow": self.max_flow.value(),
            # control interval (seconds)
            "rh_tolerance": self.rh_tolerance.value(),
            "stabilization_time": self.stabilization_time.value(),
            "stabilization_tolerance": self.stabilization_tolerance.value(),
        }
