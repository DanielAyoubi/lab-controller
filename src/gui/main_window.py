import os
import sys
import json
from typing import Optional

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QGroupBox, QDoubleSpinBox,
    QFormLayout, QMessageBox, QComboBox, QCheckBox, QScrollArea, QGridLayout
)
from PyQt6.QtCore import Qt

from src.devices.controller import Controller
from src.gui.widgets.plot_widget import RealTimePlotWidget
from src.gui.workers import ExperimentWorker, PollWorker, FlowRampWorker
from src.gui.settings_dialog import SettingsDialog
from src.utility.update_settings import apply_settings, save_config_to_file

# Compact styling for the purge toggle (sits inline with the ramp checkbox).
_PURGE_STYLE_OFF = "font-size: 11px; padding: 2px 6px;"
_PURGE_STYLE_ON = _PURGE_STYLE_OFF + " background-color: #cc7a00; color: white;"

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("N-SIM Environmental Control")
        self.resize(1200, 800)

        # Load Config
        self.config_path: Optional[str] = None
        self.config = self.load_config()
        
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


    def load_config(self, config_path: Optional[str] = None) -> dict:
        """Load the machine-specific JSON config.

        Source files run from any CWD because the path is resolved relative to
        this module. When packaged as a PyInstaller executable, an editable
        ``config.json`` placed next to the .exe takes precedence over the copy
        bundled inside the executable — so COM ports can be changed without
        rebuilding.
        """
        candidates = self._config_search_paths(config_path)
        for path in candidates:
            if path and os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    self.config_path = path
                    return json.loads(self._strip_json_comments(f.read()))
        searched = "\n  ".join(p for p in candidates if p)
        raise FileNotFoundError(
            "Config file not found. Looked in:\n  "
            f"{searched}\n"
            "Place a config.json next to the executable (or in src/configs/ "
            "when running from source)."
        )

    @staticmethod
    def _strip_json_comments(text: str) -> str:
        """Strip ``//`` line and ``/* */`` block comments from JSON text.

        Lets ``config.json`` carry inline documentation while still being parsed
        by the standard ``json`` module. Comment markers inside string values are
        preserved (so e.g. a path or COM port containing ``//`` is left intact).
        """
        out = []
        i, n = 0, len(text)
        in_string = escape = False
        while i < n:
            c = text[i]
            if in_string:
                out.append(c)
                if escape:
                    escape = False
                elif c == "\\":
                    escape = True
                elif c == '"':
                    in_string = False
                i += 1
            elif c == '"':
                in_string = True
                out.append(c)
                i += 1
            elif c == "/" and i + 1 < n and text[i + 1] == "/":
                i += 2
                while i < n and text[i] not in "\r\n":
                    i += 1
            elif c == "/" and i + 1 < n and text[i + 1] == "*":
                i += 2
                while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                    i += 1
                i += 2
            else:
                out.append(c)
                i += 1
        return "".join(out)

    @staticmethod
    def _config_search_paths(config_path: Optional[str]) -> list:
        """Ordered list of config.json locations to try (first match wins)."""
        if config_path:
            return [config_path]

        paths = []
        if getattr(sys, "frozen", False):
            # Packaged exe: prefer an editable config.json beside the executable,
            # then fall back to the read-only copy bundled inside the onefile.
            paths.append(os.path.join(os.path.dirname(sys.executable), "config.json"))
            meipass = getattr(sys, "_MEIPASS", None)
            if meipass:
                paths.append(os.path.join(meipass, "src", "configs", "config.json"))
        paths.append(os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            os.pardir, "configs", "config.json",
        ))
        return paths

    def _start_poll_worker(self):
        # Stop any existing worker first so we never overwrite a running QThread.
        # An orphaned, still-running QThread crashes the app ("QThread: Destroyed
        # while thread is still running") when it is later garbage-collected.
        self._stop_poll_worker()
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
        if not dialog.exec():
            return

        new_settings = dialog.get_settings()
        self.config.update(new_settings)
        self._apply_settings_to_runtime()
        saved_to = self._persist_settings(new_settings)

        # If ports changed, warn the user to reconnect
        persist_note = (f"Saved to {saved_to}." if saved_to
                        else "Could not write config.json — changes apply this session only.")
        QMessageBox.information(self, "Settings Updated",
                                "Settings have been updated.\n"
                                f"{persist_note}\n"
                                "If you changed device ports or addresses, please disconnect and reconnect.")

        self._refresh_device_dots()

    def _persist_settings(self, new_settings: dict) -> Optional[str]:
        """Write the changed settings back to config.json, preserving comments.

        When packaged as an executable the writable target is a config.json next
        to the .exe (the bundled copy is read-only), using the loaded file as the
        comment/format template. Returns the path written, or None on failure.
        """
        try:
            dest = self._config_search_paths(None)[0]
            save_config_to_file(new_settings, dest, template_path=self.config_path)
            return dest
        except Exception as e:
            print(f"Failed to save config.json: {e}")
            return None

    def _apply_settings_to_runtime(self):
        """Push the in-memory config into the controller, plot, and poll worker."""
        if self.controller:
            apply_settings(self.controller.config, self.config,
                           self.controller.logger, self.controller.pid)

        if hasattr(self, 'plot_widget'):
            self.plot_widget.set_max_points(self.config.get('max_plot_points', 500))

        # Poll interval change takes effect on the next sleep cycle
        if self.poll_worker:
            self.poll_worker.interval_ms = int(self.config.get('control_interval', 5000))

    def _refresh_device_dots(self):
        """Update device dot indicators to reflect enabled/disabled + connection state."""
        try:
            for key in self.device_labels:
                if not bool(self.config.get(f"{key}_enabled", True)):
                    self._set_device_dot(key, "Disabled")
                elif getattr(self.controller, key, None) and self.controller.is_connected():
                    self._set_device_dot(key, "Connected")
                else:
                    self._set_device_dot(key, "Disconnected")
        except Exception:
            pass

    def _set_controls_enabled(self, enabled: bool):
        """Enable/disable the device-control buttons together."""
        for btn in (self.btn_set_flow, self.btn_purge, self.btn_set_chiller,
                    self.btn_start_exp, self.btn_toggle_rh_control):
            btn.setEnabled(enabled)

    def _reset_rh_control_ui(self):
        """Return the RH-control widgets to their inactive/stopped state."""
        self.btn_toggle_rh_control.setText("Start RH Control")
        self.btn_toggle_rh_control.setStyleSheet("")
        self.lbl_rh_pid_status.setText("Inactive")
        self.lbl_rh_pid_status.setStyleSheet("color: gray")
        self.spin_rh_target.setEnabled(True)
        self.spin_rh_total_flow.setEnabled(True)

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

        layout.addWidget(self._build_device_status_group())
        layout.addWidget(self._build_manual_flow_group())
        layout.addWidget(self._build_rh_control_group())
        layout.addWidget(self._build_chiller_group())
        layout.addWidget(self._build_experiment_group())

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

    def _build_device_status_group(self) -> QGroupBox:
        # Devices — compact: colored-dot indicators + connect button on one row
        conn_group = QGroupBox("Devices")
        conn_vbox = QVBoxLayout()
        conn_vbox.setSpacing(4)

        # 2×2 grid of [● Name] indicators
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
            ("firesting",  "O₂"),
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
        return conn_group

    def _build_manual_flow_group(self) -> QGroupBox:
        # Manual Control
        manual_group = QGroupBox("Manual Control")
        manual_layout = QFormLayout()
        
        self.spin_dry = QDoubleSpinBox()
        self.spin_dry.setRange(0, 5.0)
        self.spin_dry.setDecimals(1)  # MFC flow resolution: 0.1 L/min (e.g. 0.1, 1.5)
        self.spin_dry.setSingleStep(0.1)
        self.spin_dry.setSuffix(" L/min")

        self.spin_wet = QDoubleSpinBox()
        self.spin_wet.setRange(0, 5.0)
        self.spin_wet.setDecimals(1)  # MFC flow resolution: 0.1 L/min (e.g. 0.1, 1.5)
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

        # Purge: one-touch toggle that overrides flows with 3 L/min wet, 0 dry.
        self.btn_purge = QPushButton("Purge")
        self.btn_purge.setCheckable(True)
        self.btn_purge.setEnabled(False)
        self.btn_purge.setMaximumWidth(70)
        self.btn_purge.setStyleSheet(_PURGE_STYLE_OFF)
        self.btn_purge.setToolTip(
            "On: force 3 L/min wet, 0 L/min dry.\n"
            "Off: restore the dry/wet setpoints above."
        )
        self.btn_purge.toggled.connect(self.toggle_purge)

        # Ramp checkbox and the compact purge toggle share one row.
        ramp_row = QHBoxLayout()
        ramp_row.setContentsMargins(0, 0, 0, 0)
        ramp_row.addWidget(self.chk_ramp_flow)
        ramp_row.addStretch()
        ramp_row.addWidget(self.btn_purge)

        # Flows are no longer plotted (they stay near-constant), so show the
        # live measured values (and setpoints) here instead. Updated each poll.
        self.lbl_flow_readout = QLabel("Dry — · Wet — L/min")
        self.lbl_flow_readout.setStyleSheet("font-size: 11px; color: #444444;")

        manual_layout.addRow("Dry Flow:", self.spin_dry)
        manual_layout.addRow("Wet Flow:", self.spin_wet)
        manual_layout.addRow(ramp_row)
        manual_layout.addRow(self.btn_set_flow)
        manual_layout.addRow("Measured:", self.lbl_flow_readout)
        manual_group.setLayout(manual_layout)
        return manual_group

    def _build_rh_control_group(self) -> QGroupBox:
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
        return rh_group

    def _build_chiller_group(self) -> QGroupBox:
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
        return chiller_group

    def _build_experiment_group(self) -> QGroupBox:
        # Experiment Control
        exp_group = QGroupBox("RH Ramp Experiment")
        exp_layout = QFormLayout()

        # Mode selector (always visible)
        self.combo_experiment_mode = QComboBox()
        self.combo_experiment_mode.addItems(["Flow", "RH"])
        saved_mode = self.config.get('experiment_mode', 'flow')
        self.combo_experiment_mode.setCurrentText("Flow" if saved_mode.lower() == 'flow' else "RH")

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

        # ── Assemble experiment panel ───────────────────────────────────────
        self.btn_start_exp = QPushButton("Start Experiment")
        self.btn_start_exp.clicked.connect(self.toggle_experiment)
        self.btn_start_exp.setEnabled(False)

        exp_layout.addRow("Mode:", self.combo_experiment_mode)
        exp_layout.addRow("Hold time:", self.spin_hold_time)
        exp_layout.addRow(self.flow_mode_widget)
        exp_layout.addRow(self.rh_mode_widget)
        exp_layout.addRow(self.btn_start_exp)

        self.combo_experiment_mode.currentTextChanged.connect(self._on_experiment_mode_changed)
        self._on_experiment_mode_changed(self.combo_experiment_mode.currentText())

        exp_group.setLayout(exp_layout)
        return exp_group

    def _create_right_panel(self):
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        self.plot_widget = RealTimePlotWidget()
        right_layout.addWidget(self.plot_widget)

        # Clear Graph button — wipes the plot without affecting devices or logging.
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_clear_graph = QPushButton("Clear Graph")
        self.btn_clear_graph.clicked.connect(self.clear_graph)
        btn_row.addWidget(self.btn_clear_graph)
        right_layout.addLayout(btn_row)

        self.main_layout.addWidget(right_panel)

    def clear_graph(self):
        self.plot_widget.clear()

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
                    self._set_controls_enabled(True)
                elif any_connected:
                    self.btn_connect.setText("Disconnect")
                    self.btn_connect.setStyleSheet("background-color: #ffe0aa;")
                    self._set_controls_enabled(True)
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
            # Clear any active RH control so a new session never silently resumes
            # control with a stale setpoint after the next Connect.
            if self.controller.rh_control_active:
                self.controller.set_rh_control_active(False)
            self._reset_rh_control_ui()
            self.controller.logger.close()
            self.controller.disconnect_devices()
            self.btn_connect.setText("Connect")
            self.btn_connect.setStyleSheet("")
            self._set_controls_enabled(False)
            for key in self.device_labels:
                status = "Disabled" if not self.config.get(f"{key}_enabled", True) else "Disconnected"
                self._set_device_dot(key, status)

    def set_manual_flow(self):
        self._apply_flow(self.spin_dry.value(), self.spin_wet.value())

    def toggle_purge(self, checked: bool):
        """Purge on: force 3 L/min wet, 0 dry. Off: restore the spinbox flows."""
        self.btn_purge.setText("Purging" if checked else "Purge")
        self.btn_purge.setStyleSheet(_PURGE_STYLE_ON if checked else _PURGE_STYLE_OFF)
        # Disable manual flow entry while purging so it can't fight the override.
        self.spin_dry.setEnabled(not checked)
        self.spin_wet.setEnabled(not checked)
        self.btn_set_flow.setEnabled(not checked)
        if checked:
            self._apply_flow(0.0, 3.0)
        else:
            self._apply_flow(self.spin_dry.value(), self.spin_wet.value())

    def _apply_flow(self, dry: float, wet: float):
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
        # `finished` is emitted from run()'s finally block (after `error`, if any),
        # so it always fires last — do all cleanup here exactly once. wait() ensures
        # run() has fully returned before we drop the only reference to the QThread.
        worker = self.flow_ramp_worker
        self.flow_ramp_worker = None
        if worker is not None:
            worker.wait()
        # Stay disabled while purge is active so it can't override the purge flows.
        self.btn_set_flow.setEnabled(not self.btn_purge.isChecked())
        if self.controller.is_connected():
            self._start_poll_worker()

    def _on_flow_ramp_error(self, msg: str):
        # Just report — thread cleanup and poll restart happen in _on_flow_ramp_finished.
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
            self._reset_rh_control_ui()

            # Re-enable inputs
            self.btn_set_flow.setEnabled(True)
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

    def toggle_experiment(self):
        if self.experiment_worker and self.experiment_worker.isRunning():
            # Signal the background thread to stop; cleanup happens in on_experiment_finished
            self.experiment_worker.stop()
            self.btn_start_exp.setText("Stopping…")
            self.btn_start_exp.setEnabled(False)
        else:
            # Start experiment — sync UI values into config
            mode = self.combo_experiment_mode.currentText().lower()  # "flow" or "rh"
            self.config['experiment_mode'] = mode
            self.config['experiment_hold_time'] = self.spin_hold_time.value()
            if mode == 'flow':
                self.config['experiment_flow_start'] = self.spin_flow_start.value()
                self.config['experiment_flow_end'] = self.spin_flow_end.value()
                self.config['experiment_flow_step'] = self.spin_flow_step.value()
            else:
                self.config['experiment_rh_lower'] = self.spin_rh_start.value()
                self.config['experiment_rh_upper'] = self.spin_rh_end.value()
                self.config['experiment_rh_step'] = self.spin_rh_step.value()
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
            # Block disconnecting mid-experiment — it would close the serial ports
            # out from under the running experiment thread. Stop the experiment first.
            self.btn_connect.setEnabled(False)

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
        self.btn_connect.setEnabled(True)

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
        self.btn_connect.setEnabled(True)
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
            self._refresh_live_dots()
            self.update_readings(data)
        except Exception:
            pass

    def _refresh_live_dots(self):
        """Reflect live per-device health (updated each poll) in the status dots,
        so a device that drops mid-run turns red and goes green again when it
        recovers."""
        try:
            health = self.controller.device_health
            for key in self.device_labels:
                if not bool(self.config.get(f"{key}_enabled", True)):
                    continue  # leave "Disabled" dots alone
                if getattr(self.controller, key, None) is None:
                    continue  # not present / failed at connect — keep its dot
                self._set_device_dot(
                    key, "Connected" if health.get(key, False) else "Disconnected"
                )
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

            def _fmt(v):
                return f"{v:.2f}" if v is not None else "—"

            self.lbl_flow_readout.setText(
                f"Dry {_fmt(data.get('dry_flow'))} (set {_fmt(data.get('dry_flow_setpoint'))}) · "
                f"Wet {_fmt(data.get('wet_flow'))} (set {_fmt(data.get('wet_flow_setpoint'))}) L/min"
            )

        except Exception:
            # Don't spam errors
            pass

    def closeEvent(self, event):
        if self.controller:
            self.controller.disconnect_devices()
        event.accept()
