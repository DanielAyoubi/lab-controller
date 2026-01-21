import os
import importlib.util
from typing import Optional

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLabel, QGroupBox, QDoubleSpinBox, 
    QFormLayout, QMessageBox, QComboBox
)
from PyQt6.QtCore import QTimer

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
        self.target_chiller_temp: Optional[float] = None
        # Index of last consumed log message from controller
        self._log_index = 0

        # Setup UI
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)

        self._create_left_panel()
        self._create_right_panel()

        # Timer for periodic polling (read sensors, then update plot)
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.poll_and_update)
        # `control_interval` in config is in seconds; QTimer needs milliseconds
        self.update_timer.start(int(self.config.get('control_interval', 5000)))

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
            
            # Update timer interval (convert seconds -> milliseconds)
            self.update_timer.setInterval(int(self.config.get('control_interval', 5000)))
            
            # If ports changed, maybe warn user to reconnect
            QMessageBox.information(self, "Settings Updated", 
                                    "Settings have been updated. \n"
                                    "If you changed device ports, please disconnect and reconnect.")
            
            # Refresh device labels to reflect enabled/disabled settings
            try:
                for key, label in self.device_labels.items():
                    enabled = bool(self.config.get(f"{key}_enabled", True))
                    if not enabled:
                        label.setText("Disabled")
                        label.setStyleSheet("color: gray")
                    else:
                        # If controller has the device object and overall connected, show Connected
                        dev_obj = getattr(self.controller, key, None)
                        if dev_obj and self.controller.is_connected():
                            label.setText("Connected")
                            label.setStyleSheet("color: green")
                        else:
                            label.setText("Disconnected")
                            label.setStyleSheet("color: red")
            except Exception:
                pass

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

        # Device Status (per-device labels)
        device_group = QGroupBox("Device Status")
        device_layout = QFormLayout()

        # Create labels for known devices
        self.device_labels = {}
        devices = [
            ("dry_mfc", "Dry Air MFC"),
            ("wet_mfc", "Wet Air MFC"),
            ("hygrometer", "Hygrometer"),
            ("chiller", "Julabo Chiller"),
        ]
        for key, name in devices:
            lbl = QLabel("Unknown")
            lbl.setStyleSheet("color: gray")
            self.device_labels[key] = lbl
            # Show Disabled if the device is not enabled in config, otherwise show Disconnected
            if self.config.get(f"{key}_enabled", False):
                lbl.setText("Disconnected")
                lbl.setStyleSheet("color: red")
            else:
                lbl.setText("Disabled")
                lbl.setStyleSheet("color: gray")
            device_layout.addRow(name + ":", lbl)

        device_group.setLayout(device_layout)
        layout.addWidget(device_group)

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

        # RH Control
        rh_group = QGroupBox("RH Control (PID)")
        rh_layout = QFormLayout()

        self.spin_rh_target = QDoubleSpinBox()
        self.spin_rh_target.setRange(0, 100)
        self.spin_rh_target.setValue(50.0)
        self.spin_rh_target.setSuffix(" %")

        self.spin_rh_total_flow = QDoubleSpinBox()
        self.spin_rh_total_flow.setRange(0, 5.0)
        self.spin_rh_total_flow.setSingleStep(0.1)
        self.spin_rh_total_flow.setValue(2.0)
        self.spin_rh_total_flow.setSuffix(" L/min")

        self.btn_toggle_rh_control = QPushButton("Start RH Control")
        # self.btn_toggle_rh_control.setCheckable(True) # Managing state manually might be better
        self.btn_toggle_rh_control.clicked.connect(self.toggle_rh_control)
        self.btn_toggle_rh_control.setEnabled(False)

        rh_layout.addRow("Target RH:", self.spin_rh_target)
        rh_layout.addRow("Total Flow:", self.spin_rh_total_flow)
        rh_layout.addRow(self.btn_toggle_rh_control)
        rh_group.setLayout(rh_layout)
        layout.addWidget(rh_group)

        # Chiller Control
        chiller_group = QGroupBox("Chiller Control")
        chiller_layout = QFormLayout()
        
        self.spin_chiller_temp = QDoubleSpinBox()
        self.spin_chiller_temp.setRange(-20, 100)
        self.spin_chiller_temp.setSingleStep(0.1)
        self.spin_chiller_temp.setSuffix(" °C")
        
        self.btn_set_chiller = QPushButton("Set Temperature")
        self.btn_set_chiller.clicked.connect(self.set_chiller_temp)
        self.btn_set_chiller.setEnabled(False)
        
        self.lbl_chiller_monitor = QLabel("Monitor: Inactive")
        self.lbl_chiller_monitor.setStyleSheet("color: gray")
        
        chiller_layout.addRow("Set Temp:", self.spin_chiller_temp)
        chiller_layout.addRow(self.btn_set_chiller)
        chiller_layout.addRow(self.lbl_chiller_monitor)
        
        chiller_group.setLayout(chiller_layout)
        layout.addWidget(chiller_group)

        # Experiment Control
        exp_group = QGroupBox("Automated Experiment")
        exp_layout = QFormLayout()
        
        self.combo_direction = QComboBox()
        self.combo_direction.addItems(["up", "down"])
        self.combo_direction.setCurrentText(self.config.get('experiment_direction', 'up'))
        
        self.spin_min_rh = QDoubleSpinBox()
        self.spin_min_rh.setRange(0.0, 100.0)
        self.spin_min_rh.setValue(self.config.get('experiment_min_rh', 0.0))
        self.spin_min_rh.setSuffix(" %")

        self.spin_max_rh = QDoubleSpinBox()
        self.spin_max_rh.setRange(0.0, 100.0)
        self.spin_max_rh.setValue(self.config.get('experiment_max_rh', 100.0))
        self.spin_max_rh.setSuffix(" %")

        self.spin_steps = QDoubleSpinBox()
        self.spin_steps.setDecimals(0)
        self.spin_steps.setRange(1, 100)
        self.spin_steps.setValue(self.config.get('experiment_steps', 10))

        self.btn_start_exp = QPushButton("Start Experiment")
        self.btn_start_exp.clicked.connect(self.toggle_experiment)
        self.btn_start_exp.setEnabled(False)

        exp_layout.addRow("Direction:", self.combo_direction)
        exp_layout.addRow("Min RH:", self.spin_min_rh)
        exp_layout.addRow("Max RH:", self.spin_max_rh)
        exp_layout.addRow("Steps:", self.spin_steps)
        exp_layout.addRow(self.btn_start_exp)
        exp_group.setLayout(exp_layout)
        layout.addWidget(exp_group)

        # Current Readings
        readings_group = QGroupBox("Current Readings")
        readings_layout = QFormLayout()
        
        self.lbl_dry_flow = QLabel("0.00 L/min")
        self.lbl_wet_flow = QLabel("0.00 L/min")
        self.lbl_hygrometer_temp = QLabel("0.00 °C")
        self.lbl_hygrometer_rh = QLabel("0.00 %")
        self.lbl_chiller_temp = QLabel("0.00 °C")
        self.lbl_chiller_rh = QLabel("0.00 %")
        
        readings_layout.addRow("Dry Flow:", self.lbl_dry_flow)
        readings_layout.addRow("Wet Flow:", self.lbl_wet_flow)
        readings_layout.addRow("Hygrometer Temp:", self.lbl_hygrometer_temp)
        readings_layout.addRow("Chiller Temp:", self.lbl_chiller_temp)
        readings_layout.addRow("Hygrometer RH:", self.lbl_hygrometer_rh)
        readings_layout.addRow("Chiller RH:", self.lbl_chiller_rh)
        
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
                results = self.controller.connect_devices()

                # Update per-device labels
                any_connected = False
                any_failed = False
                for key, label in self.device_labels.items():
                    if key in results:
                        if results[key]:
                            label.setText("Connected")
                            label.setStyleSheet("color: green")
                            any_connected = True
                        else:
                            label.setText("Failed")
                            label.setStyleSheet("color: red")
                            any_failed = True
                    else:
                        # If device explicitly disabled in config, mark Disabled
                        if not self.config.get(f"{key}_enabled", True):
                            label.setText("Disabled")
                            label.setStyleSheet("color: gray")
                        else:
                            label.setText("Not configured")
                            label.setStyleSheet("color: gray")

                # Update overall status and buttons
                if any_connected and not any_failed:
                    self.lbl_status.setText("Status: Connected")
                    self.lbl_status.setStyleSheet("color: green")
                    self.btn_connect.setText("Disconnect")
                    self.btn_set_flow.setEnabled(True)
                    self.btn_set_chiller.setEnabled(True)
                    self.btn_start_exp.setEnabled(True)
                    self.btn_toggle_rh_control.setEnabled(True)
                elif any_connected:
                    self.lbl_status.setText("Status: Partial Connection")
                    self.lbl_status.setStyleSheet("color: orange")
                    self.btn_connect.setText("Disconnect")
                    self.btn_set_flow.setEnabled(True)
                    self.btn_set_chiller.setEnabled(True)
                    self.btn_start_exp.setEnabled(True)
                    self.btn_toggle_rh_control.setEnabled(True)
                else:
                    self.lbl_status.setText("Status: Disconnected")
                    self.lbl_status.setStyleSheet("color: red")
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))
        else:
            self.controller.disconnect_devices()
            self.lbl_status.setText("Status: Disconnected")
            self.lbl_status.setStyleSheet("color: red")
            self.btn_connect.setText("Connect Devices")
            self.btn_set_flow.setEnabled(False)
            self.btn_set_chiller.setEnabled(False)
            self.btn_start_exp.setEnabled(False)
            self.btn_toggle_rh_control.setEnabled(False)
            # Clear device labels
            if hasattr(self, 'device_labels'):
                for key, lbl in self.device_labels.items():
                    if not self.config.get(f"{key}_enabled", True):
                        lbl.setText("Disabled")
                        lbl.setStyleSheet("color: gray")
                    else:
                        lbl.setText("Disconnected")
                        lbl.setStyleSheet("color: red")

    def set_manual_flow(self):
        dry = self.spin_dry.value()
        wet = self.spin_wet.value()
        try:
            self.controller.set_flow_rates(dry_flow=dry, wet_flow=wet)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to set flow: {e}")

    def set_chiller_temp(self):
        temp = self.spin_chiller_temp.value()
        try:
            self.controller.set_chiller_temperature(temp)
            self.target_chiller_temp = temp
            self.lbl_chiller_monitor.setText("Monitor: Waiting...")
            self.lbl_chiller_monitor.setStyleSheet("color: orange")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to set chiller temperature: {e}")

    def toggle_rh_control(self):
        if self.controller.rh_control_active:
            # Stop
            self.controller.set_rh_control_active(False)
            self.btn_toggle_rh_control.setText("Start RH Control")
            self.btn_toggle_rh_control.setStyleSheet("")
            
            # Re-enable inputs
            self.btn_set_flow.setEnabled(True)
            self.spin_rh_target.setEnabled(True)
            self.spin_rh_total_flow.setEnabled(True)
            self.btn_start_exp.setEnabled(True)
        else:
            # Start
            target = self.spin_rh_target.value()
            total_flow = self.spin_rh_total_flow.value()
            
            self.controller.set_rh_control_active(True, target, total_flow)
            
            self.btn_toggle_rh_control.setText("Stop RH Control")
            self.btn_toggle_rh_control.setStyleSheet("background-color: #ffcccc") # Light red to indicate active/stop
            
            # Disable inputs to prevent conflict
            self.btn_set_flow.setEnabled(False)
            self.spin_rh_target.setEnabled(False) 
            self.spin_rh_total_flow.setEnabled(False)
            self.btn_start_exp.setEnabled(False)

    def toggle_experiment(self):
        if self.experiment_worker and self.experiment_worker.isRunning():
            # Stop experiment
            self.experiment_worker.stop()
            self.experiment_worker.wait()
            self.btn_start_exp.setText("Start Experiment")
            self.btn_set_flow.setEnabled(True)
            self.update_timer.start(int(self.config.get('control_interval', 5000)))
        else:
            # Start experiment
            # Update config with UI values
            self.config['experiment_direction'] = self.combo_direction.currentText()
            self.config['experiment_min_rh'] = self.spin_min_rh.value()
            self.config['experiment_max_rh'] = self.spin_max_rh.value()
            self.config['experiment_steps'] = int(self.spin_steps.value())
            
            self.experiment_worker = ExperimentWorker(self.controller, self.config)
            self.experiment_worker.finished.connect(self.on_experiment_finished)
            self.experiment_worker.error.connect(self.on_experiment_error)
            self.experiment_worker.data_ready.connect(self.update_readings)
            self.experiment_worker.start()
            
            self.update_timer.stop()
            
            self.btn_start_exp.setText("Stop Experiment")
            self.btn_set_flow.setEnabled(False)

    def on_experiment_finished(self):
        self.update_timer.start(int(self.config.get('control_interval', 5000)))
        self.btn_start_exp.setText("Start Experiment")
        self.btn_set_flow.setEnabled(True)
        QMessageBox.information(self, "Experiment", "Experiment Completed")

    def on_experiment_error(self, msg):
        self.update_timer.start(int(self.config.get('control_interval', 5000)))
        self.btn_start_exp.setText("Start Experiment")
        self.btn_set_flow.setEnabled(True)
        QMessageBox.critical(self, "Experiment Error", msg)

    def poll_and_update(self):
        try:
            if self.controller.is_connected():
                data = self.controller.read_all_sensors()
                
                # Exec RH Control Loop Logic
                if self.controller.rh_control_active:
                    # Prefer Chiller RH -> Hygrometer RH
                    curr_rh = data.get('rh_chiller')
                    if curr_rh is None:
                        curr_rh = data.get('rh_hygrometer')
                    
                    self.controller.update_rh_control_loop(curr_rh)
                    
                self.update_readings(data)
        except Exception:
            pass

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
            
            hygrometer_temp = data.get('hygrometer_temp')
            if hygrometer_temp is not None:
                self.lbl_hygrometer_temp.setText(f"{hygrometer_temp:.2f} °C")
                
            # Update RH Labels
            rh_hygro = data.get('rh_hygrometer')
            if rh_hygro is not None:
                self.lbl_hygrometer_rh.setText(f"{rh_hygro:.2f} %")
                
            rh_chill = data.get('rh_chiller')
            if rh_chill is not None:
                self.lbl_chiller_rh.setText(f"{rh_chill:.2f} %")

            # Update Chiller Temp
            chiller_temp = data.get('chiller_temp')
            if chiller_temp is not None:
                self.lbl_chiller_temp.setText(f"{chiller_temp:.2f} °C")

            # Monitor Logic
            if self.target_chiller_temp is not None:
                chiller_temp = data.get('chiller_temp')
                if chiller_temp is not None:
                    diff = abs(chiller_temp - self.target_chiller_temp)
                    if diff < 0.5: # Tolerance
                        self.lbl_chiller_monitor.setText("Monitor: Target Reached")
                        self.lbl_chiller_monitor.setStyleSheet("color: green")
                        self.target_chiller_temp = None # Stop monitoring
                    else:
                        self.lbl_chiller_monitor.setText(f"Monitor: Diff {diff:.2f} °C")

            # Update Plot
            self.plot_widget.update_plot(data)
            
        except Exception:
            # Don't spam errors
            pass

    def closeEvent(self, event):
        if self.controller:
            self.controller.disconnect_devices()
        event.accept()
