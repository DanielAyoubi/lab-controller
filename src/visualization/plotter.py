"""
Dynamic Plotter for N-SIM Microscope System

This module provides real-time plotting of sensor data.
"""

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.dates import DateFormatter
import matplotlib.dates as mdates
from datetime import datetime
from collections import deque
from typing import Dict, List, Optional
import numpy as np


class DynamicPlotter:
    """Real-time plotting of sensor data"""
    
    def __init__(self, max_points: int = 500, update_interval: int = 1000):
        """
        Initialize the dynamic plotter.
        
        Args:
            max_points: Maximum number of data points to display
            update_interval: Update interval in milliseconds
        """
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
        self.fig.suptitle('N-SIM Microscope Environmental Control', fontsize=14, fontweight='bold')
        
        # Configure subplots
        self._setup_plots()
        
        # Animation object (will be set when started)
        self.animation: Optional[FuncAnimation] = None
        self.is_running = False
        
    def _setup_plots(self):
        """Configure the plot layouts"""
        # Plot 1: Flow rates
        self.axes[0].set_title('Mass Flow Controllers', fontweight='bold')
        self.axes[0].set_ylabel('Flow Rate (ml/min)')
        self.axes[0].grid(True, alpha=0.3)
        self.axes[0].legend(['Dry Air (Actual)', 'Dry Air (Setpoint)', 
                            'Wet Air (Actual)', 'Wet Air (Setpoint)'], 
                           loc='upper right')
        
        # Plot 2: Temperature
        self.axes[1].set_title('Temperature Measurements', fontweight='bold')
        self.axes[1].set_ylabel('Temperature (°C)')
        self.axes[1].grid(True, alpha=0.3)
        self.axes[1].legend(['Ambient', 'Dewpoint'], loc='upper right')
        
        # Plot 3: Humidity
        self.axes[2].set_title('Relative Humidity', fontweight='bold')
        self.axes[2].set_ylabel('Humidity (%)')
        self.axes[2].set_xlabel('Time')
        self.axes[2].grid(True, alpha=0.3)
        self.axes[2].legend(['RH'], loc='upper right')
        
        # Format x-axis for time display
        for ax in self.axes:
            ax.xaxis.set_major_formatter(DateFormatter('%H:%M:%S'))
            plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
        
        plt.tight_layout()
    
    def add_data_point(self, data: Dict[str, float]):
        """
        Add a new data point to the plot.
        
        Args:
            data: Dictionary containing sensor readings
        """
        # Add timestamp
        if 'timestamp' not in data:
            timestamp = datetime.now()
        else:
            timestamp = datetime.fromisoformat(data['timestamp']) if isinstance(data['timestamp'], str) else data['timestamp']
        
        self.timestamps.append(timestamp)
        
        # Add flow data
        self.dry_flow.append(data.get('dry_flow', np.nan))
        self.wet_flow.append(data.get('wet_flow', np.nan))
        self.dry_setpoint.append(data.get('dry_setpoint', np.nan))
        self.wet_setpoint.append(data.get('wet_setpoint', np.nan))
        
        # Add environmental data
        self.ambient_temp.append(data.get('ambient_temp', np.nan))
        self.dewpoint_temp.append(data.get('dewpoint_temp', np.nan))
        self.relative_humidity.append(data.get('relative_humidity', np.nan))
    
    def update_plots(self, frame):
        """
        Update the plots (called by FuncAnimation).
        
        Args:
            frame: Frame number (unused, required by FuncAnimation)
        """
        if len(self.timestamps) == 0:
            return
        
        # Clear axes
        for ax in self.axes:
            ax.clear()
        
        # Convert timestamps to matplotlib dates
        time_data = mdates.date2num(list(self.timestamps))
        
        # Plot 1: Flow rates
        if len(time_data) > 0:
            self.axes[0].plot(time_data, list(self.dry_flow), 'b-', linewidth=2, label='Dry Air (Actual)')
            self.axes[0].plot(time_data, list(self.dry_setpoint), 'b--', linewidth=1, alpha=0.7, label='Dry Air (Setpoint)')
            self.axes[0].plot(time_data, list(self.wet_flow), 'r-', linewidth=2, label='Wet Air (Actual)')
            self.axes[0].plot(time_data, list(self.wet_setpoint), 'r--', linewidth=1, alpha=0.7, label='Wet Air (Setpoint)')
        
        self.axes[0].set_title('Mass Flow Controllers', fontweight='bold')
        self.axes[0].set_ylabel('Flow Rate (ml/min)')
        self.axes[0].grid(True, alpha=0.3)
        self.axes[0].legend(loc='upper right')
        
        # Plot 2: Temperature
        if len(time_data) > 0:
            self.axes[1].plot(time_data, list(self.ambient_temp), 'g-', linewidth=2, label='Ambient')
            self.axes[1].plot(time_data, list(self.dewpoint_temp), 'c-', linewidth=2, label='Dewpoint')
        
        self.axes[1].set_title('Temperature Measurements', fontweight='bold')
        self.axes[1].set_ylabel('Temperature (°C)')
        self.axes[1].grid(True, alpha=0.3)
        self.axes[1].legend(loc='upper right')
        
        # Plot 3: Humidity
        if len(time_data) > 0:
            self.axes[2].plot(time_data, list(self.relative_humidity), 'm-', linewidth=2, label='RH')
        
        self.axes[2].set_title('Relative Humidity', fontweight='bold')
        self.axes[2].set_ylabel('Humidity (%)')
        self.axes[2].set_xlabel('Time')
        self.axes[2].grid(True, alpha=0.3)
        self.axes[2].legend(loc='upper right')
        
        # Format x-axis
        for ax in self.axes:
            ax.xaxis.set_major_formatter(DateFormatter('%H:%M:%S'))
            plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')
        
        plt.tight_layout()
    
    def start(self, data_source_callback=None):
        """
        Start the dynamic plotting.
        
        Args:
            data_source_callback: Optional callback function to fetch new data
        """
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
                cache_frame_data=False
            )
        else:
            self.animation = FuncAnimation(
                self.fig,
                self.update_plots,
                interval=self.update_interval,
                blit=False,
                cache_frame_data=False
            )
        
        plt.show(block=False)
        plt.pause(0.1)
    
    def stop(self):
        """Stop the dynamic plotting"""
        self.is_running = False
        if self.animation:
            self.animation.event_source.stop()
    
    def show(self):
        """Display the plot window"""
        plt.show()
    
    def save_figure(self, filename: str):
        """
        Save the current plot to a file.
        
        Args:
            filename: Output filename
        """
        self.fig.savefig(filename, dpi=150, bbox_inches='tight')
        print(f"Plot saved to {filename}")
