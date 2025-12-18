import time
from datetime import datetime
import sys
import os
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

# Add the current directory to the path so we can import src
sys.path.append(os.getcwd())

from config import CONFIG
from src.devices.controller import Controller

def plot_results(filename):
    if not filename or not os.path.exists(filename):
        print("No log file to plot.")
        return

    try:
        print(f"Plotting results from {filename}...")
        df = pd.read_csv(filename)
        
        plt.figure(figsize=(10, 6))
        
        # Plot RH vs Wet Flow
        # We use scatter plot because we have many points per setpoint
        plt.scatter(df['wet_flow_setpoint'], df['rh_device'], alpha=0.5, label='Measured RH (Ambient)')
        plt.scatter(df['wet_flow_setpoint'], df['rh_chiller'], alpha=0.5, label='Measured RH (Chiller)', color='orange')
        
        # Calculate and plot trendlines
        # Dataset 1: Ambient
        mask1 = df['rh_device'].notna() & df['wet_flow_setpoint'].notna()
        if mask1.any():
            x1 = df.loc[mask1, 'wet_flow_setpoint']
            y1 = df.loc[mask1, 'rh_device']
            z1 = np.polyfit(x1, y1, 1)
            p1 = np.poly1d(z1)
            # Sort x for line plotting
            x_plot = np.sort(x1.unique())
            plt.plot(x_plot, p1(x_plot), "--", color='blue', alpha=0.8, label=f'Fit (Ambient): y={z1[0]:.2f}x+{z1[1]:.2f}')

        # Dataset 2: Chiller
        mask2 = df['rh_chiller'].notna() & df['wet_flow_setpoint'].notna()
        if mask2.any():
            x2 = df.loc[mask2, 'wet_flow_setpoint']
            y2 = df.loc[mask2, 'rh_chiller']
            z2 = np.polyfit(x2, y2, 1)
            p2 = np.poly1d(z2)
            # Sort x for line plotting
            x_plot = np.sort(x2.unique())
            plt.plot(x_plot, p2(x_plot), "--", color='red', alpha=0.8, label=f'Fit (Chiller): y={z2[0]:.2f}x+{z2[1]:.2f}')

        plt.xlabel('Wet Flow Setpoint (L/min)')
        plt.ylabel('Relative Humidity (%)')
        plt.title('Calibration: RH vs Wet Flow (Total Flow = 2 L/min)')
        plt.grid(True)
        plt.legend()
        
        # Save plot
        plot_filename = filename.replace('.csv', '.png')
        plt.savefig(plot_filename)
        print(f"Plot saved to {plot_filename}")
        
        # Show plot
        plt.show()
        
    except Exception as e:
        print(f"Error creating plot: {e}")

