from typing import Dict, List, Optional
from collections import deque
from datetime import datetime
import numpy as np
import pyqtgraph as pg

from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtCore import Qt

from src.devices.registry import PANELS
from src.utility import series_style

# Legend text: a touch larger than pyqtgraph's 9pt default, and bold, so it
# stays readable sitting directly on the grid without a panel behind it.
_LEGEND_TEXT_SIZE = "10pt"

# series_style names line styles abstractly so the saved PNG can use the same
# vocabulary; this maps them onto Qt's pen styles.
_PEN_STYLES = {
    "solid": Qt.PenStyle.SolidLine,
    "dashdot": Qt.PenStyle.DashDotLine,
    "dot": Qt.PenStyle.DotLine,
    "dashed": Qt.PenStyle.DashLine,
}


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
        self._styles = series_style.assign_styles(self.manifest)
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
            pen=pg.mkPen(rgb, width=style["width"],
                         style=_PEN_STYLES[style["line_style"]]),
            symbol=style["symbol"], symbolSize=series_style.SYMBOL_SIZE,
            symbolBrush=rgb, symbolPen=pg.mkPen("w", width=0.5),
            name=label,
        )
        item.setZValue(style["z"])
        return item

    @staticmethod
    def _dashed_line(plot, style, label):
        """Setpoint: a pale, wide dashed halo drawn behind its measurement."""
        pen = pg.mkPen(style["rgb"], width=style["width"],
                       style=Qt.PenStyle.DashLine)
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
            sizes[::series_style.marker_stride(len(xs))] = series_style.SYMBOL_SIZE
            line.setData(xs, ys, symbolSize=sizes)
