from typing import Dict, List, Optional
from collections import deque
from datetime import datetime
import numpy as np
import pyqtgraph as pg

from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtCore import Qt

from src.devices.registry import PANELS

_LEGEND_TEXT_SIZE = "10pt"

_PALETTE = [
    (31, 119, 180),   # blue
    (255, 127, 14),   # orange
    (44, 160, 44),    # green
    (214, 39, 40),    # red
    (148, 103, 189),  # purple
    (23, 190, 207),   # cyan
    (227, 119, 194),  # pink
    (140, 86, 75),    # brown
    (188, 189, 34),   # olive
    (127, 127, 127),  # grey
]

# pyqtgraph symbol codes, chosen to stay legible at ~7 px.
_SYMBOLS = ["o", "s", "t", "d", "p", "h", "star", "t1"]

# Line styles for a device's *measurement* channels that land in the same panel
# — a probe contributes both Temp and Dewpoint to the temperature panel, and
# sharing the device colour would otherwise make them one indistinguishable
# pair. DashLine is reserved: it always and only means a setpoint.
_LINE_STYLES = [Qt.PenStyle.SolidLine, Qt.PenStyle.DashDotLine, Qt.PenStyle.DotLine]

# A setpoint is usually *equal* to its measurement — an MFC sits on its
# commanded flow — so drawing it in the same colour at the same width simply
# hides it under the measurement. Instead it is a pale, wider halo *behind*:
# where the two agree you see a soft band, where they diverge the halo pulls away.
_WIDTH_MEASURED = 2.2
_WIDTH_SETPOINT = 5.0
_SETPOINT_TINT = 0.6     # how far to blend the device colour toward white
_Z_MEASURED = 1
_Z_SETPOINT = -1         # behind, so the measurement stays crisp on top

# Roughly how many markers to draw along a trace: enough to identify the shape,
# few enough that they never merge into a band and hide the line's colour.
_MARKERS_PER_TRACE = 22
_SYMBOL_SIZE = 7.0


