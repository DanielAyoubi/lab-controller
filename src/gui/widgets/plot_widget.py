from typing import Dict, Optional
from collections import namedtuple, deque
from datetime import datetime
import numpy as np
import pyqtgraph as pg

from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtCore import Qt


# Match Matplotlib's single-letter colours so the appearance is preserved.
_COLORS = {
    "b": (0, 0, 255),      # blue
    "r": (255, 0, 0),      # red
    "g": (0, 128, 0),      # green
    "c": (0, 191, 191),    # cyan
    "m": (200, 0, 200),    # magenta
    "o": (255, 140, 0),    # orange
}


# Declarative description of every trace on the plot. Keeping it in one place
# means __init__, set_max_points, clear, update_plot and _redraw can't drift out
# of sync, and left/right-axis assignment is data-driven.
#   panel: which stacked panel (1 = top, 2 = bottom)
#   side : "left" (primary axis) or "right" (secondary axis, own scale)
#   style: "solid" (line + dot markers) or "dashed" (setpoint, semi-transparent)
Series = namedtuple("Series", "key field label color style panel side")

_SERIES_SPEC = (
    # Panel 1 — Flow & RH. RH on the left axis, flows on a right axis: the
    # wet/dry flow ratio is what drives RH, so they belong on one panel.
    Series("rh_chiller",            "rh_chiller",            "RH (Chiller Temp)",         "b", "solid",  1, "left"),
    Series("rh_chiller_calibrated", "rh_chiller_calibrated", "RH (Chiller, Calibrated)",  "r", "solid",  1, "left"),
    Series("rh_hygrometer",         "rh_hygrometer",         "RH (Hygrometer)",           "m", "solid",  1, "left"),
    Series("dry_flow",              "dry_flow",              "Dry Flow",                  "g", "solid",  1, "right"),
    Series("wet_flow",              "wet_flow",              "Wet Flow",                  "o", "solid",  1, "right"),
    Series("dry_flow_setpoint",     "dry_flow_setpoint",     "Dry Flow Set",              "g", "dashed", 1, "right"),
    Series("wet_flow_setpoint",     "wet_flow_setpoint",     "Wet Flow Set",              "o", "dashed", 1, "right"),

    # Panel 2 — Temperature & O₂. Temps on the left axis; O₂ gets its own right
    # axis so its ~20 % range isn't squashed against the 0-100 % RH scale.
    Series("dewpoint",        "dewpoint_temp",    "Dewpoint",        "c", "solid",  2, "left"),
    Series("chiller",         "chiller_temp",     "Chiller",         "b", "solid",  2, "left"),
    Series("chiller_set",     "chiller_setpoint", "Chiller Set",     "b", "dashed", 2, "left"),
    Series("hygrometer_temp", "hygrometer_temp",  "Hygrometer Temp", "o", "solid",  2, "left"),
    Series("oxygen",          "oxygen",           "O₂ (FireSting)",  "g", "solid",  2, "right"),
)

# Per-panel axis titles/labels.
_PANELS = {
    1: {"title": "Flow & RH",        "left": "RH (%)",     "right": "Flow (L/min)", "xlabel": None},
    2: {"title": "Temperature & O₂", "left": "Temp (°C)",  "right": "O₂ (%)",       "xlabel": "Time"},
}

# The distinct data fields we buffer (derived from the spec so storage stays in
# sync with what is drawn).
_FIELDS = tuple(dict.fromkeys(s.field for s in _SERIES_SPEC))


