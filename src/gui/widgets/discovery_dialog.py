"""Instrument detection — the "Detect devices…" dialog on the Devices tab.

Picks ports, runs a scan on a background thread, and hands back the
instruments that answered so the device list editor can fill in their
connection fields. Everything it knows about how to recognise an instrument
comes from :mod:`src.devices.discovery`.
"""

from typing import Dict, List, Optional, Sequence

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QDialog, QDialogButtonBox, QGroupBox,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QProgressBar,
    QPushButton, QRadioButton, QVBoxLayout,
)

from src.devices import discovery
from src.gui.workers import DiscoveryWorker


def _format_duration(seconds: float) -> str:
    if seconds < 90:
        return f"~{int(seconds)} s"
    return f"~{seconds / 60:.0f} min"


class DiscoveryDialog(QDialog):
    """Scan serial ports for instruments and return the ones to add."""

    def __init__(self, specs: Sequence[Dict], busy_ports: Sequence[str] = (),
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Detect devices")
        self.resize(520, 560)

        self.specs = list(specs or [])
        self.busy_ports = set(busy_ports or ())
        self.worker: Optional[DiscoveryWorker] = None
        self.results: List[discovery.Found] = []

        layout = QVBoxLayout(self)

        hint = QLabel(
            "Scanning asks every selected port what is on it, using the same "
            "read-only handshake each driver already performs when it "
            "connects. Nothing is written to any instrument."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #555555; font-size: 11px;")
        layout.addWidget(hint)

        # ── Ports ────────────────────────────────────────────────────────────
        ports_box = QGroupBox("Ports to scan")
        ports_layout = QVBoxLayout(ports_box)
        self.list_ports = QListWidget()
        self.list_ports.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.list_ports.setMaximumHeight(140)
        ports_layout.addWidget(self.list_ports)

        refresh_row = QHBoxLayout()
        self.lbl_ports = QLabel()
        self.lbl_ports.setStyleSheet("color: #555555; font-size: 11px;")
        btn_refresh = QPushButton("Refresh ports")
        btn_refresh.clicked.connect(self._reload_ports)
        refresh_row.addWidget(self.lbl_ports, 1)
        refresh_row.addWidget(btn_refresh)
        ports_layout.addLayout(refresh_row)
        layout.addWidget(ports_box)

        # ── Depth ────────────────────────────────────────────────────────────
        depth_box = QGroupBox("How hard to look")
        depth_layout = QVBoxLayout(depth_box)
        self.radio_quick = QRadioButton("Quick — default and already-configured addresses")
        self.radio_quick.setChecked(True)
        self.radio_deep = QRadioButton("Deep — also sweep every Modbus address (1–247)")
        self.radio_deep.setToolTip(
            "Use this when an MFC or probe has been renumbered away from its "
            "factory address. Much slower, because every silent address costs "
            "a timeout."
        )
        depth_layout.addWidget(self.radio_quick)
        depth_layout.addWidget(self.radio_deep)
        self.lbl_estimate = QLabel()
        self.lbl_estimate.setStyleSheet("color: #555555; font-size: 11px;")
        self.lbl_estimate.setWordWrap(True)
        depth_layout.addWidget(self.lbl_estimate)
        layout.addWidget(depth_box)

        for widget in (self.radio_quick, self.radio_deep):
            widget.toggled.connect(self._update_estimate)

        # ── Run ──────────────────────────────────────────────────────────────
        run_row = QHBoxLayout()
        self.btn_scan = QPushButton("Scan")
        self.btn_scan.clicked.connect(self._toggle_scan)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        run_row.addWidget(self.btn_scan)
        run_row.addWidget(self.progress, 1)
        layout.addLayout(run_row)

        self.lbl_status = QLabel(" ")
        self.lbl_status.setStyleSheet("color: #555555; font-size: 11px;")
        layout.addWidget(self.lbl_status)

        # ── Results ──────────────────────────────────────────────────────────
        results_box = QGroupBox("Found")
        results_layout = QVBoxLayout(results_box)
        self.list_results = QListWidget()
        self.list_results.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        results_layout.addWidget(self.list_results)
        layout.addWidget(results_box, 1)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Add selected")
        self.buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Close")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.list_ports.itemChanged.connect(self._update_estimate)
        self._reload_ports()

    # ── Ports ────────────────────────────────────────────────────────────────

    def _reload_ports(self):
        # Populating flips check states; the estimate is refreshed once at the
        # end instead of once per row.
        self.list_ports.blockSignals(True)
        self.list_ports.clear()
        ports = discovery.list_serial_ports()
        for port in ports:
            item = QListWidgetItem(port.label)
            in_use = port.device in self.busy_ports
            if in_use:
                item.setText(f"{port.label}  — in use, disconnect first")
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                item.setCheckState(Qt.CheckState.Unchecked)
            else:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, port.device)
            self.list_ports.addItem(item)

        self.list_ports.blockSignals(False)
        if not ports:
            self.lbl_ports.setText("No serial ports detected.")
        else:
            self.lbl_ports.setText(f"{len(ports)} port(s) detected.")
        self._update_estimate()

    def _selected_ports(self) -> List[str]:
        out = []
        for row in range(self.list_ports.count()):
            item = self.list_ports.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                out.append(item.data(Qt.ItemDataRole.UserRole))
        return out

    def _update_estimate(self, *_):
        ports = self._selected_ports()
        if not ports:
            self.lbl_estimate.setText("Select at least one port.")
            self.btn_scan.setEnabled(False)
            return
        self.btn_scan.setEnabled(True)
        scan_plan = discovery.plan(ports, deep=self.radio_deep.isChecked(),
                                   specs=self.specs)
        self.lbl_estimate.setText(
            f"Worst case {_format_duration(scan_plan.estimated_seconds)} for "
            f"{len(ports)} port(s) — usually much less, because a port stops "
            "being probed as soon as something answers on it."
        )

    # ── Scanning ─────────────────────────────────────────────────────────────

    def _toggle_scan(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.btn_scan.setEnabled(False)
            self.lbl_status.setText("Cancelling…")
            return
        self._start_scan()

    def _start_scan(self):
        ports = self._selected_ports()
        if not ports:
            return

        self.results = []
        self.list_results.clear()
        scan_plan = discovery.plan(ports, deep=self.radio_deep.isChecked(),
                                   specs=self.specs)

        self.progress.setRange(0, max(1, scan_plan.total_units))
        self.progress.setValue(0)
        self.btn_scan.setText("Stop")
        self._set_inputs_enabled(False)

        self.worker = DiscoveryWorker(scan_plan, skip_ports=sorted(self.busy_ports))
        self.worker.progress.connect(self._on_progress)
        self.worker.found.connect(self._on_found)
        self.worker.scan_finished.connect(self._on_scan_finished)
        self.worker.start()

    def _set_inputs_enabled(self, enabled: bool):
        self.list_ports.setEnabled(enabled)
        self.radio_quick.setEnabled(enabled)
        self.radio_deep.setEnabled(enabled)
        self.buttons.setEnabled(enabled)

    def _on_progress(self, done: int, message: str):
        self.progress.setValue(done)
        self.lbl_status.setText(message)

    def _on_found(self, found: discovery.Found):
        self.results.append(found)
        existing = next((s for s in self.specs if found.matches(s)), None)

        item = QListWidgetItem(found.label)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        if existing is not None:
            # Already in the list — offer it, but unticked, so a re-scan does
            # not quietly add a duplicate card for a device the user has
            # already named and given a role.
            item.setText(f"{found.label}  — already configured as "
                         f"\"{existing.get('tag', existing.get('id'))}\"")
            item.setCheckState(Qt.CheckState.Unchecked)
        else:
            item.setCheckState(Qt.CheckState.Checked)
        item.setData(Qt.ItemDataRole.UserRole, found)
        self.list_results.addItem(item)

    def _on_scan_finished(self, results: list):
        self.btn_scan.setText("Scan")
        self.btn_scan.setEnabled(True)
        self._set_inputs_enabled(True)
        self.progress.setValue(self.progress.maximum())
        new = sum(1 for f in results if not any(f.matches(s) for s in self.specs))
        if not results:
            self.lbl_status.setText("Scan finished — nothing answered.")
        else:
            self.lbl_status.setText(
                f"Scan finished — {len(results)} instrument(s) found, {new} new."
            )

    # ── Result ───────────────────────────────────────────────────────────────

    def selected_devices(self) -> List[discovery.Found]:
        out = []
        for row in range(self.list_results.count()):
            item = self.list_results.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                out.append(item.data(Qt.ItemDataRole.UserRole))
        return out

    def _shutdown_worker(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait()
        self.worker = None

    # A scan holds serial ports open, so it must never outlive the dialog —
    # otherwise the next connect finds them busy.
    def accept(self):
        self._shutdown_worker()
        super().accept()

    def reject(self):
        self._shutdown_worker()
        super().reject()

    def closeEvent(self, event):
        self._shutdown_worker()
        super().closeEvent(event)
