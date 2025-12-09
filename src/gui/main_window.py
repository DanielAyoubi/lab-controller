import sys
import os
import importlib.util
from typing import Dict, Optional

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLabel, QGroupBox, QDoubleSpinBox, 
    QFormLayout, QMessageBox, QTabWidget, QComboBox
)
from PyQt6.QtCore import QTimer, Qt

from src.devices.controller import Controller
from src.gui.widgets.plot_widget import RealTimePlotWidget
from src.gui.workers import ExperimentWorker
from src.gui.settings_dialog import SettingsDialog

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("N-SIM Environmental Control")
        self.resize(1200, 800)

        # Load Config
        self.config = self.load_config("config.py")
        
        # Initialize Controller
        self.controller = Controller(self.config)
        self.experiment_worker: Optional[ExperimentWorker] = None

        # Setup UI
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)

        self._create_left_panel()
        self._create_right_panel()

        # Timer for updates
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_readings)
        self.update_timer.start(1000)  # 1 second update

    def load_config(self, config_path: str) -> dict:
        if not os.path.exists(config_path):
            return {}
        try:
            spec = importlib.util.spec_from_file_location("config", config_path)
            config_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(config_module)
            if hasattr(config_module, "CONFIG"):
                return config_module.CONFIG.copy()
        except Exception as e:
            print(f"Error loading config: {e}")
        return {}

    def open_settings(self):
        dialog = SettingsDialog(self.config, self)
        if dialog.exec():
            new_settings = dialog.get_settings()
            self.config.update(new_settings)
            
            # Update controller settings
            if self.controller:
                self.controller.update_settings(self.config)

            # Apply changes
            if hasattr(self, 'plot_widget'):
                self.plot_widget.set_max_points(self.config.get('max_plot_points', 500))
            
            # Update timer interval
            self.update_timer.setInterval(self.config.get('plot_update_interval', 1000))
            
            # If ports changed, maybe warn user to reconnect
            QMessageBox.information(self, "Settings Updated", 
                                    "Settings have been updated. \n"
                                    "If you changed device ports, please disconnect and reconnect.")

    def _create_left_panel(self):
        panel = QWidget()
        panel.setFixedWidth(350)
        layout = QVBoxLayout(panel)

        # Connection Status
        conn_group = QGroupBox("Device Connection")
        conn_layout = QVBoxLayout()
        self.btn_connect = QPushButton("Connect Devices")
        self.btn_connect.clicked.connect(self.toggle_connection)
        self.lbl_status = QLabel("Status: Disconnected")
        self.lbl_status.setStyleSheet("color: red")
        conn_layout.addWidget(self.lbl_status)
        conn_layout.addWidget(self.btn_connect)
        conn_group.setLayout(conn_layout)
        layout.addWidget(conn_group)

        # Manual Control
        manual_group = QGroupBox("Manual Control")
        manual_layout = QFormLayout()
        
        self.spin_dry = QDoubleSpinBox()
        self.spin_dry.setRange(0, 5.0)
        self.spin_dry.setSingleStep(0.1)
        self.spin_dry.setSuffix(" L/min")
        
        self.spin_wet = QDoubleSpinBox()
        self.spin_wet.setRange(0, 5.0)
        self.spin_wet.setSingleStep(0.1)
        self.spin_wet.setSuffix(" L/min")

        self.btn_set_flow = QPushButton("Set Flow Rates")
        self.btn_set_flow.clicked.connect(self.set_manual_flow)
        self.btn_set_flow.setEnabled(False)

        manual_layout.addRow("Dry Air:", self.spin_dry)
        manual_layout.addRow("Wet Air:", self.spin_wet)
        manual_layout.addRow(self.btn_set_flow)
        manual_group.setLayout(manual_layout)
        layout.addWidget(manual_group)

        # Experiment Control
        exp_group = QGroupBox("Automated Experiment")
        exp_layout = QFormLayout()
        
        self.combo_direction = QComboBox()
        self.combo_direction.addItems(["up", "down"])
        
        self.spin_duration = QDoubleSpinBox()
        self.spin_duration.setRange(1, 600)
        self.spin_duration.setValue(60)
        self.spin_duration.setSuffix(" min")

        self.btn_start_exp = QPushButton("Start Experiment")
        self.btn_start_exp.clicked.connect(self.toggle_experiment)
        self.btn_start_exp.setEnabled(False)

        exp_layout.addRow("Direction:", self.combo_direction)
        exp_layout.addRow("Duration:", self.spin_duration)
        exp_layout.addRow(self.btn_start_exp)
        exp_group.setLayout(exp_layout)
        layout.addWidget(exp_group)

        # Current Readings
        readings_group = QGroupBox("Current Readings")
        readings_layout = QFormLayout()
        
        self.lbl_dry_flow = QLabel("0.00 L/min")
        self.lbl_wet_flow = QLabel("0.00 L/min")
        self.lbl_temp = QLabel("0.00 °C")
        self.lbl_rh = QLabel("0.00 %")
        
        readings_layout.addRow("Dry Flow:", self.lbl_dry_flow)
        readings_layout.addRow("Wet Flow:", self.lbl_wet_flow)
        readings_layout.addRow("Temperature:", self.lbl_temp)
        readings_layout.addRow("Humidity:", self.lbl_rh)
        
        readings_group.setLayout(readings_layout)
        layout.addWidget(readings_group)

        # Settings
        self.btn_settings = QPushButton("Settings")
        self.btn_settings.clicked.connect(self.open_settings)
        layout.addWidget(self.btn_settings)

        layout.addStretch()
        self.main_layout.addWidget(panel)

    def _create_right_panel(self):
        self.plot_widget = RealTimePlotWidget()
        self.main_layout.addWidget(self.plot_widget)

    def toggle_connection(self):
        if self.btn_connect.text() == "Connect Devices":
            try:
                if self.controller.connect_devices():
                    self.lbl_status.setText("Status: Connected")
                    self.lbl_status.setStyleSheet("color: green")
                    self.btn_connect.setText("Disconnect")
                    self.btn_set_flow.setEnabled(True)
                    self.btn_start_exp.setEnabled(True)
                else:
                    QMessageBox.warning(self, "Connection Error", "Some devices failed to connect.")
                    # Still allow partial functionality?
                    self.lbl_status.setText("Status: Partial Connection")
                    self.lbl_status.setStyleSheet("color: orange")
                    self.btn_connect.setText("Disconnect")
                    self.btn_set_flow.setEnabled(True)
                    self.btn_start_exp.setEnabled(True)
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))
        else:
            self.controller.disconnect_devices()
            self.lbl_status.setText("Status: Disconnected")
            self.lbl_status.setStyleSheet("color: red")
            self.btn_connect.setText("Connect Devices")
            self.btn_set_flow.setEnabled(False)
            self.btn_start_exp.setEnabled(False)

    def set_manual_flow(self):
        dry = self.spin_dry.value()
        wet = self.spin_wet.value()
        try:
            self.controller.set_flow_rates(dry_flow=dry, wet_flow=wet)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to set flow: {e}")

    def toggle_experiment(self):
        if self.experiment_worker and self.experiment_worker.isRunning():
            # Stop experiment
            self.experiment_worker.stop()
            self.experiment_worker.wait()
            self.btn_start_exp.setText("Start Experiment")
            self.btn_set_flow.setEnabled(True)
            self.update_timer.start(1000)
        else:
            # Start experiment
            # Update config with UI values
            self.config['experiment_direction'] = self.combo_direction.currentText()
            self.config['experiment_duration'] = self.spin_duration.value()
            
            self.experiment_worker = ExperimentWorker(self.controller, self.config)
            self.experiment_worker.finished.connect(self.on_experiment_finished)
            self.experiment_worker.error.connect(self.on_experiment_error)
            self.experiment_worker.data_ready.connect(self.update_readings)
            self.experiment_worker.start()
            
            self.update_timer.stop()
            
            self.btn_start_exp.setText("Stop Experiment")
            self.btn_set_flow.setEnabled(False)

    def on_experiment_finished(self):
        self.update_timer.start(1000)
        self.btn_start_exp.setText("Start Experiment")
        self.btn_set_flow.setEnabled(True)
        QMessageBox.information(self, "Experiment", "Experiment Completed")

    def on_experiment_error(self, msg):
        self.update_timer.start(1000)
        self.btn_start_exp.setText("Start Experiment")
        self.btn_set_flow.setEnabled(True)
        QMessageBox.critical(self, "Experiment Error", msg)

    def update_readings(self, data=None):
        # Only read if connected or at least initialized
        # The controller.read_all_sensors() handles missing devices by returning None
        try:
            if data is None:
                if self.controller.is_connected():
                    data = self.controller.read_all_sensors()
                else:
                    return
            
            # Update Labels
            if data.get('dry_flow') is not None:
                self.lbl_dry_flow.setText(f"{data['dry_flow']:.2f} L/min")
            if data.get('wet_flow') is not None:
                self.lbl_wet_flow.setText(f"{data['wet_flow']:.2f} L/min")
            
            temp = data.get('cell_temp') or data.get('ambient_temp')
            if temp is not None:
                self.lbl_temp.setText(f"{temp:.2f} °C")
                
            rh = data.get('relative_humidity')
            if rh is not None:
                self.lbl_rh.setText(f"{rh:.2f} %")

            # Update Plot
            self.plot_widget.update_plot(data)
            
        except Exception:
            # Don't spam errors
            pass

    def closeEvent(self, event):
        if self.controller:
            self.controller.stop()
            self.controller.disconnect_devices()
        event.accept()
