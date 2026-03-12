from typing import Dict, Optional
from collections import deque
from datetime import datetime
import numpy as np
import matplotlib.pyplot as plt

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.dates import DateFormatter
import matplotlib.dates as mdates

from PyQt6.QtWidgets import QWidget, QVBoxLayout

class MplCanvas(FigureCanvas):
    def __init__(self, parent=None, width=5, height=4, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi)
        self.axes = self.fig.subplots(3, 1, sharex=True)
        super(MplCanvas, self).__init__(self.fig)

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

        # Layout
        layout = QVBoxLayout()
        self.canvas = MplCanvas(self, width=5, height=10, dpi=100)
        layout.addWidget(self.canvas)
        self.setLayout(layout)

        self._lines = {}
        self._redraw_count = 0
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

    def _setup_plots(self):
        ax1, ax2, ax3 = self.canvas.axes

        # Plot 1: Flow rates
        self._lines['dry_actual'], = ax1.plot([], [], "b.-", label="Dry Actual")
        self._lines['dry_set'], = ax1.plot([], [], "b--", alpha=0.5, label="Dry Set")
        self._lines['wet_actual'], = ax1.plot([], [], "r.-", label="Wet Actual")
        self._lines['wet_set'], = ax1.plot([], [], "r--", alpha=0.5, label="Wet Set")
        
        ax1.set_title("Mass Flow Controllers", fontweight="bold", fontsize=10)
        ax1.set_ylabel("Flow (L/min)", fontsize=9)
        ax1.grid(True, alpha=0.3)
        ax1.legend(loc="upper left", fontsize='small')
        
        # Plot 2: Temperature
        self._lines['hygrometer'], = ax2.plot([], [], "g.-", label="Hygrometer")
        self._lines['dewpoint'], = ax2.plot([], [], "c.-", label="Dewpoint")
        self._lines['chiller'], = ax2.plot([], [], "b.-", label="Chiller")
        self._lines['chiller_set'], = ax2.plot([], [], "b--", alpha=0.5, label="Chiller Set")

        ax2.set_title("Temperature", fontweight="bold", fontsize=10)
        ax2.set_ylabel("Temp (°C)", fontsize=9)
        ax2.grid(True, alpha=0.3)
        ax2.legend(loc="upper left", fontsize='small')

        # Plot 3: Humidity
        self._lines['rh_hygrometer'], = ax3.plot([], [], "g.-", label="RH (Hygrometer Temp)")
        self._lines['rh_chiller'], = ax3.plot([], [], "b.-", label="RH (Chiller Temp)")

        ax3.set_title("Relative Humidity", fontweight="bold", fontsize=10)
        ax3.set_ylabel("RH (%)", fontsize=9)
        ax3.set_xlabel("Time", fontsize=9)
        ax3.grid(True, alpha=0.3)
        ax3.legend(loc="upper left", fontsize='small')

        # Format Date
        date_fmt = DateFormatter("%H:%M:%S")
        ax3.xaxis.set_major_formatter(date_fmt)
        plt.setp(ax3.xaxis.get_majorticklabels(), rotation=45, ha="right")

        self.canvas.fig.tight_layout()

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

        self._redraw()

    def _redraw(self):
        if len(self.timestamps) == 0:
            return

        # Convert timestamps to numpy array once for efficiency
        time_data = np.array(mdates.date2num(list(self.timestamps)))

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

        # Helper to update line with valid data only (to ensure lines connect)
        def update_line_filtered(line, y_data):
            # Filter valid data
            mask = ~np.isnan(y_data)
            if np.any(mask):
                line.set_data(time_data[mask], y_data[mask])
            else:
                line.set_data([], [])
        
        update_line_filtered(self._lines['dry_actual'], dry_flow_data)
        update_line_filtered(self._lines['dry_set'], dry_setpoint_data)
        update_line_filtered(self._lines['wet_actual'], wet_flow_data)
        update_line_filtered(self._lines['wet_set'], wet_setpoint_data)
        
        update_line_filtered(self._lines['hygrometer'], hygrometer_temp_data)
        update_line_filtered(self._lines['dewpoint'], dewpoint_temp_data)
        update_line_filtered(self._lines['chiller'], chiller_temp_data)
        update_line_filtered(self._lines['chiller_set'], chiller_setpoint_data)
        
        update_line_filtered(self._lines['rh_hygrometer'], rh_hygrometer_data)
        update_line_filtered(self._lines['rh_chiller'], rh_chiller_data)

        # Rescale axes — relim every tick, autoscale every 10 to reduce CPU cost
        self._redraw_count += 1
        for ax in self.canvas.axes:
            ax.relim()
            if self._redraw_count % 10 == 0:
                ax.autoscale_view()

        self.canvas.draw_idle()
