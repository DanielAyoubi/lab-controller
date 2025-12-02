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
        self.ambient_temp = deque(maxlen=max_points)
        self.dewpoint_temp = deque(maxlen=max_points)
        self.relative_humidity = deque(maxlen=max_points)

        # Layout
        layout = QVBoxLayout()
        self.canvas = MplCanvas(self, width=5, height=10, dpi=100)
        layout.addWidget(self.canvas)
        self.setLayout(layout)

        self._lines = {}
        self._setup_plots()

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
        self._lines['ambient'], = ax2.plot([], [], "g.-", label="Ambient")
        self._lines['dewpoint'], = ax2.plot([], [], "c.-", label="Dewpoint")

        ax2.set_title("Temperature", fontweight="bold", fontsize=10)
        ax2.set_ylabel("Temp (°C)", fontsize=9)
        ax2.grid(True, alpha=0.3)
        ax2.legend(loc="upper left", fontsize='small')

        # Plot 3: Humidity
        self._lines['rh'], = ax3.plot([], [], "m.-", label="RH")

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

    def update_plot(self, data: Dict[str, float]):
        # Parse timestamp
        if "timestamp" not in data:
            timestamp = datetime.now()
        else:
            timestamp = (
                datetime.fromisoformat(data["timestamp"])
                if isinstance(data["timestamp"], str)
                else data["timestamp"]
            )

        self.timestamps.append(timestamp)
        self.dry_flow.append(data.get("dry_flow", np.nan))
        self.wet_flow.append(data.get("wet_flow", np.nan))
        self.dry_setpoint.append(data.get("dry_flow_setpoint", np.nan))
        self.wet_setpoint.append(data.get("wet_flow_setpoint", np.nan))
        self.ambient_temp.append(data.get("ambient_temp", np.nan))
        self.dewpoint_temp.append(data.get("dewpoint_temp", np.nan))
        
        # Choose the best RH source to display
        rh = data.get("relative_humidity_control")
        if rh is None:
            rh = data.get("relative_humidity_cell_calc")
        if rh is None:
            rh = data.get("relative_humidity_calculated")
        if rh is None:
            rh = data.get("relative_humidity_device")
            
        self.relative_humidity.append(rh if rh is not None else np.nan)

        self._redraw()

    def _redraw(self):
        if len(self.timestamps) == 0:
            return

        # Convert timestamps to numpy array for masking
        time_data = np.array(mdates.date2num(list(self.timestamps)))

        # Helper to update line with valid data only (to ensure lines connect)
        def update_line(line, data_deque):
            # Convert to float array (None becomes NaN)
            y_data = np.array(list(data_deque), dtype=np.float64)
            
            # Filter valid data
            mask = ~np.isnan(y_data)
            if np.any(mask):
                line.set_data(time_data[mask], y_data[mask])
            else:
                line.set_data([], [])

        # Update data
        update_line(self._lines['dry_actual'], self.dry_flow)
        update_line(self._lines['dry_set'], self.dry_setpoint)
        update_line(self._lines['wet_actual'], self.wet_flow)
        update_line(self._lines['wet_set'], self.wet_setpoint)
        
        update_line(self._lines['ambient'], self.ambient_temp)
        update_line(self._lines['dewpoint'], self.dewpoint_temp)
        
        update_line(self._lines['rh'], self.relative_humidity)

        # Rescale axes
        for ax in self.canvas.axes:
            ax.relim()
            ax.autoscale_view()

        self.canvas.draw()