def main():
    # Initialize controller
    print("Initializing controller...")
    controller = Controller(CONFIG)
    
    # Connect devices
    if not controller.connect_devices():
        print("Failed to connect to all devices. Exiting.")
        return

    # Check required devices
    if not (controller.dry_mfc and controller.wet_mfc and controller.hygrometer and controller.chiller):
        print("Error: All devices (Dry MFC, Wet MFC, Hygrometer, Chiller) must be connected for this calibration.")
        return

    # Set chiller target temperature
    chiller_target_temp = 20.0
    print(f"Setting chiller to {chiller_target_temp} C...")
    controller.chiller.set_setpoint_temperature(chiller_target_temp)
    controller.chiller.start_control()

    # Start logging
    print("Starting data logger...")
    controller.log_fields.append('rh_chiller')
    controller.logger.start_new_log(controller.log_fields)
    log_filename = controller.logger.get_current_filename()
    
    # Calibration parameters
    total_flow = 1.0  # L/min
    step_duration = 1 * 60  # 1 minutes in seconds
    wet_flow_start = total_flow
    wet_flow_increment = 0.2
    
    # Calculate number of steps
    # We want to go from total_flow down to 0. 
    # Since we use floats, let's be careful with the loop condition.
    
    current_wet_flow = wet_flow_start
    
    try:
        while current_wet_flow >= -0.001: # -0.001 for float comparison safety
            current_dry_flow = total_flow - current_wet_flow
            
            # Ensure we don't set negative flow due to float errors
            if current_dry_flow < 0:
                current_dry_flow = 0.0
            
            print(f"\n--- Step: Wet Flow = {current_wet_flow:.2f} L/min, Dry Flow = {current_dry_flow:.2f} L/min ---")
            
            # Set flows
            if controller.dry_mfc:
                controller.dry_mfc.set_flow(current_dry_flow)
            if controller.wet_mfc:
                controller.wet_mfc.set_flow(current_wet_flow)
                
            # Wait for flow stabilization
            print("Waiting 60 seconds for flow stabilization...")
            time.sleep(60)

            # Wait for step duration, logging periodically
            start_time = time.time()
            while time.time() - start_time < step_duration:
                # Collect data
                data = {
                    'timestamp': datetime.now().isoformat(),
                    'dry_flow_setpoint': current_dry_flow,
                    'wet_flow_setpoint': current_wet_flow,
                    'chiller_setpoint': chiller_target_temp,
                }
                
                # Read Dry MFC
                if controller.dry_mfc:
                    status = controller.dry_mfc.get_status()
                    data['dry_flow'] = status.get('flow', 0.0)
                else:
                    data['dry_flow'] = 0.0
                    
                # Read Wet MFC
                if controller.wet_mfc:
                    status = controller.wet_mfc.get_status()
                    data['wet_flow'] = status.get('flow', 0.0)
                else:
                    data['wet_flow'] = 0.0
                    
                # Read Hygrometer
                if controller.hygrometer:
                    readings = controller.hygrometer.get_readings()
                    if readings:
                        data['dewpoint_temp'] = readings.get('dewpoint_temp')
                        data['ambient_temp'] = readings.get('ambient_temp')
                        data['rh_device'] = readings.get('relative_humidity_device')
                        data['relative_humidity'] = readings.get('relative_humidity_calculated')
                    else:
                        # Fill with None or 0 if read failed
                        data['dewpoint_temp'] = None
                        data['ambient_temp'] = None
                        data['rh_device'] = None
                        data['relative_humidity'] = None
                else:
                    data['dewpoint_temp'] = None
                    data['ambient_temp'] = None
                    data['rh_device'] = None
                    data['relative_humidity'] = None

                # Read Chiller (if available)
                if controller.chiller:
                    try:
                        temp_str = controller.chiller.get_internal_temperature()
                        if temp_str:
                            data['chiller_temp'] = float(temp_str)
                        else:
                            data['chiller_temp'] = None
                    except Exception as e:
                        # print(f"Error reading chiller: {e}")
                        data['chiller_temp'] = None
                else:
                    data['chiller_temp'] = None

                # Calculate RH from Chiller Temp
                if data['chiller_temp'] is not None and data['dewpoint_temp'] is not None:
                    data['rh_chiller'] = controller.hygrometer.compute_relative_humidity(data['dewpoint_temp'], data['chiller_temp'])
                else:
                    data['rh_chiller'] = None

                # Read Thermocouple
                if controller.t_probe:
                    try:
                        data['cell_temp'] = controller.t_probe.get_temperature()
                    except Exception as e:
                        # print(f"Error reading thermocouple: {e}")
                        data['cell_temp'] = None
                else:
                    data['cell_temp'] = None

                # Log data
                controller.logger.log_data(data)
                
                # Print status update every 10 seconds
                if int(time.time()) % 10 == 0:
                     print(f"Logged data point. RH: {data.get('rh_device')} % (Ambient), {data.get('rh_chiller')} % (Chiller)")

                # Sleep for a bit (e.g. 2 seconds)
                time.sleep(2)
            
            # Decrement wet flow
            current_wet_flow -= wet_flow_increment

    except KeyboardInterrupt:
        print("\nCalibration interrupted by user.")
    finally:
        print("Stopping flows...")
        if controller.dry_mfc:
            controller.dry_mfc.set_flow(0.0)
        if controller.wet_mfc:
            controller.wet_mfc.set_flow(0.0)
        if controller.chiller:
            controller.chiller.stop_control()
        
        controller.logger.close()
        print("Done.")

        # Plot results
        if log_filename:
            plot_results(log_filename)

if __name__ == "__main__":
    main()