class RealTimePlotWidget(QWidget):
    def __init__(self, max_points: int = 500):
        super().__init__()
        self.max_points = max_points

        # Data storage: one deque per data field, plus the shared time axis.
        self.timestamps = deque(maxlen=max_points)
        self._data = {f: deque(maxlen=max_points) for f in _FIELDS}

        # Layout
        pg.setConfigOptions(antialias=True, background="w", foreground="k")
        layout = QVBoxLayout()
        self.glw = pg.GraphicsLayoutWidget()
        self.glw.setBackground("w")
        layout.addWidget(self.glw)
        self.setLayout(layout)

        self._lines = {}        # series key -> PlotDataItem
        self._right_vbs = {}    # panel number -> right-axis ViewBox
        self._setup_plots()

    def set_max_points(self, max_points: int):
        self.max_points = max_points
        # Re-create deques with new maxlen, preserving existing data.
        self.timestamps = deque(self.timestamps, maxlen=max_points)
        for f in _FIELDS:
            self._data[f] = deque(self._data[f], maxlen=max_points)

    def clear(self):
        """Drop all buffered data and blank every line on the plot."""
        self.timestamps.clear()
        for d in self._data.values():
            d.clear()
        for line in self._lines.values():
            line.setData([], [])

    def _make_line(self, color, style, label):
        """Create a PlotDataItem: solid = line + dot markers, dashed = setpoint."""
        rgb = _COLORS[color]
        if style == "dashed":
            pen = pg.mkPen((*rgb, 128), width=1, style=Qt.PenStyle.DashLine)
            return pg.PlotDataItem([], [], pen=pen, name=label)
        return pg.PlotDataItem(
            [],
            [],
            pen=pg.mkPen(rgb, width=1),
            symbol="o",
            symbolSize=4,
            symbolBrush=rgb,
            symbolPen=None,
            name=label,
        )

    def _add_right_axis(self, panel, panel_num, label):
        """Give `panel` a second y-axis (pyqtgraph has no Matplotlib twinx)."""
        vb = pg.ViewBox()
        panel.showAxis("right")
        panel.scene().addItem(vb)
        panel.getAxis("right").linkToView(vb)
        panel.getAxis("right").setLabel(label)
        panel.getAxis("right").enableAutoSIPrefix(False)
        vb.setXLink(panel)
        self._right_vbs[panel_num] = vb

        # Keep the secondary ViewBox aligned with the main one on every resize.
        # The x-link means our setGeometry re-fires the main box's sigResized,
        # so a re-entrancy guard is required to avoid infinite recursion.
        guard = {"busy": False}

        def _sync(vb=vb, p=panel, guard=guard):
            if guard["busy"]:
                return
            guard["busy"] = True
            try:
                vb.setGeometry(p.getViewBox().sceneBoundingRect())
                vb.linkedViewChanged(p.getViewBox(), vb.XAxis)
            finally:
                guard["busy"] = False

        panel.getViewBox().sigResized.connect(_sync)
        _sync()

    def _setup_plots(self):
        # Build the stacked panels, top to bottom, sharing one time x-axis.
        panels = {}
        first = None
        self._x_panel = None  # the panel all others x-link to; drives the time window
        for row, num in enumerate(sorted(_PANELS)):
            cfg = _PANELS[num]
            axis = pg.DateAxisItem(orientation="bottom")
            panel = self.glw.addPlot(row=row, col=0, axisItems={"bottom": axis})
            panel.setTitle(f"<b>{cfg['title']}</b>", size="10pt")
            panel.setLabel("left", cfg["left"])
            if cfg["xlabel"]:
                panel.setLabel("bottom", cfg["xlabel"])
            panel.showGrid(x=True, y=True, alpha=0.3)
            panel.getAxis("left").enableAutoSIPrefix(False)
            panel._legend = panel.addLegend(offset=(10, 10))

            if first is None:
                first = panel
                self._x_panel = panel
            else:
                panel.setXLink(first)

            if cfg["right"]:
                self._add_right_axis(panel, num, cfg["right"])

            panels[num] = panel

        # Create each trace and attach it to the correct panel/axis.
        for s in _SERIES_SPEC:
            panel = panels[s.panel]
            line = self._make_line(s.color, s.style, s.label)
            self._lines[s.key] = line
            if s.side == "right":
                # Right-axis items live in a separate ViewBox, so they are not
                # auto-registered in the panel legend — add them by hand.
                self._right_vbs[s.panel].addItem(line)
                panel._legend.addItem(line, s.label)
            else:
                panel.addItem(line)  # auto-registers in the legend

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

        # Coerce None -> np.nan so numpy conversions later don't raise.
        def _coerce(v):
            return v if v is not None else np.nan

        self.timestamps.append(timestamp)
        for f in _FIELDS:
            self._data[f].append(_coerce(data.get(f)))

        self._redraw()

    def _redraw(self):
        if len(self.timestamps) == 0:
            return

        # DateAxisItem expects POSIX seconds on the x-axis.
        time_data = np.array([t.timestamp() for t in self.timestamps], dtype=np.float64)

        # Update a line with valid data only (so line segments connect across
        # missing samples instead of breaking at every NaN).
        def update_line_filtered(line, series):
            y_data = np.array(list(series), dtype=np.float64)
            mask = ~np.isnan(y_data)
            if np.any(mask):
                line.setData(time_data[mask], y_data[mask])
            else:
                line.setData([], [])

        for s in _SERIES_SPEC:
            update_line_filtered(self._lines[s.key], self._data[s.field])

        # Frame the time window explicitly. Auto-range on each panel only sees
        # that panel's own left-axis items, so when a panel's left-axis series
        # have no data (e.g. hygrometer/chiller offline) its X stays at the
        # default [0,1] and the right-axis data (flows / O₂, in a linked
        # ViewBox) is drawn far off-screen. Setting X from the actual timestamps
        # keeps the window over the data whichever axis is carrying it.
        if self._x_panel is not None:
            t_min = float(time_data[0])
            t_max = float(time_data[-1])
            if t_max <= t_min:
                t_max = t_min + 1.0  # single point: give the axis a finite width
            self._x_panel.setXRange(t_min, t_max, padding=0.02)
