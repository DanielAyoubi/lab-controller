import os
import importlib.util
from typing import Optional

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QGroupBox, QDoubleSpinBox,
    QFormLayout, QMessageBox, QComboBox, QCheckBox, QScrollArea
)
from PyQt6.QtCore import Qt

from src.devices.controller import Controller
from src.gui.widgets.plot_widget import RealTimePlotWidget
from src.gui.workers import ExperimentWorker, PollWorker, FlowRampWorker
from src.gui.settings_dialog import SettingsDialog
from src.utility.update_settings import apply_settings

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("N-SIM Environmental Control")
        self.resize(1200, 800)

        # Load Config
        self.config = self.load_config("src/configs/config.py")
        
        # Initialize Controller
        self.controller = Controller(self.config)
        self.experiment_worker: Optional[ExperimentWorker] = None
        self.poll_worker: Optional[PollWorker] = None
        self.flow_ramp_worker: Optional[FlowRampWorker] = None
        self.target_chiller_temp: Optional[float] = None
        self._last_plot_path: Optional[str] = None

        # Setup UI
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)

        self._create_left_panel()
        self._create_right_panel()


    def load_config(self, config_path: str) -> dict:
        if not os.path.exists(config_path):
            return {}
        try:
            spec = importlib.util.spec_from_file_location("config", config_path)
            config_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(config_module)
            if hasattr(config_module, "CONFIG"):
                cfg = config_module.CONFIG.copy()
                # Merge machine-specific overrides from local_config.py (gitignored)
                local_path = os.path.join(os.path.dirname(os.path.abspath(config_path)), "local_config.py")
                if os.path.exists(local_path):
                    try:
                        local_spec = importlib.util.spec_from_file_location("local_config", local_path)
                        if local_spec is None or local_spec.loader is None:
                            raise ValueError("Could not create spec for local_config.py")
                        local_module = importlib.util.module_from_spec(local_spec)
                        local_spec.loader.exec_module(local_module)
                        if hasattr(local_module, "LOCAL_CONFIG"):
                            cfg.update(local_module.LOCAL_CONFIG)
                            print(f"Loaded local_config.py overrides: {list(local_module.LOCAL_CONFIG.keys())}")
                    except Exception as e:
                        print(f"Error loading local_config.py: {e}")
                return cfg
        except Exception as e:
            print(f"Error loading config: {e}")
        return {}

    def _start_poll_worker(self):
        interval_ms = int(self.config.get('control_interval', 5000))
        self.poll_worker = PollWorker(self.controller, interval_ms)
        self.poll_worker.data_ready.connect(self._on_poll_data)
        self.poll_worker.start()

    def _stop_poll_worker(self):
        if self.poll_worker and self.poll_worker.isRunning():
            self.poll_worker.stop()
            self.poll_worker.wait()
        self.poll_worker = None

    def open_settings(self):
        dialog = SettingsDialog(self.config, self)
        if dialog.exec():
            new_settings = dialog.get_settings()
            self.config.update(new_settings)
            
            # Update controller settings
            if self.controller:
                apply_settings(self.controller.config, self.config, self.controller.logger, self.controller.pid)

            # Apply changes
            if hasattr(self, 'plot_widget'):
                self.plot_widget.set_max_points(self.config.get('max_plot_points', 500))
            
            # Update poll interval (takes effect on the next sleep cycle)
            if self.poll_worker:
                self.poll_worker.interval_ms = int(self.config.get('control_interval', 5000))
            
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
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 4, 4, 4)

        # Connection Status
        conn_group = QGroupBox("Device Connection")
        conn_layout = QVBoxLayout()
        self.btn_connect = QPushButton("Connect Devices")
        self.btn_connect.clicked.connect(self.toggle_connection)
        self.lbl_status = QLabel("Status: Disconnected")
        self.lbl_status.setStyleSheet("color: red")
        self.chk_save_csv = QCheckBox("Save data to CSV")
        self.chk_save_csv.setChecked(True)
        conn_layout.addWidget(self.lbl_status)
        conn_layout.addWidget(self.chk_save_csv)
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

        self.lbl_rh_pid_status = QLabel("Inactive")
        self.lbl_rh_pid_status.setStyleSheet("color: gray")

        rh_layout.addRow("Target RH:", self.spin_rh_target)
        rh_layout.addRow("Total Flow:", self.spin_rh_total_flow)
        rh_layout.addRow(self.btn_toggle_rh_control)
        rh_layout.addRow("PID Status:", self.lbl_rh_pid_status)
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
        exp_group = QGroupBox("RH Ramp Experiment")
        exp_layout = QFormLayout()

        self.combo_direction = QComboBox()
        self.combo_direction.addItems(["up", "down"])
        self.combo_direction.setCurrentText(self.config.get('experiment_direction', 'up'))

        self.spin_step_size = QDoubleSpinBox()
        self.spin_step_size.setDecimals(1)
        self.spin_step_size.setRange(0.5, 50.0)
        self.spin_step_size.setSingleStep(0.5)
        self.spin_step_size.setValue(self.config.get('experiment_step_size', 5.0))
        self.spin_step_size.setSuffix(" %")

        self.spin_hold_time = QDoubleSpinBox()
        self.spin_hold_time.setDecimals(0)
        self.spin_hold_time.setRange(10.0, 3600.0)
        self.spin_hold_time.setSingleStep(10.0)
        self.spin_hold_time.setValue(self.config.get('experiment_hold_time', 180.0))
        self.spin_hold_time.setSuffix(" s")

        self.spin_rh_lower = QDoubleSpinBox()
        self.spin_rh_lower.setDecimals(1)
        self.spin_rh_lower.setRange(0.0, 100.0)
        self.spin_rh_lower.setSingleStep(1.0)
        self.spin_rh_lower.setValue(self.config.get('experiment_rh_lower', 0.0))
        self.spin_rh_lower.setSuffix(" %")

        self.spin_rh_upper = QDoubleSpinBox()
        self.spin_rh_upper.setDecimals(1)
        self.spin_rh_upper.setRange(0.0, 100.0)
        self.spin_rh_upper.setSingleStep(1.0)
        self.spin_rh_upper.setValue(self.config.get('experiment_rh_upper', 90.0))
        self.spin_rh_upper.setSuffix(" %")

        self.btn_start_exp = QPushButton("Start Experiment")
        self.btn_start_exp.clicked.connect(self.toggle_experiment)
        self.btn_start_exp.setEnabled(False)

        exp_layout.addRow("Direction:", self.combo_direction)
        exp_layout.addRow("Step Size (% wet flow):", self.spin_step_size)
        exp_layout.addRow("Step Wait Time:", self.spin_hold_time)
        exp_layout.addRow("RH Lower Limit:", self.spin_rh_lower)
        exp_layout.addRow("RH Upper Limit:", self.spin_rh_upper)
        exp_layout.addRow(self.btn_start_exp)
        exp_group.setLayout(exp_layout)
        layout.addWidget(exp_group)

        # Settings
        self.btn_settings = QPushButton("Settings")
        self.btn_settings.clicked.connect(self.open_settings)
        layout.addWidget(self.btn_settings)

        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(panel)
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(370)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.main_layout.addWidget(scroll)

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

                # Start background CSV log if requested
                if any_connected and self.chk_save_csv.isChecked():
                    try:
                        self.controller.logger.start_new_log(self.controller.log_fields)
                    except Exception as e:
                        print(f"Failed to start background log: {e}")

                if any_connected:
                    self._start_poll_worker()
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))
        else:
            self._stop_poll_worker()
            self.controller.logger.close()
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
        self.btn_set_flow.setEnabled(False)
        self._stop_poll_worker()  # avoid concurrent serial access during ramp
        self.flow_ramp_worker = FlowRampWorker(self.controller, dry, wet)
        self.flow_ramp_worker.finished.connect(self._on_flow_ramp_finished)
        self.flow_ramp_worker.error.connect(self._on_flow_ramp_error)
        self.flow_ramp_worker.start()

    def _on_flow_ramp_finished(self):
        self.flow_ramp_worker = None
        self.btn_set_flow.setEnabled(True)
        if self.controller.is_connected():
            self._start_poll_worker()

    def _on_flow_ramp_error(self, msg: str):
        self.flow_ramp_worker = None
        self.btn_set_flow.setEnabled(True)
        if self.controller.is_connected():
            self._start_poll_worker()
        QMessageBox.warning(self, "Error", f"Failed to set flow: {msg}")

    def set_chiller_temp(self):
        temp = self.spin_chiller_temp.value()
        self._stop_poll_worker()
        try:
            self.controller.chiller.set_setpoint_temperature(temp)
            self.controller.chiller.start_control()
            self.target_chiller_temp = temp
            self.lbl_chiller_monitor.setText("Monitor: Waiting...")
            self.lbl_chiller_monitor.setStyleSheet("color: orange")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to set chiller temperature: {e}")
        finally:
            if self.controller.is_connected():
                self._start_poll_worker()

    def toggle_rh_control(self):
        if self.controller.rh_control_active:
            # Stop
            self.controller.set_rh_control_active(False)
            self.btn_toggle_rh_control.setText("Start RH Control")
            self.btn_toggle_rh_control.setStyleSheet("")
            self.lbl_rh_pid_status.setText("Inactive")
            self.lbl_rh_pid_status.setStyleSheet("color: gray")
            
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
            self.experiment_worker.wait(5000)
            self.btn_start_exp.setText("Start Experiment")
            self.btn_set_flow.setEnabled(True)
            self._start_poll_worker()
        else:
            # Start experiment — sync UI values into config
            self.config['experiment_direction'] = self.combo_direction.currentText()
            self.config['experiment_step_size'] = self.spin_step_size.value()
            self.config['experiment_hold_time'] = self.spin_hold_time.value()
            self.config['experiment_rh_lower'] = self.spin_rh_lower.value()
            self.config['experiment_rh_upper'] = self.spin_rh_upper.value()
            # Close background log; the experiment will open its own CSV
            self.controller.logger.close()

            self._stop_poll_worker()

            self.experiment_worker = ExperimentWorker(self.controller, self.config)
            self.experiment_worker.finished.connect(self.on_experiment_finished)
            self.experiment_worker.error.connect(self.on_experiment_error)
            self.experiment_worker.progress.connect(self._on_experiment_progress)
            self.experiment_worker.data_ready.connect(self.update_readings)
            self.experiment_worker.start()

            self.btn_start_exp.setText("Stop Experiment")
            self.btn_set_flow.setEnabled(False)

    def _on_experiment_progress(self, msg: str):
        if msg.startswith("PLOT_PATH:"):
            self._last_plot_path = msg[len("PLOT_PATH:"):]

    def on_experiment_finished(self):
        self._start_poll_worker()
        self.btn_start_exp.setText("Start Experiment")
        self.btn_set_flow.setEnabled(True)

        # Restart background log if CSV saving is enabled and devices are still connected
        if self.chk_save_csv.isChecked() and self.controller.is_connected():
            try:
                self.controller.logger.start_new_log(self.controller.log_fields)
            except Exception as e:
                print(f"Failed to restart background log: {e}")

        plot_path = self._last_plot_path
        self._last_plot_path = None
        msg = "Experiment completed."
        if plot_path:
            msg += f"\n\nPlot saved to:\n{plot_path}"
        QMessageBox.information(self, "Experiment", msg)

    def on_experiment_error(self, msg):
        self._start_poll_worker()
        self.btn_start_exp.setText("Start Experiment")
        self.btn_set_flow.setEnabled(True)
        self._last_plot_path = None
        QMessageBox.critical(self, "Experiment Error", msg)

    def _on_poll_data(self, data: dict):
        try:
            curr_rh = data.get('rh_chiller') if data.get('rh_chiller') is not None else data.get('rh_hygrometer')
            if self.controller.rh_control_active:
                self.controller.update_rh_control_loop(curr_rh)
                status = self.controller.get_rh_control_status(curr_rh)
                self.lbl_rh_pid_status.setText(status)
                if "Settling" in status:
                    self.lbl_rh_pid_status.setStyleSheet("color: orange")
                elif "At target" in status:
                    self.lbl_rh_pid_status.setStyleSheet("color: green")
                else:
                    self.lbl_rh_pid_status.setStyleSheet("color: blue")
            else:
                self.lbl_rh_pid_status.setText("Inactive")
                self.lbl_rh_pid_status.setStyleSheet("color: gray")
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
            
            
            # Update Plot
            self.plot_widget.update_plot(data)
            
        except Exception:
            # Don't spam errors
            pass

    def closeEvent(self, event):
        if self.controller:
            self.controller.disconnect_devices()
        event.accept()
