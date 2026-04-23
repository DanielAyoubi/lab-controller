import os
import importlib.util
from typing import Optional

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QGroupBox, QDoubleSpinBox,
    QFormLayout, QMessageBox, QComboBox, QCheckBox, QScrollArea, QGridLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QSizePolicy,
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
            
            # Refresh device dot indicators to reflect enabled/disabled settings
            try:
                for key in self.device_labels:
                    enabled = bool(self.config.get(f"{key}_enabled", True))
                    if not enabled:
                        self._set_device_dot(key, "Disabled")
                    else:
                        dev_obj = getattr(self.controller, key, None)
                        if dev_obj and self.controller.is_connected():
                            self._set_device_dot(key, "Connected")
                        else:
                            self._set_device_dot(key, "Disconnected")
            except Exception:
                pass

    def _set_device_dot(self, key: str, status: str):
        dot = self.device_labels.get(key)
        if dot is None:
            return
        color_map = {
            "Connected":      "#22aa22",
            "Failed":         "#dd2222",
            "Disconnected":   "#dd2222",
            "Disabled":       "#888888",
            "Not configured": "#888888",
        }
        dot.setStyleSheet(f"color: {color_map.get(status, '#888888')}; font-size: 14px;")
        dot.setToolTip(status)

    def _create_left_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 4, 4, 4)

        # Devices — compact: colored-dot indicators + connect button on one row
        conn_group = QGroupBox("Devices")
        conn_vbox = QVBoxLayout()
        conn_vbox.setSpacing(4)

        # 2×2 grid of indicators
        dot_grid = QWidget()
        dot_layout = QGridLayout(dot_grid)
        dot_layout.setContentsMargins(0, 0, 0, 0)
        dot_layout.setSpacing(2)

        self.device_labels = {}
        _devices = [
            ("dry_mfc",    "Dry MFC"),
            ("wet_mfc",    "Wet MFC"),
            ("hygrometer", "Hygro"),
            ("chiller",    "Chiller"),
        ]
        for idx, (key, short_name) in enumerate(_devices):
            dot = QLabel("●")
            dot.setFixedWidth(16)
            if self.config.get(f"{key}_enabled", False):
                dot.setStyleSheet("color: #dd2222; font-size: 14px;")
                dot.setToolTip("Disconnected")
            else:
                dot.setStyleSheet("color: #888888; font-size: 14px;")
                dot.setToolTip("Disabled")
            self.device_labels[key] = dot

            name_lbl = QLabel(short_name)
            name_lbl.setStyleSheet("font-size: 11px;")

            cell = QWidget()
            cell_h = QHBoxLayout(cell)
            cell_h.setContentsMargins(0, 0, 0, 0)
            cell_h.setSpacing(3)
            cell_h.addWidget(dot)
            cell_h.addWidget(name_lbl)
            cell_h.addStretch()

            row, col = divmod(idx, 2)
            dot_layout.addWidget(cell, row, col)

        conn_vbox.addWidget(dot_grid)

        # Bottom row: Save CSV checkbox + Connect/Disconnect button
        conn_bottom = QHBoxLayout()
        self.chk_save_csv = QCheckBox("Save CSV")
        self.chk_save_csv.setChecked(True)
        self.btn_connect = QPushButton("Connect")
        self.btn_connect.clicked.connect(self.toggle_connection)
        conn_bottom.addWidget(self.chk_save_csv)
        conn_bottom.addWidget(self.btn_connect)
        conn_vbox.addLayout(conn_bottom)

        conn_group.setLayout(conn_vbox)
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

        self.chk_ramp_flow = QCheckBox("Stepwise ramp")
        self.chk_ramp_flow.setChecked(True)
        self.chk_ramp_flow.setToolTip(
            "Checked: ramp flows gradually in 0.05 L/min steps (takes ~1 s/step).\n"
            "Unchecked: jump directly to setpoint."
        )

        self.btn_set_flow = QPushButton("Set Flow Rates")
        self.btn_set_flow.clicked.connect(self.set_manual_flow)
        self.btn_set_flow.setEnabled(False)

        manual_layout.addRow("Dry Flow:", self.spin_dry)
        manual_layout.addRow("Wet Flow:", self.spin_wet)
        manual_layout.addRow(self.chk_ramp_flow)
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

        # Mode selector (always visible)
        self.combo_experiment_mode = QComboBox()
        self.combo_experiment_mode.addItems(["Flow", "RH", "Hysteresis"])
        _mode_map = {'flow': 'Flow', 'rh': 'RH', 'hysteresis': 'Hysteresis'}
        saved_mode = self.config.get('experiment_mode', 'flow')
        self.combo_experiment_mode.setCurrentText(_mode_map.get(saved_mode.lower(), 'Flow'))

        # Hold time (always visible, shared between modes)
        self.spin_hold_time = QDoubleSpinBox()
        self.spin_hold_time.setDecimals(0)
        self.spin_hold_time.setRange(10.0, 3600.0)
        self.spin_hold_time.setSingleStep(10.0)
        self.spin_hold_time.setValue(self.config.get('experiment_hold_time', 180.0))
        self.spin_hold_time.setSuffix(" s")

        # ── Flow mode widget group ──────────────────────────────────────────
        self.flow_mode_widget = QWidget()
        flow_form = QFormLayout(self.flow_mode_widget)
        flow_form.setContentsMargins(0, 0, 0, 0)

        self.spin_flow_start = QDoubleSpinBox()
        self.spin_flow_start.setDecimals(3)
        self.spin_flow_start.setRange(0.0, 10.0)
        self.spin_flow_start.setSingleStep(0.05)
        self.spin_flow_start.setValue(self.config.get('experiment_flow_start', 0.0))
        self.spin_flow_start.setSuffix(" L/min")

        self.spin_flow_end = QDoubleSpinBox()
        self.spin_flow_end.setDecimals(3)
        self.spin_flow_end.setRange(0.0, 10.0)
        self.spin_flow_end.setSingleStep(0.05)
        self.spin_flow_end.setValue(self.config.get('experiment_flow_end', 2.0))
        self.spin_flow_end.setSuffix(" L/min")

        self.spin_flow_step = QDoubleSpinBox()
        self.spin_flow_step.setDecimals(3)
        self.spin_flow_step.setRange(0.001, 2.0)
        self.spin_flow_step.setSingleStep(0.05)
        self.spin_flow_step.setValue(self.config.get('experiment_flow_step', 0.1))
        self.spin_flow_step.setSuffix(" L/min")

        flow_form.addRow("Start wet flow:", self.spin_flow_start)
        flow_form.addRow("End wet flow:", self.spin_flow_end)
        flow_form.addRow("Wet flow step:", self.spin_flow_step)

        # ── RH mode widget group ────────────────────────────────────────────
        self.rh_mode_widget = QWidget()
        rh_form = QFormLayout(self.rh_mode_widget)
        rh_form.setContentsMargins(0, 0, 0, 0)

        self.spin_rh_start = QDoubleSpinBox()
        self.spin_rh_start.setDecimals(1)
        self.spin_rh_start.setRange(0.0, 100.0)
        self.spin_rh_start.setSingleStep(1.0)
        self.spin_rh_start.setValue(self.config.get('experiment_rh_lower', 0.0))
        self.spin_rh_start.setSuffix(" %")

        self.spin_rh_end = QDoubleSpinBox()
        self.spin_rh_end.setDecimals(1)
        self.spin_rh_end.setRange(0.0, 100.0)
        self.spin_rh_end.setSingleStep(1.0)
        self.spin_rh_end.setValue(self.config.get('experiment_rh_upper', 90.0))
        self.spin_rh_end.setSuffix(" %")

        self.spin_rh_step = QDoubleSpinBox()
        self.spin_rh_step.setDecimals(1)
        self.spin_rh_step.setRange(0.1, 50.0)
        self.spin_rh_step.setSingleStep(1.0)
        self.spin_rh_step.setValue(self.config.get('experiment_rh_step', 5.0))
        self.spin_rh_step.setSuffix(" %")

        rh_form.addRow("Start RH:", self.spin_rh_start)
        rh_form.addRow("End RH:", self.spin_rh_end)
        rh_form.addRow("RH step:", self.spin_rh_step)

        # ── Hysteresis mode widget ──────────────────────────────────────────
        self.hysteresis_widget = QWidget()
        hyst_vbox = QVBoxLayout(self.hysteresis_widget)
        hyst_vbox.setContentsMargins(0, 0, 0, 0)
        hyst_vbox.setSpacing(4)

        _col_headers = ["T (°C)", "Step%", "Start%", "End%", "Prog", "Wait(s)"]
        self.hysteresis_table = QTableWidget(0, len(_col_headers))
        self.hysteresis_table.setHorizontalHeaderLabels(_col_headers)
        _hdr = self.hysteresis_table.horizontalHeader()
        if _hdr is not None:
            # Stretch columns 1-3 (Step/Start/End) equally; fix narrow columns
            for col in [0, 4, 5]:
                _hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            for col in [1, 2, 3]:
                _hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        self.hysteresis_table.setColumnWidth(0, 52)   # T (°C)
        self.hysteresis_table.setColumnWidth(4, 42)   # Prog
        self.hysteresis_table.setColumnWidth(5, 58)   # Wait(s)
        self.hysteresis_table.setMinimumHeight(120)
        self.hysteresis_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        hyst_vbox.addWidget(self.hysteresis_table)

        hyst_btn_row = QHBoxLayout()
        btn_add_row = QPushButton("Add Row")
        btn_add_row.clicked.connect(self._hysteresis_add_row)
        btn_remove_row = QPushButton("Remove Row")
        btn_remove_row.clicked.connect(self._hysteresis_remove_row)
        hyst_btn_row.addWidget(btn_add_row)
        hyst_btn_row.addWidget(btn_remove_row)
        hyst_vbox.addLayout(hyst_btn_row)

        # Pre-populate from config or add one default row
        saved_steps = self.config.get('experiment_hysteresis_steps', [])
        if saved_steps:
            for s in saved_steps:
                self._hysteresis_add_row(s)
        else:
            self._hysteresis_add_row()

        # ── Assemble experiment panel ───────────────────────────────────────
        self.btn_start_exp = QPushButton("Start Experiment")
        self.btn_start_exp.clicked.connect(self.toggle_experiment)
        self.btn_start_exp.setEnabled(False)

        exp_layout.addRow("Mode:", self.combo_experiment_mode)
        exp_layout.addRow("Hold time:", self.spin_hold_time)
        exp_layout.addRow(self.flow_mode_widget)
        exp_layout.addRow(self.rh_mode_widget)
        exp_layout.addRow(self.hysteresis_widget)
        exp_layout.addRow(self.btn_start_exp)

        self.combo_experiment_mode.currentTextChanged.connect(self._on_experiment_mode_changed)
        self._on_experiment_mode_changed(self.combo_experiment_mode.currentText())

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
        if self.btn_connect.text() == "Connect":
            try:
                results = self.controller.connect_devices()

                any_connected = False
                any_failed = False
                for key in self.device_labels:
                    if key in results:
                        if results[key]:
                            self._set_device_dot(key, "Connected")
                            any_connected = True
                        else:
                            self._set_device_dot(key, "Failed")
                            any_failed = True
                    else:
                        if not self.config.get(f"{key}_enabled", True):
                            self._set_device_dot(key, "Disabled")
                        else:
                            self._set_device_dot(key, "Not configured")

                if any_connected and not any_failed:
                    self.btn_connect.setText("Disconnect")
                    self.btn_connect.setStyleSheet("background-color: #ccffcc;")
                    self.btn_set_flow.setEnabled(True)
                    self.btn_set_chiller.setEnabled(True)
                    self.btn_start_exp.setEnabled(True)
                    self.btn_toggle_rh_control.setEnabled(True)
                elif any_connected:
                    self.btn_connect.setText("Disconnect")
                    self.btn_connect.setStyleSheet("background-color: #ffe0aa;")
                    self.btn_set_flow.setEnabled(True)
                    self.btn_set_chiller.setEnabled(True)
                    self.btn_start_exp.setEnabled(True)
                    self.btn_toggle_rh_control.setEnabled(True)
                # else: all failed — button stays "Connect", no style change

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
            self.btn_connect.setText("Connect")
            self.btn_connect.setStyleSheet("")
            self.btn_set_flow.setEnabled(False)
            self.btn_set_chiller.setEnabled(False)
            self.btn_start_exp.setEnabled(False)
            self.btn_toggle_rh_control.setEnabled(False)
            for key in self.device_labels:
                status = "Disabled" if not self.config.get(f"{key}_enabled", True) else "Disconnected"
                self._set_device_dot(key, status)

    def set_manual_flow(self):
        dry = self.spin_dry.value()
        wet = self.spin_wet.value()
        self._stop_poll_worker()  # avoid concurrent serial access
        if self.chk_ramp_flow.isChecked():
            # Gradual stepwise ramp via background worker
            self.btn_set_flow.setEnabled(False)
            self.flow_ramp_worker = FlowRampWorker(self.controller, dry, wet)
            self.flow_ramp_worker.finished.connect(self._on_flow_ramp_finished)
            self.flow_ramp_worker.error.connect(self._on_flow_ramp_error)
            self.flow_ramp_worker.start()
        else:
            # Instant jump — set directly, no ramp
            try:
                self.controller.set_flow_rates(dry_flow=dry, wet_flow=wet, ramp_flow=False)
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to set flow: {e}")
            finally:
                if self.controller.is_connected():
                    self._start_poll_worker()

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

    def _on_experiment_mode_changed(self, mode_text: str):
        self.flow_mode_widget.setVisible(mode_text == "Flow")
        self.rh_mode_widget.setVisible(mode_text == "RH")
        self.hysteresis_widget.setVisible(mode_text == "Hysteresis")
        # Hold-time spinbox is shared by Flow/RH but not used in Hysteresis
        # (hysteresis uses per-row wait_time instead), so hide it for clarity
        self.spin_hold_time.setVisible(mode_text != "Hysteresis")

    def toggle_experiment(self):
        if self.experiment_worker and self.experiment_worker.isRunning():
            # Signal the background thread to stop; cleanup happens in on_experiment_finished
            self.experiment_worker.stop()
            self.btn_start_exp.setText("Stopping…")
            self.btn_start_exp.setEnabled(False)
        else:
            # Start experiment — sync UI values into config
            mode = self.combo_experiment_mode.currentText().lower()  # "flow", "rh", or "hysteresis"
            self.config['experiment_mode'] = mode
            if mode == 'flow':
                self.config['experiment_hold_time'] = self.spin_hold_time.value()
                self.config['experiment_flow_start'] = self.spin_flow_start.value()
                self.config['experiment_flow_end'] = self.spin_flow_end.value()
                self.config['experiment_flow_step'] = self.spin_flow_step.value()
            elif mode == 'rh':
                self.config['experiment_hold_time'] = self.spin_hold_time.value()
                self.config['experiment_rh_lower'] = self.spin_rh_start.value()
                self.config['experiment_rh_upper'] = self.spin_rh_end.value()
                self.config['experiment_rh_step'] = self.spin_rh_step.value()
            else:  # hysteresis
                self.config['experiment_hysteresis_steps'] = self._read_hysteresis_table()
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
        was_cancelled = not self.btn_start_exp.isEnabled()  # disabled means we hit "Stopping…"
        if was_cancelled:
            try:
                self.controller.set_flow_rates(dry_flow=0.0, wet_flow=0.0,
                                               max_flow=self.config.get('max_flow', 2.0),
                                               ramp_flow=False)
            except Exception as e:
                print(f"Failed to zero flows after cancel: {e}")
        self._start_poll_worker()
        self.btn_start_exp.setText("Start Experiment")
        self.btn_start_exp.setEnabled(True)
        self.btn_set_flow.setEnabled(True)

        if was_cancelled:
            return

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
        self.btn_start_exp.setEnabled(True)
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

    def _hysteresis_add_row(self, step: dict = None):
        row = self.hysteresis_table.rowCount()
        self.hysteresis_table.insertRow(row)
        defaults = {"chiller_setpoint": 20.0, "step_size": 5.0,
                    "start_rh": 5.0, "end_rh": 80.0,
                    "program": "H", "wait_time": 180.0}
        s = step if step else defaults
        self.hysteresis_table.setItem(row, 0, QTableWidgetItem(str(s.get("chiller_setpoint", 20.0))))
        self.hysteresis_table.setItem(row, 1, QTableWidgetItem(str(s.get("step_size", 5.0))))
        self.hysteresis_table.setItem(row, 2, QTableWidgetItem(str(s.get("start_rh", 5.0))))
        self.hysteresis_table.setItem(row, 3, QTableWidgetItem(str(s.get("end_rh", 80.0))))
        prog_combo = QComboBox()
        prog_combo.addItems(["H", "D"])
        prog_combo.setCurrentText(str(s.get("program", "H")).upper())
        self.hysteresis_table.setCellWidget(row, 4, prog_combo)
        self.hysteresis_table.setItem(row, 5, QTableWidgetItem(str(s.get("wait_time", 180.0))))

    def _hysteresis_remove_row(self):
        selected = self.hysteresis_table.currentRow()
        row = selected if selected >= 0 else self.hysteresis_table.rowCount() - 1
        if row >= 0:
            self.hysteresis_table.removeRow(row)

    def _read_hysteresis_table(self) -> list:
        steps = []
        for row in range(self.hysteresis_table.rowCount()):
            def _cell(c, default=0.0):
                item = self.hysteresis_table.item(row, c)
                if item is None:
                    return default
                try:
                    return float(item.text())
                except ValueError:
                    return default
            prog_widget = self.hysteresis_table.cellWidget(row, 4)
            program = prog_widget.currentText() if prog_widget else "H"
            steps.append({
                "chiller_setpoint": _cell(0, 20.0),
                "step_size":        _cell(1, 5.0),
                "start_rh":         _cell(2, 5.0),
                "end_rh":           _cell(3, 80.0),
                "program":          program,
                "wait_time":        _cell(5, 180.0),
            })
        return steps

    def closeEvent(self, event):
        if self.controller:
            self.controller.disconnect_devices()
        event.accept()
