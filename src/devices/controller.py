import time
from datetime import datetime
from typing import Optional, Dict, Tuple

from src.devices.vogtlin_mfc import VogtlinMFC
from src.devices.dewmaster import DewMaster
from src.devices.thermocouple import Thermocouple
from src.logging.data_logger import DataLogger
from src.visualization.plotter import DynamicPlotter


class Controller:
    def __init__(self, config: Dict):
        self.config = config
        self.running = False
        
        # Initialize devices
        self.dry_mfc: Optional[VogtlinMFC] = None
        self.wet_mfc: Optional[VogtlinMFC] = None
        self.hygrometer: Optional[DewMaster] = None
        self.t_probe: Optional[Thermocouple] = None
        # self.chiller: Optional[Chiller] = None
        
        # Initialize logger
        self.logger = DataLogger(
            output_dir=config.get('log_dir', 'data'),
            filename_prefix=config.get('log_prefix', 'nsim_log')
        )
        
        # Initialize plotter
        self.plotter = DynamicPlotter(
            max_points=config.get('max_plot_points', 500),
            update_interval=config.get('plot_update_interval', 1000)
        )
        
        # Data fields for logging - collect all possible data
        self.log_fields = [
            'timestamp',
            'dry_flow',
            'wet_flow', 
            'dry_flow_setpoint',
            'wet_flow_setpoint',
            'cell_temp',
            'ambient_temp',
            'dewpoint_temp',
            'relative_humidity_device',      # RH reading directly from DewMaster
            'relative_humidity_calculated',  # RH calculated from dewpoint + ambient temp
            'relative_humidity_cell_calc',   # RH calculated from dewpoint + cell temp
            'relative_humidity_control'      # The RH value actually used for control
        ]
        
    def connect_devices(self) -> bool:
        success = True
        
        # Connect dry air MFC
        if self.config.get('dry_mfc_enabled', True) and 'dry_mfc_port' in self.config:
            print(f"Connecting to Dry Air MFC on {self.config['dry_mfc_port']}...")
            self.dry_mfc = VogtlinMFC(
                port=self.config['dry_mfc_port'],
                address=self.config.get('dry_mfc_address', 1),
                name="Dry Air MFC"
            )
            if not self.dry_mfc.connect():
                print("Failed to connect to Dry Air MFC")
                success = False
            else:
                print("Dry Air MFC connected successfully")
        
        # Connect wet air MFC
        if self.config.get('wet_mfc_enabled', True) and 'wet_mfc_port' in self.config:
            print(f"Connecting to Wet Air MFC on {self.config['wet_mfc_port']}...")
            self.wet_mfc = VogtlinMFC(
                port=self.config['wet_mfc_port'],
                address=self.config.get('wet_mfc_address', 2),
                name="Wet Air MFC"
            )
            if not self.wet_mfc.connect():
                print("Failed to connect to Wet Air MFC")
                success = False
            else:
                print("Wet Air MFC connected successfully")
        
        # Connect hygrometer
        if self.config.get('hygrometer_enabled', True) and 'hygrometer_port' in self.config:
            print(f"Connecting to DewMaster Hygrometer on {self.config['hygrometer_port']}...")
            self.hygrometer = DewMaster(
                port=self.config['hygrometer_port'],
                baudrate=self.config.get('hygrometer_baudrate', 9600)
            )
            if not self.hygrometer.connect():
                print("Failed to connect to DewMaster Hygrometer")
                success = False
            else:
                print("DewMaster Hygrometer connected successfully")

        if self.config.get('t_probe_enabled'):
            vendor_id = self.config.get('t_probe_vendor_id', Thermocouple.DEFAULT_VENDOR_ID)
            product_id = self.config.get('t_probe_product_id', Thermocouple.DEFAULT_PRODUCT_ID)
            print(f"Connecting to Temperature Probe (USB) [VID=0x{vendor_id:04X}, PID=0x{product_id:04X}]...")
            self.t_probe = Thermocouple(
                vendor_id=vendor_id,
                product_id=product_id,
            )
            if not self.t_probe.connect():
                print("Failed to connect to Temperature Probe")
                success = False
            else:
                print("Temperature Probe connected successfully")

        # if self.config.get('chiller_enabled', True) and 'chiller_port' in self.config:
        #     pass
        
        return success
    
    def disconnect_devices(self):
        print("\nDisconnecting devices...")
        
        if self.dry_mfc:
            self.dry_mfc.disconnect()
            print("Dry Air MFC disconnected")
        
        if self.wet_mfc:
            self.wet_mfc.disconnect()
            print("Wet Air MFC disconnected")
        
        if self.hygrometer:
            self.hygrometer.disconnect()
            print("DewMaster Hygrometer disconnected")

        if self.t_probe:
            self.t_probe.disconnect()
            print("Temperature Probe disconnected")
    
    def read_all_sensors(self) -> Dict[str, float]:
        data = {
            'timestamp': datetime.now().isoformat(),
            'dry_flow': None,
            'wet_flow': None,
            'dry_flow_setpoint': None,
            'wet_flow_setpoint': None,
            'cell_temp': None,
            'ambient_temp': None,
            'dewpoint_temp': None,
            'relative_humidity_device': None,
            'relative_humidity_calculated': None,
            'relative_humidity_cell_calc': None,
            'relative_humidity_control': None
        }
        
        # Read dry MFC
        if self.dry_mfc:
            data['dry_flow'] = self.dry_mfc.get_flow()
            data['dry_flow_setpoint'] = self.dry_mfc.get_setpoint()
        
        # Read wet MFC
        if self.wet_mfc:
            data['wet_flow'] = self.wet_mfc.get_flow()
            data['wet_flow_setpoint'] = self.wet_mfc.get_setpoint()
        
        # Read hygrometer
        if self.hygrometer:
            readings = self.hygrometer.get_readings()
            if readings:
                data['ambient_temp'] = readings.get('ambient_temp')
                data['dewpoint_temp'] = readings.get('dewpoint_temp')
                data['relative_humidity_device'] = readings.get('relative_humidity_device')
                data['relative_humidity_calculated'] = readings.get('relative_humidity_calculated')

        # Read thermocouple
        if self.t_probe:
            data['cell_temp'] = self.t_probe.get_temperature()

        # Calculate RH using cell temperature instead of ambient (if available)
        if (
            self.hygrometer and
            data['dewpoint_temp'] is not None and
            data['cell_temp'] is not None
        ):
            data['relative_humidity_cell_calc'] = self.hygrometer.compute_relative_humidity(
                data['dewpoint_temp'], data['cell_temp']
            )
        
        # Determine which RH value to use for control based on configuration
        rh_source = self.config.get('rh_control_source', 'cell_calc')  # Default to calculated from cell temp
        
        if rh_source == 'dewmaster' and data['relative_humidity_device'] is not None:
            data['relative_humidity_control'] = data['relative_humidity_device']
        elif rh_source == 'calculated' and data['relative_humidity_calculated'] is not None:
            data['relative_humidity_control'] = data['relative_humidity_calculated']
        elif rh_source == 'cell_calc' and data['relative_humidity_cell_calc'] is not None:
            data['relative_humidity_control'] = data['relative_humidity_cell_calc']
        else:
            # Fallback hierarchy: cell_calc -> calculated -> device
            if data['relative_humidity_cell_calc'] is not None:
                data['relative_humidity_control'] = data['relative_humidity_cell_calc']
            elif data['relative_humidity_calculated'] is not None:
                data['relative_humidity_control'] = data['relative_humidity_calculated']
            elif data['relative_humidity_device'] is not None:
                data['relative_humidity_control'] = data['relative_humidity_device']
        
        return data
    
    def set_flow_rates(self, dry_flow: Optional[float] = None, wet_flow: Optional[float] = None, 
                       max_flow: Optional[float] = None, timeout: int = 30):
        # Validate total flow doesn't exceed maximum
        if max_flow is not None:
            total = (dry_flow or 0) + (wet_flow or 0)
            if total > max_flow:
                raise ValueError(f"Total flow rate {total:.2f} L/min exceeds maximum {max_flow:.2f} L/min")
        
        if dry_flow is not None and self.dry_mfc:
            if self.dry_mfc.set_flow(dry_flow):
                print(f"Set dry air flow to {dry_flow:.3f} L/min")
            else:
                print("Failed to set dry air flow")
        
        if wet_flow is not None and self.wet_mfc:
            if self.wet_mfc.set_flow(wet_flow):
                print(f"Set wet air flow to {wet_flow:.3f} L/min")
            else:
                print("Failed to set wet air flow")

        if wet_flow is not None and dry_flow is not None:
            print("Letting flow equilibrate...")
            time.sleep(timeout) # Let flow equilibrate
    
    def start_monitoring(self, interval: float = 5.0):
        print(f"\nStarting monitoring with {interval}s interval...")
        print("Press Ctrl+C to stop\n")
        
        # Start logging
        self.logger.start_new_log(self.log_fields)
        print(f"Logging to: {self.logger.get_current_filename()}\n")
        
        # Start plotting
        self.plotter.start(data_source_callback=self.read_all_sensors)
        
        self.running = True
        
        try:
            while self.running:
                data = self.read_all_sensors()
                
                # Log data
                self.logger.log_data(data)
                
                # Add to plotter
                self.plotter.add_data_point(data)
                
                # Display current readings
                print(f"[{data['timestamp']}]")
                
                # Flow rates with setpoints
                if data['dry_flow'] is not None:
                    if data['dry_flow_setpoint'] is not None:
                        print(f"  Dry Air:  {data['dry_flow']:.3f} L/min (SP: {data['dry_flow_setpoint']:.3f})")
                    else:
                        print(f"  Dry Air:  {data['dry_flow']:.3f} L/min")
                        
                if data['wet_flow'] is not None:
                    if data['wet_flow_setpoint'] is not None:
                        print(f"  Wet Air:  {data['wet_flow']:.3f} L/min (SP: {data['wet_flow_setpoint']:.3f})")
                    else:
                        print(f"  Wet Air:  {data['wet_flow']:.3f} L/min")
                
                # Total flow
                total_flow = 0
                if data['dry_flow'] is not None:
                    total_flow += data['dry_flow']
                if data['wet_flow'] is not None:
                    total_flow += data['wet_flow']
                if total_flow > 0:
                    print(f"  Total:    {total_flow:.3f} L/min")
                
                # Temperatures
                temps = []
                if data['cell_temp'] is not None:
                    temps.append(f"Cell: {data['cell_temp']:.2f}°C")
                if data['ambient_temp'] is not None:
                    temps.append(f"Ambient: {data['ambient_temp']:.2f}°C")
                if data['dewpoint_temp'] is not None:
                    temps.append(f"Dewpoint: {data['dewpoint_temp']:.2f}°C")
                if temps:
                    print(f"  Temps:    {' | '.join(temps)}")
                
                # Humidity readings½
                rh_source = self.config.get('rh_control_source', 'cell_calc')
                if data['relative_humidity_control'] is not None:
                    print(f"  RH (Control): {data['relative_humidity_control']:.1f}% [using {rh_source}]")
                
                # Show other RH values for comparison
                other_rh = []
                if data['relative_humidity_device'] is not None and rh_source != 'dewmaster':
                    other_rh.append(f"DewMaster: {data['relative_humidity_device']:.1f}%")
                if data['relative_humidity_calculated'] is not None and rh_source != 'calculated':
                    other_rh.append(f"Calc: {data['relative_humidity_calculated']:.1f}%")
                if data['relative_humidity_cell_calc'] is not None and rh_source != 'cell_calc':
                    other_rh.append(f"Cell: {data['relative_humidity_cell_calc']:.1f}%")
                if other_rh:
                    print(f"  RH (Other):   {' | '.join(other_rh)}")
                
                print()
                
                # Wait for next sample
                time.sleep(interval)
                
        except KeyboardInterrupt:
            print("\n\nMonitoring stopped by user")
        finally:
            self.running = False
            self.plotter.stop()
    
    def calculate_flow_rates_for_rh(self, target_rh: float, total_flow: float) -> Tuple[float, float]:
        # Assumes: Dry air stream is at 0% RH & Wet air stream is at 100% RH (saturated) - Simple mixing model: RH_result ≈ (wet_flow / total_flow) * 100
        
        target_rh = max(0.0, min(100.0, target_rh)) # Clamp target RH to valid range
        
        # Calculate wet flow as fraction of total flow
        wet_flow = (target_rh / 100.0) * total_flow
        dry_flow = total_flow - wet_flow
        
        return dry_flow, wet_flow
    
    def adjust_flows_for_rh(self, target_rh: float, actual_rh: float, 
                            current_dry_flow: float, current_wet_flow: float,
                            max_flow: float, adjustment_factor: float = 0.1) -> Tuple[float, float]:
        # Adjust flow rates to reduce deviation from target RH.
        error = target_rh - actual_rh
        adjustment_factor = adjustment_factor * (1 + (abs(error) / 100.0)) # adjust based on size of error
        
        # Calculate adjustment based on error
        # If actual RH is too low, increase wet flow
        # If actual RH is too high, decrease wet flow
        flow_adjustment = (error / 100.0) * max_flow * adjustment_factor
        
        new_wet_flow = current_wet_flow + flow_adjustment
        new_wet_flow = max(0.0, new_wet_flow)  # Can't go negative
        
        # Calculate new dry flow to maintain target total (max_flow), but allow going below
        new_dry_flow = max_flow - new_wet_flow
        
        # If new dry flow would be negative, adjust both flows proportionally
        if new_dry_flow < 0:
            new_dry_flow = 0
            new_wet_flow = min(max_flow, new_wet_flow) # Clamp wet flow to max_flow
        
        # Ensure total doesn't exceed max_flow
        new_total = new_dry_flow + new_wet_flow
        if new_total > max_flow:
            # Scale down proportionally
            scale = max_flow / new_total
            new_dry_flow *= scale
            new_wet_flow *= scale
        
        return new_dry_flow, new_wet_flow
    
    def stabilize_flows_for_rh(self, target_rh: float, max_flow: float, 
                               stabilization_time: float = 60.0, 
                               stabilization_tolerance: float = 2.0,
                               control_interval: float = 5.0,
                               fallback_tolerance: float = 5.0) -> Tuple[bool, float, float]:
        # Stabilize flow rates to achieve stable RH within tolerance of target.
        print(f"    Stabilizing flows for {target_rh:.1f}% RH (tolerance: ±{stabilization_tolerance:.1f}%)")
        
        # Calculate initial flow rates
        dry_flow, wet_flow = self.calculate_flow_rates_for_rh(target_rh, max_flow)
        
        # Set initial flows
        self.set_flow_rates(dry_flow=dry_flow, wet_flow=wet_flow, max_flow=max_flow)
        time.sleep(5.0)  # Initial settling time
        
        stabilization_start = time.time()
        last_control_time = time.time()
        stable_readings = []  # Track recent RH readings for stability assessment
        max_stable_readings = 5  # Number of readings to consider for stability
        
        print(f"    Initial flows: Dry {dry_flow:.3f}, Wet {wet_flow:.3f} L/min")
        
        while (time.time() - stabilization_start) < stabilization_time:
            current_time = time.time()
            
            # Read current data
            data = self.read_all_sensors()
            actual_rh = data.get('relative_humidity_control')
            
            if actual_rh is None:
                print("    No RH reading available, continuing...")
                time.sleep(1.0)
                continue
            
            # Track RH readings for stability assessment
            stable_readings.append(actual_rh)
            if len(stable_readings) > max_stable_readings:
                stable_readings.pop(0)
            
            elapsed = current_time - stabilization_start
            deviation = abs(actual_rh - target_rh)
            
            print(f"    {elapsed:.1f}s: RH {actual_rh:.1f}% (target {target_rh:.1f}%, dev {deviation:.1f}%)")
            
            # Check if we have enough readings and they're all within tolerance
            if len(stable_readings) >= max_stable_readings:
                all_stable = all(abs(rh - target_rh) <= stabilization_tolerance for rh in stable_readings)
                rh_range = max(stable_readings) - min(stable_readings)
                
                if all_stable and rh_range <= stabilization_tolerance:
                    print(f"    Flows stabilized! RH stable at {actual_rh:.1f}% (range: {rh_range:.1f}%)")
                    final_dry = data.get('dry_flow', dry_flow)
                    final_wet = data.get('wet_flow', wet_flow)
                    return True, final_dry, final_wet
            
            # Adjust flows if needed and enough time has passed
            if (current_time - last_control_time) >= control_interval:
                if deviation > stabilization_tolerance:
                    print(f"    Adjusting flows (deviation {deviation:.1f}% > {stabilization_tolerance:.1f}%)")
                    
                    current_dry = data.get('dry_flow', dry_flow)
                    current_wet = data.get('wet_flow', wet_flow)
                    
                    new_dry, new_wet = self.adjust_flows_for_rh(
                        target_rh=target_rh,
                        actual_rh=actual_rh,
                        current_dry_flow=current_dry,
                        current_wet_flow=current_wet,
                        max_flow=max_flow,
                        adjustment_factor=0.03  # Smaller adjustment for stabilization
                    )
                    
                    self.set_flow_rates(dry_flow=new_dry, wet_flow=new_wet, max_flow=max_flow)
                    dry_flow, wet_flow = new_dry, new_wet
                    
                    # Clear stability readings after adjustment
                    stable_readings.clear()
                    
                last_control_time = current_time
            
            time.sleep(1.0)  # Check every second during stabilization
        
        # Stabilization timeout
        final_dry = data.get('dry_flow', dry_flow) if 'data' in locals() else dry_flow
        final_wet = data.get('wet_flow', wet_flow) if 'data' in locals() else wet_flow
        final_rh = actual_rh if 'actual_rh' in locals() else None
        
        if final_rh is not None:
            final_deviation = abs(final_rh - target_rh)
            if final_deviation <= fallback_tolerance:  # Use broader tolerance for timeout case
                print(f"    Stabilization timeout, but RH {final_rh:.1f}% within control tolerance ({fallback_tolerance:.1f}%)")
                return True, final_dry, final_wet
            else:
                print(f"    Stabilization timeout, RH {final_rh:.1f}% outside tolerance (dev: {final_deviation:.1f}%)")
                return False, final_dry, final_wet
        else:
            print("    Stabilization timeout, no RH reading available")
            return False, final_dry, final_wet
    
    def run_automated_experiment(self, direction: str = 'up', steps: int = 10, 
                                 duration: float = 5.0, max_flow: float = 2.0,
                                 control_interval: float = 5.0, rh_tolerance: float = 5.0,
                                 stabilization_time: float = 60.0, stabilization_tolerance: float = 2.0):
        """
        Run an automated humidity ramp experiment with feedback control.
        System aims to maintain max_flow as total flow but may go below if needed for RH control.
        
        Args:
            direction: 'up' for 0% to 100% RH, 'down' for 100% to 0% RH
            steps: Number of steps between start and end RH
            duration: Total experiment duration in minutes
            max_flow: Maximum/target total flow rate (dry + wet) in L/min
            control_interval: Time between control updates in seconds
            rh_tolerance: Maximum allowed deviation from target RH before adjustment (%)
            stabilization_time: Maximum time to spend stabilizing flows at each step (seconds)
            stabilization_tolerance: RH tolerance for considering flows stable (%)
        """
        if not self.dry_mfc or not self.wet_mfc:
            raise RuntimeError("Both dry and wet MFCs must be connected for automated experiments")
        
        if not self.hygrometer:
            raise RuntimeError("Hygrometer must be connected for automated experiments")
        
        # Convert duration from minutes to seconds for internal calculations
        duration_seconds = duration * 60.0
        step_duration_seconds = duration_seconds / steps
        
        print("\n" + "=" * 60)
        print("Starting Automated Humidity Ramp Experiment")
        print("=" * 60)
        print(f"Direction: {direction.upper()} (0% → 100% RH)" if direction.lower() == 'up' else f"Direction: {direction.upper()} (100% → 0% RH)")
        print(f"Steps: {steps}")
        print(f"Duration: {duration:.1f} minutes ({duration_seconds:.1f} seconds)")
        print(f"Step duration: {step_duration_seconds:.1f} seconds ({step_duration_seconds/60:.2f} minutes)")
        print(f"Target flow rate: {max_flow:.3f} L/min (may go below if needed for RH control)")
        print(f"Control interval: {control_interval:.1f} seconds")
        print(f"RH tolerance: ±{rh_tolerance:.1f}%")
        print(f"Stabilization time: {stabilization_time:.1f} seconds")
        print(f"Stabilization tolerance: ±{stabilization_tolerance:.1f}%")
        print("=" * 60 + "\n")
        
        if direction.lower() == 'up':
            start_rh = 0.0
            end_rh = 100.0
        else:
            start_rh = 100.0
            end_rh = 0.0
        
        # Calculate step size
        rh_step = (end_rh - start_rh) / steps
        
        # Start logging
        self.logger.start_new_log(self.log_fields)
        print(f"Logging to: {self.logger.get_current_filename()}\n")
        
        # Start plotting
        self.plotter.start(data_source_callback=self.read_all_sensors)
        
        self.running = True
        
        try:
            for step in range(steps + 1):
                target_rh = start_rh + (step * rh_step) # Calculate target RH for this step
                
                target_rh = max(0.0, min(100.0, target_rh)) # Clamp to valid range
                
                print(f"\n--- Step {step}/{steps} ---")
                print(f"Target RH: {target_rh:.1f}%")
                
                # Stabilize flows for this target RH
                stabilization_success, dry_flow, wet_flow = self.stabilize_flows_for_rh(
                    target_rh=target_rh,
                    max_flow=max_flow,
                    stabilization_time=stabilization_time,
                    stabilization_tolerance=stabilization_tolerance,
                    control_interval=control_interval,
                    fallback_tolerance=rh_tolerance
                )
                
                if not stabilization_success:
                    print(f"    Warning: Could not fully stabilize flows for step {step}")
                    print(f"    Proceeding with current flows: Dry {dry_flow:.3f}, Wet {wet_flow:.3f} L/min")
                else:
                    print(f"    Flows stabilized for step {step}!")
                
                print(f"\nStarting data collection phase for step {step}...")
                time.sleep(1.0)  # Brief pause before data collection
                
                # Data collection loop for this step (flows should already be stable)
                step_start_time = time.time()
                last_control_time = time.time()
                
                while (time.time() - step_start_time) < step_duration_seconds and self.running:
                    current_time = time.time()
                    
                    # Read sensors
                    data = self.read_all_sensors()

                    # Log data
                    self.logger.log_data(data)
                    
                    # Add to plotter
                    self.plotter.add_data_point(data)
                    
                    actual_rh = data.get('relative_humidity_control')
                    
                    # Periodic status update
                    if (current_time - last_control_time) >= control_interval and actual_rh is not None:
                        deviation = abs(actual_rh - target_rh)
                        
                        elapsed_min = (current_time - step_start_time) / 60.0
                        step_duration_min = step_duration_seconds / 60.0
                        cell_temp = data.get('cell_temp')
                        ambient_temp = data.get('ambient_temp')
                        dewpoint_temp = data.get('dewpoint_temp')

                        print(f"  Time: {elapsed_min:.2f} min / {step_duration_min:.2f} min ({current_time - step_start_time:.1f}s / {step_duration_seconds:.1f}s)")
                        print(f"  Target RH: {target_rh:.1f}% | Actual RH: {actual_rh:.1f}% | Deviation: {deviation:.1f}%")
                        
                        # Flow information
                        dry_flow_current = data.get('dry_flow', 0)
                        wet_flow_current = data.get('wet_flow', 0)
                        total_flow = dry_flow_current + wet_flow_current
                        print(f"  Flows: Dry {dry_flow_current:.3f} | Wet {wet_flow_current:.3f} | Total {total_flow:.3f} L/min")

                        # Temperature information
                        temps_parts = []
                        if cell_temp is not None:
                            temps_parts.append(f"Cell: {cell_temp:.2f}°C")
                        if ambient_temp is not None:
                            temps_parts.append(f"Ambient: {ambient_temp:.2f}°C")
                        if dewpoint_temp is not None:
                            temps_parts.append(f"Dewpoint: {dewpoint_temp:.2f}°C")
                        if temps_parts:
                            print(f"  Temps: {' | '.join(temps_parts)}")
                        
                        # RH comparison information
                        rh_source = self.config.get('rh_control_source', 'cell_calc')
                        rh_parts = [f"Control ({rh_source}): {actual_rh:.1f}%"]
                        if data.get('relative_humidity_device') is not None and rh_source != 'device':
                            rh_parts.append(f"Device: {data['relative_humidity_device']:.1f}%")
                        if data.get('relative_humidity_calculated') is not None and rh_source != 'calculated':
                            rh_parts.append(f"Calc: {data['relative_humidity_calculated']:.1f}%")
                        if data.get('relative_humidity_cell_calc') is not None and rh_source != 'cell_calc':
                            rh_parts.append(f"Cell: {data['relative_humidity_cell_calc']:.1f}%")
                        print(f"  RH: {' | '.join(rh_parts)}")
                        
                        # Only make major adjustments if deviation is very large (flows should be stable)
                        if deviation > rh_tolerance * 2:  # Only adjust if deviation is 2x the tolerance
                            print(f"  ⚠ Large deviation {deviation:.1f}% (>{rh_tolerance*2:.1f}%) - Making corrective adjustment...")
                            
                            current_dry = data.get('dry_flow', dry_flow)
                            current_wet = data.get('wet_flow', wet_flow)
                            
                            new_dry, new_wet = self.adjust_flows_for_rh(
                                target_rh=target_rh,
                                actual_rh=actual_rh,
                                current_dry_flow=current_dry,
                                current_wet_flow=current_wet,
                                max_flow=max_flow,
                                adjustment_factor=0.02  # Smaller adjustment during data collection
                            )
                            
                            self.set_flow_rates(dry_flow=new_dry, wet_flow=new_wet, max_flow=max_flow)
                            dry_flow, wet_flow = new_dry, new_wet
                            time.sleep(1.0)
                        elif deviation <= rh_tolerance:
                            print("  ✅ Within tolerance - flows stable")
                        else:
                            print(f"  Minor deviation {deviation:.1f}% - maintaining current flows")
                        
                        last_control_time = current_time
                        print()
                    
                    time.sleep(1)
                
                if not self.running:
                    break
                
                print(f"Step {step} complete\n")
            
            print("\n" + "=" * 60)
            print("Experiment Complete!")
            print("=" * 60)
            
        except KeyboardInterrupt:
            print("\n\nExperiment stopped by user")
        finally:
            self.running = False
            self.plotter.stop()
    
    def stop(self):
        self.running = False
        self.disconnect_devices()

    def warn_if_temp_delta(self, data: Dict[str, Optional[float]]):
        cell_temp = data.get('cell_temp')
        ambient_temp = data.get('ambient_temp')
        if cell_temp is None or ambient_temp is None:
            return
        delta = abs(cell_temp - ambient_temp)
        if delta > 5:
            print(f"  ⚠ Warning: Cell vs Ambient temperature differs by {delta:.2f} °C")
