from collections import deque
from datetime import datetime
from typing import Dict, List, Optional

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation
from matplotlib.dates import DateFormatter


class DynamicPlotter:
    def __init__(self, max_points: int = 500, update_interval: int = 1000):
        self.max_points = max_points
        self.update_interval = update_interval

        # Data storage (using deque for efficient append/pop)
        self.timestamps = deque(maxlen=max_points)
        self.dry_flow = deque(maxlen=max_points)
        self.wet_flow = deque(maxlen=max_points)
        self.dry_setpoint = deque(maxlen=max_points)
        self.wet_setpoint = deque(maxlen=max_points)
        self.ambient_temp = deque(maxlen=max_points)
        self.dewpoint_temp = deque(maxlen=max_points)
        self.relative_humidity = deque(maxlen=max_points)

        # Create figure and subplots
        self.fig, self.axes = plt.subplots(3, 1, figsize=(12, 10))
        self.fig.suptitle(
            "N-SIM Microscope Environmental Control", fontsize=14, fontweight="bold"
        )

        # Store line objects for efficient updates
        self._lines = {}

        # Configure subplots
        self._setup_plots()

        # Animation object (will be set when started)
        self.animation: Optional[FuncAnimation] = None
        self.is_running = False

    def _setup_plots(self):
        """Configure the plot layouts and initialize line objects"""
        # Plot 1: Flow rates
        self._lines['dry_actual'], = self.axes[0].plot([], [], "b-", linewidth=2, label="Dry Air (Actual)")
        self._lines['dry_setpoint'], = self.axes[0].plot([], [], "b--", linewidth=1, alpha=0.7, label="Dry Air (Setpoint)")
        self._lines['wet_actual'], = self.axes[0].plot([], [], "r-", linewidth=2, label="Wet Air (Actual)")
        self._lines['wet_setpoint'], = self.axes[0].plot([], [], "r--", linewidth=1, alpha=0.7, label="Wet Air (Setpoint)")
        
        self.axes[0].set_title("Mass Flow Controllers", fontweight="bold")
        self.axes[0].set_ylabel("Flow Rate (ml/min)")
        self.axes[0].grid(True, alpha=0.3)
        self.axes[0].legend(loc="upper right")

        # Plot 2: Temperature
        self._lines['ambient'], = self.axes[1].plot([], [], "g-", linewidth=2, label="Ambient")
        self._lines['dewpoint'], = self.axes[1].plot([], [], "c-", linewidth=2, label="Dewpoint")
        
        self.axes[1].set_title("Temperature Measurements", fontweight="bold")
        self.axes[1].set_ylabel("Temperature (°C)")
        self.axes[1].grid(True, alpha=0.3)
        self.axes[1].legend(loc="upper right")

        # Plot 3: Humidity
        self._lines['rh'], = self.axes[2].plot([], [], "m-", linewidth=2, label="RH")
        
        self.axes[2].set_title("Relative Humidity", fontweight="bold")
        self.axes[2].set_ylabel("Humidity (%)")
        self.axes[2].set_xlabel("Time")
        self.axes[2].grid(True, alpha=0.3)
        self.axes[2].legend(loc="upper right")

        # Format x-axis for time display
        for ax in self.axes:
            ax.xaxis.set_major_formatter(DateFormatter("%H:%M:%S"))
            plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right")

        plt.tight_layout()

    def add_data_point(self, data: Dict[str, Optional[float]]):
        # Add timestamp
        if "timestamp" not in data:
            timestamp = datetime.now()
        else:
            timestamp = (
                datetime.fromisoformat(data["timestamp"])
                if isinstance(data["timestamp"], str)
                else data["timestamp"]
            )

        self.timestamps.append(timestamp)

        # Add flow data
        self.dry_flow.append(data.get("dry_flow", np.nan))
        self.wet_flow.append(data.get("wet_flow", np.nan))
        self.dry_setpoint.append(data.get("dry_setpoint", np.nan))
        self.wet_setpoint.append(data.get("wet_setpoint", np.nan))

        # Add environmental data
        self.ambient_temp.append(data.get("ambient_temp", np.nan))
        self.dewpoint_temp.append(data.get("dewpoint_temp", np.nan))
        self.relative_humidity.append(data.get("relative_humidity", np.nan))

    def update_plots(self, frame):
        if len(self.timestamps) == 0:
            return

        # Convert timestamps to numpy array once for efficiency
        time_data = np.array(mdates.date2num(list(self.timestamps)))

        # Update line data efficiently without clearing axes
        if len(time_data) > 0:
            # Convert deques to numpy arrays once
            dry_flow_data = np.array(list(self.dry_flow))
            dry_setpoint_data = np.array(list(self.dry_setpoint))
            wet_flow_data = np.array(list(self.wet_flow))
            wet_setpoint_data = np.array(list(self.wet_setpoint))
            ambient_temp_data = np.array(list(self.ambient_temp))
            dewpoint_temp_data = np.array(list(self.dewpoint_temp))
            rh_data = np.array(list(self.relative_humidity))
            
            # Update flow rate lines
            self._lines['dry_actual'].set_data(time_data, dry_flow_data)
            self._lines['dry_setpoint'].set_data(time_data, dry_setpoint_data)
            self._lines['wet_actual'].set_data(time_data, wet_flow_data)
            self._lines['wet_setpoint'].set_data(time_data, wet_setpoint_data)
            
            # Update temperature lines
            self._lines['ambient'].set_data(time_data, ambient_temp_data)
            self._lines['dewpoint'].set_data(time_data, dewpoint_temp_data)
            
            # Update humidity line
            self._lines['rh'].set_data(time_data, rh_data)

        # Rescale axes to fit data
        for ax in self.axes:
            ax.relim()
            ax.autoscale_view()

        # Redraw canvas
        self.fig.canvas.draw_idle()

    def start(self, data_source_callback=None):
        self.is_running = True

        if data_source_callback:

            def update_with_data(frame):
                new_data = data_source_callback()
                if new_data:
                    self.add_data_point(new_data)
                self.update_plots(frame)

            self.animation = FuncAnimation(
                self.fig,
                update_with_data,
                interval=self.update_interval,
                blit=False,
                cache_frame_data=False,
            )
        else:
            self.animation = FuncAnimation(
                self.fig,
                self.update_plots,
                interval=self.update_interval,
                blit=False,
                cache_frame_data=False,
            )

        plt.show(block=False)
        plt.pause(0.1)

    def stop(self):
        self.is_running = False
        if self.animation:
            self.animation.event_source.stop()

    def show(self):
        plt.show()

    def save_figure(self, filename: str):
        self.fig.savefig(filename, dpi=150, bbox_inches="tight")
        print(f"Plot saved to {filename}")