def _marker_stride(n_points: int) -> int:
    """Draw a marker every Nth point so they never merge into a solid band."""
    return max(1, n_points // _MARKERS_PER_TRACE)


def _assign_styles(manifest):
    """Map each manifest column to its pyqtgraph drawing style."""
    groups = []
    for entry in manifest:
        group = entry.get("group") or entry["column"]
        if group not in groups:
            groups.append(group)

    seen_in_panel = {}   # (group, panel) -> measurement traces so far
    styles = {}
    for entry in manifest:
        group = entry.get("group") or entry["column"]
        group_idx = groups.index(group)
        rgb = _PALETTE[group_idx % len(_PALETTE)]
        dashed = bool(entry.get("dashed"))

        if dashed:
            # A setpoint mirrors its measurement rather than being a channel in
            # its own right, so it does not consume a line style.
            channel_idx = 0
            pen_style = Qt.PenStyle.DashLine
            rgb = tuple(int(round(c + (255 - c) * _SETPOINT_TINT)) for c in rgb)
        else:
            key = (group, entry["panel"])
            channel_idx = seen_in_panel.get(key, 0)
            seen_in_panel[key] = channel_idx + 1
            pen_style = _LINE_STYLES[channel_idx % len(_LINE_STYLES)]

        styles[entry["column"]] = {
            "rgb": rgb,
            "symbol": _SYMBOLS[(group_idx + channel_idx) % len(_SYMBOLS)],
            "dashed": dashed,
            "pen_style": pen_style,
            "width": _WIDTH_SETPOINT if dashed else _WIDTH_MEASURED,
            "z": _Z_SETPOINT if dashed else _Z_MEASURED,
        }
    return styles


class RealTimePlotWidget(QWidget):
    """Three shared-x panels — flows, temperatures, percentages.

    The widget knows nothing about specific devices. It is driven by a *series
    manifest* (see ``registry.build_manifest``): a list of
    ``{column, label, panel, dashed}`` entries produced from the configured
    device set. ``configure()`` rebuilds the traces whenever that set changes,
    which is what puts each device's tag into the legend.
    """

    def __init__(self, max_points: int = 500):
        super().__init__()
        self.max_points = max_points
        self.manifest: List[Dict] = []

        pg.setConfigOptions(antialias=True, background="w", foreground="k")
        layout = QVBoxLayout()
        self.glw = pg.GraphicsLayoutWidget()
        self.glw.setBackground("w")
        layout.addWidget(self.glw)
        self.setLayout(layout)

        self.timestamps: deque = deque(maxlen=max_points)
        self._series: Dict[str, deque] = {}   # column -> values
        self._lines: Dict[str, pg.PlotDataItem] = {}
        self._panels: Dict[str, pg.PlotItem] = {}
        self._legends: Dict[str, pg.LegendItem] = {}
        self._styles: Dict[str, Dict] = {}

        self._setup_panels()

    # ── Layout ───────────────────────────────────────────────────────────────

    def _setup_panels(self):
        """Create the three empty panels once; traces are added by configure()."""
        first: Optional[pg.PlotItem] = None
        for row, (key, title, y_label) in enumerate(PANELS):
            plot = self.glw.addPlot(
                row=row, col=0,
                axisItems={"bottom": pg.DateAxisItem(orientation="bottom")},
            )
            plot.setTitle(f"<b>{title}</b>", size="10pt")
            plot.setLabel("left", y_label)
            plot.showGrid(x=True, y=True, alpha=0.3)
            # pyqtgraph defaults to auto SI-prefix scaling, which for small
            # values tacks a multiplier onto the axis instead of the real numbers.
            plot.getAxis("left").enableAutoSIPrefix(False)
            # No panel behind the legend — it sits directly on the plot. The
            # labels carry their own contrast instead (see _embolden_legend).
            self._legends[key] = plot.addLegend(
                offset=(10, 10),
                labelTextColor=(0, 0, 0),
                labelTextSize=_LEGEND_TEXT_SIZE,
            )
            if first is None:
                first = plot
            else:
                plot.setXLink(first)   # shared x-axis across all three panels
            self._panels[key] = plot
        if PANELS:
            self._panels[PANELS[-1][0]].setLabel("bottom", "Time")

    def configure(self, manifest: List[Dict]):
        """Rebuild the traces for a new device set. Drops all buffered data."""
        self.manifest = list(manifest or [])

        for line in self._lines.values():
            line.clear()
        for legend in self._legends.values():
            legend.clear()
        for plot in self._panels.values():
            plot.clearPlots()
        self._lines.clear()
        self._series.clear()
        self.timestamps.clear()

        # One colour and marker shape per device, so a setpoint reads as the
        # dashed twin of its own measurement rather than a separate quantity.
        self._styles = _assign_styles(self.manifest)
        for entry in self.manifest:
            panel = self._panels.get(entry["panel"])
            if panel is None:
                continue
            column = entry["column"]
            style = self._styles[column]
            self._series[column] = deque(maxlen=self.max_points)
            self._lines[column] = (
                self._dashed_line(panel, style, entry["label"])
                if style["dashed"]
                else self._solid_line(panel, style, entry["label"])
            )

        self._embolden_legends()

    def _embolden_legends(self):
        """Re-render every legend label in bold.

        ``LegendItem.addItem`` builds its ``LabelItem`` with only colour, size
        and justification — there is no way to ask for bold up front — so the
        labels are restyled once the traces exist. ``setText`` merges these
        options into the ones already set, keeping colour and size.
        """
        for legend in self._legends.values():
            for _sample, label in legend.items:
                label.setText(label.text, bold=True, size=_LEGEND_TEXT_SIZE)
            legend.updateSize()

    @staticmethod
    def _solid_line(plot, style, label):
        """Measurement: a solid line carrying the device's marker shape.

        Markers are thinned out at draw time (see ``_redraw``) — the shape is
        there to identify the trace and to appear in the legend sample, not to
        mark every sample.
        """
        rgb = style["rgb"]
        item = plot.plot(
            [], [],
            pen=pg.mkPen(rgb, width=style["width"], style=style["pen_style"]),
            symbol=style["symbol"], symbolSize=_SYMBOL_SIZE,
            symbolBrush=rgb, symbolPen=pg.mkPen("w", width=0.5),
            name=label,
        )
        item.setZValue(style["z"])
        return item

    @staticmethod
    def _dashed_line(plot, style, label):
        """Setpoint: a pale, wide dashed halo drawn behind its measurement."""
        pen = pg.mkPen(style["rgb"], width=style["width"],
                       style=style["pen_style"])
        item = plot.plot([], [], pen=pen, name=label)
        item.setZValue(style["z"])
        return item

    # ── Data ─────────────────────────────────────────────────────────────────

    def set_max_points(self, max_points: int):
        self.max_points = max_points
        # Re-create deques with the new maxlen, preserving existing data.
        self.timestamps = deque(self.timestamps, maxlen=max_points)
        for column, values in self._series.items():
            self._series[column] = deque(values, maxlen=max_points)

    def clear(self):
        """Drop all buffered data and blank every line on the plot."""
        self.timestamps.clear()
        for values in self._series.values():
            values.clear()
        for line in self._lines.values():
            line.setData([], [])

    def update_plot(self, data: Dict[str, Optional[float]]):
        raw = data.get("timestamp")
        if raw is None:
            timestamp = datetime.now()
        else:
            timestamp = datetime.fromisoformat(raw) if isinstance(raw, str) else raw

        self.timestamps.append(timestamp)
        for column, values in self._series.items():
            value = data.get(column)
            # Coerce None -> nan so the numpy conversion below never raises.
            values.append(value if value is not None else np.nan)

        self._redraw()

    def _redraw(self):
        if len(self.timestamps) == 0:
            return

        # DateAxisItem expects POSIX seconds on the x-axis.
        time_data = np.array([t.timestamp() for t in self.timestamps], dtype=np.float64)

        for column, values in self._series.items():
            line = self._lines.get(column)
            if line is None:
                continue
            y_data = np.array(list(values), dtype=np.float64)
            # Plot only the valid points so gaps from a dropped-out device
            # connect through instead of breaking the trace.
            n = min(len(time_data), len(y_data))
            mask = ~np.isnan(y_data[:n])
            if not np.any(mask):
                line.setData([], [])
                continue

            xs, ys = time_data[:n][mask], y_data[:n][mask]
            style = self._styles.get(column, {})
            if style.get("dashed", True):
                line.setData(xs, ys)
                continue

            # Show the marker on every Nth point only. Drawing one per sample
            # turns a 500-point trace into a solid band that hides both the
            # line's colour and its shape; a size of 0 skips a point without
            # removing the symbol from the item (so the legend still shows it).
            sizes = np.zeros(len(xs))
            sizes[::_marker_stride(len(xs))] = _SYMBOL_SIZE
            line.setData(xs, ys, symbolSize=sizes)
