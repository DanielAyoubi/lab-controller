from typing import Dict, Optional
from collections import deque
from datetime import datetime
import numpy as np
import pyqtgraph as pg

from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtCore import Qt


# Match Matplotlib's single-letter colours so the appearance is preserved.
_COLORS = {
    "b": (0, 0, 255),
    "r": (255, 0, 0),
    "g": (0, 128, 0),
    "c": (0, 191, 191),
}


# Names of the per-series data deques. Keeping the list in one place means
# __init__, set_max_points and clear can't drift out of sync.
# Flows are not plotted (they stay near-constant; shown as a live readout in
# the main window and always logged to CSV), and the hygrometer-temperature
# based series are omitted from the display for the same reason.
_SERIES = (
    "timestamps", "dewpoint_temp", "chiller_temp", "chiller_setpoint",
    "rh_chiller", "rh_chiller_calibrated", "oxygen",
)


class RealTimePlotWidget(QWidget):
    def __init__(self, max_points: int = 500):
        super().__init__()
        self.max_points = max_points

        # Data storage
        for name in _SERIES:
            setattr(self, name, deque(maxlen=max_points))

        # Layout
        pg.setConfigOptions(antialias=True, background="w", foreground="k")
        layout = QVBoxLayout()
        self.glw = pg.GraphicsLayoutWidget()
        self.glw.setBackground("w")
        layout.addWidget(self.glw)
        self.setLayout(layout)

        self._lines = {}
        self._setup_plots()

    def set_max_points(self, max_points: int):
        self.max_points = max_points
        # Re-create deques with new maxlen, preserving existing data
        for name in _SERIES:
            setattr(self, name, deque(getattr(self, name), maxlen=max_points))

    def clear(self):
        """Drop all buffered data and blank every line on the plot."""
        for name in _SERIES:
            getattr(self, name).clear()
        for line in self._lines.values():
            line.setData([], [])

    def _solid_line(self, plot, key, color, label):
        """Solid line with a dot marker at every point (Matplotlib '<c>.-')."""
        rgb = _COLORS[color]
        self._lines[key] = plot.plot(
            [],
            [],
            pen=pg.mkPen(rgb, width=1),
            symbol="o",
            symbolSize=4,
            symbolBrush=rgb,
            symbolPen=None,
            name=label,
        )

    def _dashed_line(self, plot, key, color, label):
        """Semi-transparent dashed line, no markers (Matplotlib '<c>--' alpha=0.5)."""
        rgb = _COLORS[color]
        pen = pg.mkPen((*rgb, 128), width=1, style=Qt.PenStyle.DashLine)
        self._lines[key] = plot.plot([], [], pen=pen, name=label)

    def _style_plot(self, plot, title, y_label, x_label=None):
        plot.setTitle(f"<b>{title}</b>", size="10pt")
        plot.setLabel("left", y_label)
        if x_label:
            plot.setLabel("bottom", x_label)
        plot.showGrid(x=True, y=True, alpha=0.3)
        plot.addLegend(offset=(10, 10))

    def _setup_plots(self):
        axis1 = pg.DateAxisItem(orientation="bottom")
        axis2 = pg.DateAxisItem(orientation="bottom")

        self.p1 = self.glw.addPlot(row=0, col=0, axisItems={"bottom": axis1})
        self.p2 = self.glw.addPlot(row=1, col=0, axisItems={"bottom": axis2})

        # Shared x-axis (replaces Matplotlib sharex=True)
        self.p2.setXLink(self.p1)

        # Show raw values on the y-axes. pyqtgraph defaults to auto SI-prefix
        # scaling, which for small values tacks a multiplier / unit prefix onto
        # the axis instead of printing the actual numbers.
        for plot in (self.p1, self.p2):
            plot.getAxis("left").enableAutoSIPrefix(False)

        # Plot 1: Temperature. The RH panel below is derived from these
        # (dewpoint + chiller temp), so the colours match across panels:
        # chiller temp (blue) feeds RH (Chiller Temp) (blue).
        self._style_plot(self.p1, "Temperature", "Temp (°C)")
        self._solid_line(self.p1, "dewpoint", "c", "Dewpoint")
        self._solid_line(self.p1, "chiller", "b", "Chiller")
        self._dashed_line(self.p1, "chiller_set", "b", "Chiller Set")

        # Plot 2: Humidity + Oxygen (both in %)
        self._style_plot(self.p2, "RH & O₂", "%", x_label="Time")
        self._solid_line(self.p2, "rh_chiller", "b", "RH (Chiller Temp)")
        self._solid_line(self.p2, "rh_chiller_calibrated", "r", "RH (Chiller Temp, Calibrated)")
        self._solid_line(self.p2, "oxygen", "g", "O₂ (FireSting)")

    def update_plot(self, data: Dict[str, Optional[float]]):
        # Parse timestamp
        if "timestamp" not in data:
            timestamp = datetime.now()
        else:
            timestamp = (
                datetime.fromisoformat(data["timestamp"])
                if isinstance(data["timestamp"], str)
                else data["timestamp"]
            )

        # Coerce None -> np.nan so numpy conversions later don't raise
        def _coerce(v):
            return v if v is not None else np.nan

        self.timestamps.append(timestamp)
        self.dewpoint_temp.append(_coerce(data.get("dewpoint_temp")))
        self.chiller_temp.append(_coerce(data.get("chiller_temp")))
        self.chiller_setpoint.append(_coerce(data.get("chiller_setpoint")))
        self.rh_chiller.append(_coerce(data.get("rh_chiller")))
        self.rh_chiller_calibrated.append(_coerce(data.get("rh_chiller_calibrated")))
        self.oxygen.append(_coerce(data.get("oxygen")))

        self._redraw()

    def _redraw(self):
        if len(self.timestamps) == 0:
            return

        # DateAxisItem expects POSIX seconds on the x-axis.
        time_data = np.array([t.timestamp() for t in self.timestamps], dtype=np.float64)

        # Helper to update line with valid data only (to ensure lines connect)
        def update_line_filtered(line, series):
            y_data = np.array(list(series), dtype=np.float64)
            mask = ~np.isnan(y_data)
            if np.any(mask):
                line.setData(time_data[mask], y_data[mask])
            else:
                line.setData([], [])

        update_line_filtered(self._lines["dewpoint"], self.dewpoint_temp)
        update_line_filtered(self._lines["chiller"], self.chiller_temp)
        update_line_filtered(self._lines["chiller_set"], self.chiller_setpoint)

        update_line_filtered(self._lines["rh_chiller"], self.rh_chiller)
        update_line_filtered(self._lines["rh_chiller_calibrated"], self.rh_chiller_calibrated)
        update_line_filtered(self._lines["oxygen"], self.oxygen)
