import os
import json
from typing import Optional

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QGroupBox, QDoubleSpinBox,
    QFormLayout, QMessageBox, QComboBox, QCheckBox, QScrollArea, QGridLayout
)
from PyQt6.QtCore import Qt

from src.devices import registry as reg
from src.devices.controller import Controller
from src.gui.widgets.plot_widget import RealTimePlotWidget
from src.gui.workers import ExperimentWorker, PollWorker, FlowRampWorker
from src.gui.settings_dialog import SettingsDialog
from src.utility.update_settings import (
    apply_settings, default_config_path, save_config_to_file,
)

# Compact styling for the purge toggle (sits inline with the ramp checkbox).
_PURGE_STYLE_OFF = "font-size: 11px; padding: 2px 6px;"
_PURGE_STYLE_ON = _PURGE_STYLE_OFF + " background-color: #cc7a00; color: white;"

# The left panel is a fixed-width column. Device tags are free text, so any
# widget that shows one must elide rather than widen — otherwise a tag like
# "Vaisala before flow cell" drags the whole panel past the viewport and the
# content gets clipped.
_LEFT_PANEL_WIDTH = 360
_DOT_TAG_WIDTH = 130    # tag beside a status dot (two per row)
_ROW_TAG_WIDTH = 120    # tag used as a form-row label

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

        The path is resolved relative to this module, so the app runs from any
        working directory.
        """
        path = str(config_path or default_config_path())
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"Config file not found: {path}. "
                "Expected a config.json in src/configs/."
            )
        self.config_path = path
        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)
        # A hand-edited file may leave an implied role unassigned.
        reg.assign_default_roles(config.get("devices", []))
        return config

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
        previous_fields = list(self.controller.log_fields)
        self.config.update(new_settings)
        self._apply_settings_to_runtime()
        self._rotate_log_if_schema_changed(previous_fields)
        # The device list may have changed: rebuild the device-driven left panel
        # and the plot's series before anything tries to touch the old widgets.
        self._rebuild_left_panel()
        saved_to = self._persist_settings()

        # If ports changed, warn the user to reconnect
        persist_note = (f"Saved to {saved_to}." if saved_to
                        else "Could not write config.json — changes apply this session only.")
        QMessageBox.information(self, "Settings Updated",
                                "Settings have been updated.\n"
                                f"{persist_note}\n"
                                "If you changed device ports or addresses, please disconnect and reconnect.")

        self._refresh_device_dots()

    def _rotate_log_if_schema_changed(self, previous_fields: list):
        """Start a fresh CSV when the column set changed under an open log.

        Column names come from the device tags, so adding a device or renaming
        one changes the schema. The open file's header is already written, and
        the writer ignores unknown keys — without a rotation the new columns
        would be silently dropped for the rest of the session.
        """
        if not self.controller.logger.is_logging():
            return
        if self.controller.log_fields == previous_fields:
            return
        try:
            self.controller.logger.close()
            self.controller.logger.start_new_log(self.controller.log_fields)
            print("Device list changed — started a new log file for the new columns.")
        except Exception as e:
            print(f"Failed to rotate log after a device change: {e}")

    def _persist_settings(self) -> Optional[str]:
        """Write the in-memory config back to config.json.

        Callers update ``self.config`` first; the whole thing is re-serialised.
        Returns the path written, or None on failure.
        """
        try:
            dest = self.config_path or str(default_config_path())
            save_config_to_file(self.config, dest)
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
            # Reconfiguring drops the buffered traces, so only do it when the
            # series actually changed — not for an unrelated settings edit.
            manifest = self.controller.build_series_manifest()
            if manifest != self.plot_widget.manifest:
                self.plot_widget.configure(manifest)

        # Poll interval change takes effect on the next sleep cycle
        if self.poll_worker:
            self.poll_worker.interval_ms = int(self.config.get('control_interval', 5000))

    def _spec_by_id(self, dev_id: str) -> dict:
        for spec in self.config.get("devices", []) or []:
            if spec.get("id") == dev_id:
                return spec
        return {}

    def _refresh_device_dots(self):
        """Update device dot indicators to reflect enabled/disabled + connection state."""
        try:
            for dev_id in self.device_labels:
                if not bool(self._spec_by_id(dev_id).get("enabled", True)):
                    self._set_device_dot(dev_id, "Disabled")
                elif dev_id in self.controller.devices and self.controller.is_connected():
                    self._set_device_dot(dev_id, "Connected")
                else:
                    self._set_device_dot(dev_id, "Disconnected")
        except Exception:
            pass

    def _set_controls_enabled(self, enabled: bool):
        """Enable/disable the device-control buttons together.

        The button set depends on which devices are configured, so it is
        collected while the panel is built rather than named here.
        """
        for btn in getattr(self, "_control_buttons", []):
            btn.setEnabled(enabled)

    def _reset_rh_control_ui(self):
        """Return the RH-control widgets to their inactive/stopped state."""
        if self.btn_toggle_rh_control is None:
            return
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

    # ── Left panel ───────────────────────────────────────────────────────────
    #
    # The panel is generated from the configured device list rather than being
    # a fixed set of groups: one status dot and one control row per device, and
    # the role-driven groups (RH control, experiment) appear only when the roles
    # they need are assigned. `_rebuild_left_panel` replaces the whole widget
    # tree, so no per-device widget reference can outlive its device.

    @staticmethod
    def _elided_label(text: str, max_width: int, style: str = "",
                      tooltip: Optional[str] = None) -> QLabel:
        """Label that truncates instead of stretching the fixed-width panel.

        The full text is always available as a tooltip, so nothing is lost.
        """
        lbl = QLabel()
        if style:
            lbl.setStyleSheet(style)
        elided = lbl.fontMetrics().elidedText(
            text, Qt.TextElideMode.ElideRight, max_width
        )
        lbl.setText(elided)
        lbl.setMaximumWidth(max_width)
        if tooltip or elided != text:
            lbl.setToolTip(tooltip or text)
        return lbl

    @staticmethod
    def _compact_form() -> QFormLayout:
        """Form layout that wraps a long row rather than forcing the panel wider."""
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        return form

    def _enabled_specs(self) -> list:
        return reg.enabled_specs(self.config.get("devices", []))

    def _specs_with_cap(self, cap: str) -> list:
        return [s for s in self._enabled_specs() if cap in reg.get_type(s).caps]

    def _create_left_panel(self):
        self.left_scroll = QScrollArea()
        self.left_scroll.setWidgetResizable(True)
        self.left_scroll.setFixedWidth(_LEFT_PANEL_WIDTH)
        self.left_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.main_layout.addWidget(self.left_scroll)
        self._rebuild_left_panel()

    def _rebuild_left_panel(self):
        """(Re)build the panel for the current device set.

        Handing a fresh widget to the scroll area lets Qt delete the previous
        tree, so stale per-device widgets can never be referenced afterwards.
        """
        was_connected = self.btn_connect.text() == "Disconnect" if hasattr(
            self, "btn_connect") else False
        save_csv = self.chk_save_csv.isChecked() if hasattr(self, "chk_save_csv") else True

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 4, 4, 4)

        self._control_buttons = []
        self.flow_spins = {}
        self.chiller_spins = {}

        layout.addWidget(self._build_device_status_group())
        flow_group = self._build_manual_flow_group()
        if flow_group:
            layout.addWidget(flow_group)
        layout.addWidget(self._build_rh_control_group())
        chiller_group = self._build_chiller_group()
        if chiller_group:
            layout.addWidget(chiller_group)
        layout.addWidget(self._build_experiment_group())

        self.btn_settings = QPushButton("Settings")
        self.btn_settings.clicked.connect(self.open_settings)
        layout.addWidget(self.btn_settings)

        layout.addStretch()

        self.left_scroll.setWidget(panel)

        self.chk_save_csv.setChecked(save_csv)
        if was_connected:
            self.btn_connect.setText("Disconnect")
            self.btn_connect.setStyleSheet("background-color: #ccffcc;")
            self._set_controls_enabled(True)
        # A rebuild during a live RH-control run must not leave the new buttons
        # claiming the loop is stopped while the controller is still driving it.
        if self.controller.rh_control_active and self.btn_toggle_rh_control:
            self._show_rh_control_running()
        self._refresh_device_dots()

    def _build_device_status_group(self) -> QGroupBox:
        # Devices — compact: colored-dot indicators + connect button on one row
        conn_group = QGroupBox("Devices")
        conn_vbox = QVBoxLayout()
        conn_vbox.setSpacing(4)

        # Grid of [● Tag] indicators, one per configured device (3 per row).
        dot_grid = QWidget()
        dot_layout = QGridLayout(dot_grid)
        dot_layout.setContentsMargins(0, 0, 0, 0)
        dot_layout.setSpacing(2)

        self.device_labels = {}
        specs = self.config.get("devices", []) or []
        for idx, spec in enumerate(specs):
            dtype = reg.get_type(spec)
            if dtype is None:
                continue
            dev_id = spec["id"]
            dot = QLabel("●")
            dot.setFixedWidth(16)
            enabled = bool(spec.get("enabled", True))
            dot.setStyleSheet(
                f"color: {'#dd2222' if enabled else '#888888'}; font-size: 14px;"
            )
            dot.setToolTip("Disconnected" if enabled else "Disabled")
            self.device_labels[dev_id] = dot

            tag = spec.get("tag", dev_id)
            name_lbl = self._elided_label(
                tag, _DOT_TAG_WIDTH, "font-size: 11px;",
                tooltip=(f"{tag}\n{dtype.label}\nPort: {spec.get('port', '—')}\n"
                         f"Role: {reg.ROLE_LABELS.get(spec.get('role', reg.ROLE_NONE))}"),
            )

            cell = QWidget()
            cell_h = QHBoxLayout(cell)
            cell_h.setContentsMargins(0, 0, 0, 0)
            cell_h.setSpacing(3)
            cell_h.addWidget(dot)
            cell_h.addWidget(name_lbl)
            cell_h.addStretch()

            row, col = divmod(idx, 2)
            dot_layout.addWidget(cell, row, col)

        if not self.device_labels:
            hint = QLabel("No devices configured — add them under Settings.")
            hint.setWordWrap(True)
            hint.setStyleSheet("color: #888888; font-size: 11px;")
            conn_vbox.addWidget(hint)
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

    def _build_manual_flow_group(self) -> Optional[QGroupBox]:
        """One flow row per configured MFC. Hidden when the rig has none."""
        mfc_specs = self._specs_with_cap("flow_setpoint")
        if not mfc_specs:
            return None

        manual_group = QGroupBox("Manual Control")
        manual_layout = self._compact_form()

        for spec in mfc_specs:
            spin = QDoubleSpinBox()
            spin.setRange(0, 5.0)
            spin.setDecimals(1)  # MFC flow resolution: 0.1 L/min (e.g. 0.1, 1.5)
            spin.setSingleStep(0.1)
            spin.setSuffix(" L/min")
            self.flow_spins[spec["id"]] = spin
            manual_layout.addRow(
                self._elided_label(spec.get("tag", spec["id"]), _ROW_TAG_WIDTH), spin
            )

        self.chk_ramp_flow = QCheckBox("Stepwise ramp")
        self.chk_ramp_flow.setChecked(True)
        self.chk_ramp_flow.setToolTip(
            "Checked: ramp flows gradually in 0.05 L/min steps (takes ~1 s/step).\n"
            "Unchecked: jump directly to setpoint."
        )

        self.btn_set_flow = QPushButton("Set Flow Rates")
        self.btn_set_flow.clicked.connect(self.set_manual_flow)
        self.btn_set_flow.setEnabled(False)
        self._control_buttons.append(self.btn_set_flow)

        ramp_row = QHBoxLayout()
        ramp_row.setContentsMargins(0, 0, 0, 0)
        ramp_row.addWidget(self.chk_ramp_flow)
        ramp_row.addStretch()

        # Purge: one-touch toggle that overrides the wet/dry pair. Only offered
        # when both roles exist — it means nothing without them.
        self.btn_purge = None
        if (reg.role_holder(self._enabled_specs(), reg.ROLE_WET_FLOW)
                and reg.role_holder(self._enabled_specs(), reg.ROLE_DRY_FLOW)):
            self.btn_purge = QPushButton("Purge")
            self.btn_purge.setCheckable(True)
            self.btn_purge.setEnabled(False)
            self.btn_purge.setMaximumWidth(70)
            self.btn_purge.setStyleSheet(_PURGE_STYLE_OFF)
            self.btn_purge.setToolTip(
                "On: force 3 L/min wet, 0 L/min dry.\n"
                "Off: restore the setpoints above."
            )
            self.btn_purge.toggled.connect(self.toggle_purge)
            self._control_buttons.append(self.btn_purge)
            ramp_row.addWidget(self.btn_purge)

        # Flows are not plotted at full detail here, so show the live measured
        # values (and setpoints) as text. Updated each poll.
        self.lbl_flow_readout = QLabel("—")
        self.lbl_flow_readout.setWordWrap(True)
        self.lbl_flow_readout.setStyleSheet("font-size: 11px; color: #444444;")

        manual_layout.addRow(ramp_row)
        manual_layout.addRow(self.btn_set_flow)
        manual_layout.addRow("Measured:", self.lbl_flow_readout)
        manual_group.setLayout(manual_layout)
        return manual_group

    def _build_rh_control_group(self) -> QGroupBox:
        """RH Control — needs a wet MFC, a dry MFC and an RH source."""
        rh_group = QGroupBox("RH Control (PID)")
        rh_layout = self._compact_form()

        if not self.controller.has_rh_control_roles():
            self.btn_toggle_rh_control = None
            self.lbl_rh_pid_status = QLabel("Unavailable")
            hint = QLabel(
                "Assign the <b>wet flow</b>, <b>dry flow</b> and <b>RH source</b> "
                "roles under Settings → Devices to enable RH control."
            )
            hint.setWordWrap(True)
            hint.setStyleSheet("color: #888888; font-size: 11px;")
            rh_layout.addRow(hint)
            rh_group.setLayout(rh_layout)
            return rh_group

        self.spin_rh_target = QDoubleSpinBox()
        self.spin_rh_target.setRange(0, 100)
        self.spin_rh_target.setValue(50.0)
        self.spin_rh_target.setSuffix(" %")

        self.spin_rh_total_flow = QDoubleSpinBox()
        self.spin_rh_total_flow.setRange(0, 5.0)
        self.spin_rh_total_flow.setSingleStep(0.1)
        self.spin_rh_total_flow.setValue(self.config.get("max_flow", 2.0))
        self.spin_rh_total_flow.setSuffix(" L/min")

        self.btn_toggle_rh_control = QPushButton("Start RH Control")
        self.btn_toggle_rh_control.clicked.connect(self.toggle_rh_control)
        self.btn_toggle_rh_control.setEnabled(False)
        self._control_buttons.append(self.btn_toggle_rh_control)

        self.lbl_rh_pid_status = QLabel("Inactive")
        self.lbl_rh_pid_status.setStyleSheet("color: gray")

        rh_layout.addRow("Target:", self.spin_rh_target)
        rh_layout.addRow("Total:", self.spin_rh_total_flow)
        rh_layout.addRow(self.btn_toggle_rh_control)
        rh_layout.addRow("Status:", self.lbl_rh_pid_status)
        rh_group.setLayout(rh_layout)
        return rh_group

    def _build_chiller_group(self) -> Optional[QGroupBox]:
        """One setpoint row per device that accepts a temperature setpoint."""
        chiller_specs = self._specs_with_cap("temp_setpoint")
        if not chiller_specs:
            return None

        chiller_group = QGroupBox("Temperature Control")
        chiller_layout = self._compact_form()

        for spec in chiller_specs:
            dev_id = spec["id"]
            spin = QDoubleSpinBox()
            spin.setRange(-20, 100)
            spin.setSingleStep(0.1)
            spin.setSuffix(" °C")
            self.chiller_spins[dev_id] = spin

            btn = QPushButton("Set")
            btn.setMaximumWidth(60)
            btn.setEnabled(False)
            btn.clicked.connect(lambda _, d=dev_id: self.set_chiller_temp(d))
            self._control_buttons.append(btn)

            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(spin)
            row.addWidget(btn)
            chiller_layout.addRow(
                self._elided_label(spec.get("tag", dev_id), _ROW_TAG_WIDTH), row
            )

        self.lbl_chiller_monitor = QLabel("Monitor: Inactive")
        self.lbl_chiller_monitor.setStyleSheet("color: gray")
        chiller_layout.addRow(self.lbl_chiller_monitor)

        chiller_group.setLayout(chiller_layout)
        return chiller_group

    def _build_experiment_group(self) -> QGroupBox:
        # Experiment Control
        exp_group = QGroupBox("RH Ramp Experiment")
        exp_layout = self._compact_form()

        # Mode selector. RH mode needs the closed-loop roles; without them only
        # the open-loop flow ramp is offered.
        self.combo_experiment_mode = QComboBox()
        self.combo_experiment_mode.addItem("Flow")
        if self.controller.has_rh_control_roles():
            self.combo_experiment_mode.addItem("RH")
        else:
            self.combo_experiment_mode.setToolTip(
                "RH mode needs the wet flow, dry flow and RH source roles "
                "assigned under Settings → Devices."
            )
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
        flow_form = self._compact_form()
        self.flow_mode_widget.setLayout(flow_form)
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

        flow_form.addRow("Start:", self.spin_flow_start)
        flow_form.addRow("End:", self.spin_flow_end)
        flow_form.addRow("Step:", self.spin_flow_step)

        # ── RH mode widget group ────────────────────────────────────────────
        self.rh_mode_widget = QWidget()
        rh_form = self._compact_form()
        self.rh_mode_widget.setLayout(rh_form)
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

        rh_form.addRow("Start:", self.spin_rh_start)
        rh_form.addRow("End:", self.spin_rh_end)
        rh_form.addRow("Step:", self.spin_rh_step)

        # ── Assemble experiment panel ───────────────────────────────────────
        self.btn_start_exp = QPushButton("Start Experiment")
        self.btn_start_exp.clicked.connect(self.toggle_experiment)
        self.btn_start_exp.setEnabled(False)
        self._control_buttons.append(self.btn_start_exp)

        exp_layout.addRow("Mode:", self.combo_experiment_mode)
        exp_layout.addRow("Hold:", self.spin_hold_time)
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
                for dev_id in self.device_labels:
                    if dev_id in results:
                        if results[dev_id]:
                            self._set_device_dot(dev_id, "Connected")
                            any_connected = True
                        else:
                            self._set_device_dot(dev_id, "Failed")
                            any_failed = True
                    elif not self._spec_by_id(dev_id).get("enabled", True):
                        self._set_device_dot(dev_id, "Disabled")
                    else:
                        self._set_device_dot(dev_id, "Not configured")

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
                    # Series depend on which devices actually came up.
                    self.plot_widget.configure(self.controller.build_series_manifest())
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
            for dev_id in self.device_labels:
                enabled = self._spec_by_id(dev_id).get("enabled", True)
                self._set_device_dot(dev_id, "Disconnected" if enabled else "Disabled")

    def _flow_kwargs_from_spins(self) -> dict:
        """Split the per-MFC spinboxes into role kwargs + extra device ids."""
        specs = self._enabled_specs()
        by_role = {
            role: (reg.role_holder(specs, role) or {}).get("id")
            for role in (reg.ROLE_DRY_FLOW, reg.ROLE_WET_FLOW)
        }
        kwargs = {"dry_flow": None, "wet_flow": None, "extra": {}}
        for dev_id, spin in self.flow_spins.items():
            if dev_id == by_role[reg.ROLE_DRY_FLOW]:
                kwargs["dry_flow"] = spin.value()
            elif dev_id == by_role[reg.ROLE_WET_FLOW]:
                kwargs["wet_flow"] = spin.value()
            else:
                kwargs["extra"][dev_id] = spin.value()
        return kwargs

    def set_manual_flow(self):
        self._apply_flow(**self._flow_kwargs_from_spins())

    def toggle_purge(self, checked: bool):
        """Purge on: force 3 L/min wet, 0 dry. Off: restore the spinbox flows.

        Only the wet/dry pair is overridden — auxiliary MFCs keep their flows.
        """
        self.btn_purge.setText("Purging" if checked else "Purge")
        self.btn_purge.setStyleSheet(_PURGE_STYLE_ON if checked else _PURGE_STYLE_OFF)
        # Disable manual flow entry while purging so it can't fight the override.
        for spin in self.flow_spins.values():
            spin.setEnabled(not checked)
        self.btn_set_flow.setEnabled(not checked)
        if checked:
            self._apply_flow(dry_flow=0.0, wet_flow=3.0)
        else:
            self._apply_flow(**self._flow_kwargs_from_spins())

    def _apply_flow(self, dry_flow=None, wet_flow=None, extra=None):
        self._stop_poll_worker()  # avoid concurrent serial access
        if self.chk_ramp_flow.isChecked():
            # Gradual stepwise ramp via background worker
            self.btn_set_flow.setEnabled(False)
            self.flow_ramp_worker = FlowRampWorker(self.controller, dry_flow, wet_flow, extra)
            self.flow_ramp_worker.finished.connect(self._on_flow_ramp_finished)
            self.flow_ramp_worker.error.connect(self._on_flow_ramp_error)
            self.flow_ramp_worker.start()
        else:
            # Instant jump — set directly, no ramp
            try:
                self.controller.set_flow_rates(
                    dry_flow=dry_flow, wet_flow=wet_flow, extra=extra, ramp_flow=False
                )
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
        purging = self.btn_purge is not None and self.btn_purge.isChecked()
        self.btn_set_flow.setEnabled(not purging)
        if self.controller.is_connected():
            self._start_poll_worker()

    def _on_flow_ramp_error(self, msg: str):
        # Just report — thread cleanup and poll restart happen in _on_flow_ramp_finished.
        QMessageBox.warning(self, "Error", f"Failed to set flow: {msg}")

    def set_chiller_temp(self, dev_id: str):
        inst = self.controller.devices.get(dev_id)
        if inst is None:
            QMessageBox.warning(self, "Error", "That device is not connected.")
            return
        temp = self.chiller_spins[dev_id].value()
        self._stop_poll_worker()
        try:
            inst.driver.set_temperature(temp)
            inst.driver.start_control()
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
            self._show_rh_control_running()

    def _show_rh_control_running(self):
        """Put the RH-control widgets into their active state."""
        self.btn_toggle_rh_control.setText("Stop RH Control")
        # Light red to indicate active/stop
        self.btn_toggle_rh_control.setStyleSheet("background-color: #ffcccc")

        # Disable inputs to prevent conflict with the loop.
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
            curr_rh = self.controller.current_rh(data)
            if self.btn_toggle_rh_control is None:
                pass  # RH control unavailable — its roles aren't assigned
            elif self.controller.rh_control_active:
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
            for dev_id in self.device_labels:
                if not bool(self._spec_by_id(dev_id).get("enabled", True)):
                    continue  # leave "Disabled" dots alone
                if dev_id not in self.controller.devices:
                    continue  # not present / failed at connect — keep its dot
                self._set_device_dot(
                    dev_id, "Connected" if health.get(dev_id, False) else "Disconnected"
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

            if self.flow_spins:
                parts = []
                for dev_id in self.flow_spins:
                    tag = self._spec_by_id(dev_id).get("tag", dev_id)
                    prefix = self.controller.column_prefix(dev_id)
                    parts.append(
                        f"{tag} {_fmt(data.get(f'{prefix}_flow'))} "
                        f"(set {_fmt(data.get(f'{prefix}_setpoint'))})"
                    )
                self.lbl_flow_readout.setText(" · ".join(parts) + " L/min")

        except Exception:
            # Don't spam errors
            pass

    def closeEvent(self, event):
        if self.controller:
            self.controller.disconnect_devices()
        event.accept()
