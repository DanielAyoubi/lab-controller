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


class RealTimePlotWidget(QWidget):
    def __init__(self, max_points: int = 500):
        super().__init__()
        self.max_points = max_points

        # Data storage
        self.timestamps = deque(maxlen=max_points)
        self.dry_flow = deque(maxlen=max_points)
        self.wet_flow = deque(maxlen=max_points)
        self.dry_setpoint = deque(maxlen=max_points)
        self.wet_setpoint = deque(maxlen=max_points)
        self.hygrometer_temp = deque(maxlen=max_points)
        self.dewpoint_temp = deque(maxlen=max_points)
        self.chiller_temp = deque(maxlen=max_points)
        self.chiller_setpoint = deque(maxlen=max_points)
        self.rh_hygrometer = deque(maxlen=max_points)
        self.rh_chiller = deque(maxlen=max_points)
        self.rh_chiller_calibrated = deque(maxlen=max_points)

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
        self.timestamps = deque(self.timestamps, maxlen=max_points)
        self.dry_flow = deque(self.dry_flow, maxlen=max_points)
        self.wet_flow = deque(self.wet_flow, maxlen=max_points)
        self.dry_setpoint = deque(self.dry_setpoint, maxlen=max_points)
        self.wet_setpoint = deque(self.wet_setpoint, maxlen=max_points)
        self.hygrometer_temp = deque(self.hygrometer_temp, maxlen=max_points)
        self.dewpoint_temp = deque(self.dewpoint_temp, maxlen=max_points)
        self.chiller_temp = deque(self.chiller_temp, maxlen=max_points)
        self.chiller_setpoint = deque(self.chiller_setpoint, maxlen=max_points)
        self.rh_hygrometer = deque(self.rh_hygrometer, maxlen=max_points)
        self.rh_chiller = deque(self.rh_chiller, maxlen=max_points)
        self.rh_chiller_calibrated = deque(self.rh_chiller_calibrated, maxlen=max_points)

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
        axis3 = pg.DateAxisItem(orientation="bottom")

        self.p1 = self.glw.addPlot(row=0, col=0, axisItems={"bottom": axis1})
        self.p2 = self.glw.addPlot(row=1, col=0, axisItems={"bottom": axis2})
        self.p3 = self.glw.addPlot(row=2, col=0, axisItems={"bottom": axis3})

        # Shared x-axis (replaces Matplotlib sharex=True)
        self.p2.setXLink(self.p1)
        self.p3.setXLink(self.p1)

        # Plot 1: Flow rates
        self._style_plot(self.p1, "Mass Flow Controllers", "Flow (L/min)")
        self._solid_line(self.p1, "dry_actual", "b", "Dry Actual")
        self._dashed_line(self.p1, "dry_set", "b", "Dry Set")
        self._solid_line(self.p1, "wet_actual", "r", "Wet Actual")
        self._dashed_line(self.p1, "wet_set", "r", "Wet Set")

        # Plot 2: Temperature
        self._style_plot(self.p2, "Temperature", "Temp (°C)")
        self._solid_line(self.p2, "hygrometer", "g", "Hygrometer")
        self._solid_line(self.p2, "dewpoint", "c", "Dewpoint")
        self._solid_line(self.p2, "chiller", "b", "Chiller")
        self._dashed_line(self.p2, "chiller_set", "b", "Chiller Set")

        # Plot 3: Humidity
        self._style_plot(self.p3, "Relative Humidity", "RH (%)", x_label="Time")
        self._solid_line(self.p3, "rh_hygrometer", "g", "RH (Hygrometer Temp)")
        self._solid_line(self.p3, "rh_chiller", "b", "RH (Chiller Temp)")
        self._solid_line(self.p3, "rh_chiller_calibrated", "r", "RH (Chiller Temp, Calibrated)")

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
        self.dry_flow.append(_coerce(data.get("dry_flow")))
        self.wet_flow.append(_coerce(data.get("wet_flow")))
        self.dry_setpoint.append(_coerce(data.get("dry_flow_setpoint")))
        self.wet_setpoint.append(_coerce(data.get("wet_flow_setpoint")))
        self.hygrometer_temp.append(_coerce(data.get("hygrometer_temp")))
        self.dewpoint_temp.append(_coerce(data.get("dewpoint_temp")))
        self.chiller_temp.append(_coerce(data.get("chiller_temp")))
        self.chiller_setpoint.append(_coerce(data.get("chiller_setpoint")))
        self.rh_hygrometer.append(_coerce(data.get("rh_hygrometer")))
        self.rh_chiller.append(_coerce(data.get("rh_chiller")))
        self.rh_chiller_calibrated.append(_coerce(data.get("rh_chiller_calibrated")))

        self._redraw()

    def _redraw(self):
        if len(self.timestamps) == 0:
            return

        # DateAxisItem expects POSIX seconds on the x-axis.
        time_data = np.array([t.timestamp() for t in self.timestamps], dtype=np.float64)

        # Convert all deques to numpy arrays once
        dry_flow_data = np.array(list(self.dry_flow), dtype=np.float64)
        dry_setpoint_data = np.array(list(self.dry_setpoint), dtype=np.float64)
        wet_flow_data = np.array(list(self.wet_flow), dtype=np.float64)
        wet_setpoint_data = np.array(list(self.wet_setpoint), dtype=np.float64)
        hygrometer_temp_data = np.array(list(self.hygrometer_temp), dtype=np.float64)
        dewpoint_temp_data = np.array(list(self.dewpoint_temp), dtype=np.float64)
        chiller_temp_data = np.array(list(self.chiller_temp), dtype=np.float64)
        chiller_setpoint_data = np.array(list(self.chiller_setpoint), dtype=np.float64)
        rh_hygrometer_data = np.array(list(self.rh_hygrometer), dtype=np.float64)
        rh_chiller_data = np.array(list(self.rh_chiller), dtype=np.float64)
        rh_chiller_calibrated_data = np.array(list(self.rh_chiller_calibrated), dtype=np.float64)

        # Helper to update line with valid data only (to ensure lines connect)
        def update_line_filtered(line, y_data):
            # Filter valid data
            mask = ~np.isnan(y_data)
            if np.any(mask):
                line.setData(time_data[mask], y_data[mask])
            else:
                line.setData([], [])

        update_line_filtered(self._lines["dry_actual"], dry_flow_data)
        update_line_filtered(self._lines["dry_set"], dry_setpoint_data)
        update_line_filtered(self._lines["wet_actual"], wet_flow_data)
        update_line_filtered(self._lines["wet_set"], wet_setpoint_data)

        update_line_filtered(self._lines["hygrometer"], hygrometer_temp_data)
        update_line_filtered(self._lines["dewpoint"], dewpoint_temp_data)
        update_line_filtered(self._lines["chiller"], chiller_temp_data)
        update_line_filtered(self._lines["chiller_set"], chiller_setpoint_data)

        update_line_filtered(self._lines["rh_hygrometer"], rh_hygrometer_data)
        update_line_filtered(self._lines["rh_chiller"], rh_chiller_data)
        update_line_filtered(self._lines["rh_chiller_calibrated"], rh_chiller_calibrated_data)
