import time
from datetime import datetime
from typing import Optional, Dict, Tuple, Callable

from src.devices.vogtlin_mfc import VogtlinMFC
from src.devices.dewmaster import DewMaster
from src.devices.thermocouple import Thermocouple
from src.logging.data_logger import DataLogger
from src.visualization.plotter import DynamicPlotter


class Controller:
    def __init__(self, config: Dict, enable_plotter: bool = True):
        self.config = config
        self.running = False
        
        # Initialize devices
        self.dry_mfc: Optional[VogtlinMFC] = None
        self.wet_mfc: Optional[VogtlinMFC] = None
        self.hygrometer: Optional[DewMaster] = None
        self.t_probe: Optional[Thermocouple] = None
        
        # Initialize logger
        self.logger = DataLogger(
            output_dir=config.get('log_dir', 'data'),
            filename_prefix=config.get('log_prefix', 'nsim_log')
        )
        
        # Initialize plotter
        self.plotter = None
        if enable_plotter:
            self.plotter = DynamicPlotter(
                max_points=config.get('max_plot_points', 500),
                update_interval=config.get('plot_update_interval', 1000)
            )
        
        # Data fields for logging
        self.log_fields = [
            'timestamp',
            'dry_flow', 'wet_flow', 
            'dry_flow_setpoint', 'wet_flow_setpoint',
            'cell_temp', 'ambient_temp', 'dewpoint_temp',
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

        # Connect Temperature Probe
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
    
    def read_all_sensors(self) -> Dict[str, Optional[float]]:
        data = {
            'timestamp': datetime.now().isoformat(),
            'dry_flow': None, 'wet_flow': None,
            'dry_flow_setpoint': None, 'wet_flow_setpoint': None,
            'cell_temp': None, 'ambient_temp': None, 'dewpoint_temp': None,
            'relative_humidity_device': None, 'relative_humidity_calculated': None,
            'relative_humidity_cell_calc': None, 'relative_humidity_control': None
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
        data['relative_humidity_control'] = self._select_rh_for_control(data)
        
        return data
    
    def _select_rh_for_control(self, data: Dict[str, Optional[float]]) -> Optional[float]:
        """
        Select the appropriate RH value for control based on configuration.
        
        Args:
            data: Dictionary containing RH readings
            
        Returns:
            Selected RH value or None if unavailable
        """
        rh_source = self.config.get('rh_control_source', 'cell_calc')
        
        # Map of source names to data keys
        rh_sources = {
            'dewmaster': 'relative_humidity_device',
            'calculated': 'relative_humidity_calculated',
            'cell_calc': 'relative_humidity_cell_calc'
        }
        
        # Try configured source first
        if rh_source in rh_sources:
            value = data.get(rh_sources[rh_source])
            if value is not None:
                return value
        
        # Fallback hierarchy: cell_calc -> calculated -> device
        for fallback_key in ['relative_humidity_cell_calc', 'relative_humidity_calculated', 'relative_humidity_device']:
            value = data.get(fallback_key)
            if value is not None:
                return value
        
        return None
    
    def set_flow_rates(self, dry_flow: Optional[float] = None, wet_flow: Optional[float] = None, 
                       max_flow: Optional[float] = None):
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
    
    def start_monitoring(self, interval: float = 5.0):
        print(f"\nStarting monitoring with {interval}s interval...")
        print("Press Ctrl+C to stop\n")
        
        # Start logging
        self.logger.start_new_log(self.log_fields)
        print(f"Logging to: {self.logger.get_current_filename()}\n")
        
        # Start plotting
        if self.plotter:
            self.plotter.start(data_source_callback=self.read_all_sensors)
        
        self.running = True
        
        try:
            while self.running:
                data = self.read_all_sensors()
                
                # Log data
                self.logger.log_data(data)
                
                # Add to plotter
                if self.plotter:
                    self.plotter.add_data_point(data)
                
                # Display current readings
                print(f"[{data['timestamp']}]")
                
                # Flow rates
                if data['dry_flow'] is not None:
                    sp_str = f" (SP: {data['dry_flow_setpoint']:.3f})" if data['dry_flow_setpoint'] is not None else ""
                    print(f"  Dry Air:  {data['dry_flow']:.3f} L/min{sp_str}")
                        
                if data['wet_flow'] is not None:
                    sp_str = f" (SP: {data['wet_flow_setpoint']:.3f})" if data['wet_flow_setpoint'] is not None else ""
                    print(f"  Wet Air:  {data['wet_flow']:.3f} L/min{sp_str}")
                
                # Total flow
                total_flow = (data['dry_flow'] or 0) + (data['wet_flow'] or 0)
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
                
                # Humidity readings
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
                time.sleep(interval)
                
        except KeyboardInterrupt:
            print("\n\nMonitoring stopped by user")
        finally:
            self.running = False
            if self.plotter:
                self.plotter.stop()
    
    def calculate_flow_rates_for_rh(self, target_rh: float, total_flow: float) -> Tuple[float, float]:
        # Assumes: Dry air stream is at 0% RH & Wet air stream is at 100% RH (saturated)
        target_rh = max(0.0, min(100.0, target_rh))
        wet_flow = (target_rh / 100.0) * total_flow
        dry_flow = total_flow - wet_flow
        return dry_flow, wet_flow
    
    def adjust_flows_for_rh(self, target_rh: float, actual_rh: float, 
                            current_dry_flow: float, current_wet_flow: float,
                            max_flow: float, adjustment_factor: float = 0.1) -> Tuple[float, float]:
        # Adjust flow rates to reduce deviation from target RH.
        error = target_rh - actual_rh
        adjustment_factor = adjustment_factor * (1 + (abs(error) / 100.0))
        
        flow_adjustment = (error / 100.0) * max_flow * adjustment_factor
        
        new_wet_flow = max(0.0, current_wet_flow + flow_adjustment)
        new_dry_flow = max_flow - new_wet_flow
        
        if new_dry_flow < 0:
            new_dry_flow = 0
            new_wet_flow = min(max_flow, new_wet_flow)
        
        # Ensure total doesn't exceed max_flow
        new_total = new_dry_flow + new_wet_flow
        if new_total > max_flow:
            scale = max_flow / new_total
            new_dry_flow *= scale
            new_wet_flow *= scale
        
        return new_dry_flow, new_wet_flow
    
    def _wait_and_log(self, duration: float, on_data: Optional[Callable[[Dict], None]] = None) -> Dict:
        start_time = time.time()
        last_data = {}
        
        while (time.time() - start_time) < duration and self.running:
            cycle_start = time.time()
            
            # Read sensors (this waits for devices)
            last_data = self.read_all_sensors()
            
            # Log and Plot
            self.logger.log_data(last_data)
            if self.plotter:
                self.plotter.add_data_point(last_data)
            
            # Callback
            if on_data:
                on_data(last_data)
            
            # Wait to ensure 1s interval
            elapsed = time.time() - cycle_start
            if elapsed < 1.0:
                time.sleep(1.0 - elapsed)
                
        return last_data

    def stabilize_flows_for_rh(self, target_rh: float, max_flow: float, 
                               on_data: Optional[Callable[[Dict], None]] = None, stabilization_tolerance: float = 2.0) -> Tuple[bool, float, float]:
        # Stabilize flow rates to achieve stable RH within tolerance of target.
        print(f"    Stabilizing flows for {target_rh:.1f}% RH")
        
        # 1. Calculate initial flows
        dry_flow, wet_flow = self.calculate_flow_rates_for_rh(target_rh, max_flow)
        
        # 2. Ramp to flows (Gradual, >2s steps)
        current_dry = 0.0
        current_wet = 0.0
        if self.dry_mfc:
            try:
                current_dry = self.dry_mfc.get_setpoint()
            except Exception:
                pass
        if self.wet_mfc:
            try:
                current_wet = self.wet_mfc.get_setpoint()
            except Exception:
                pass
            
        steps = 10 
        step_interval = 5.0 
        
        print(f"    Ramping flows to Dry: {dry_flow:.3f}, Wet: {wet_flow:.3f}...")
        for i in range(steps):
            if not self.running:
                return False, current_dry, current_wet
            
            fraction = (i + 1) / steps
            inter_dry = current_dry + (dry_flow - current_dry) * fraction
            inter_wet = current_wet + (wet_flow - current_wet) * fraction
            
            self.set_flow_rates(dry_flow=inter_dry, wet_flow=inter_wet, max_flow=max_flow)
            self._wait_and_log(step_interval, on_data)
            
        # Ensure final set
        self.set_flow_rates(dry_flow=dry_flow, wet_flow=wet_flow, max_flow=max_flow)
        
        # 3. Equilibrate (60s)
        print("    Equilibrating for 60 seconds...")
        last_data = self._wait_and_log(60.0, on_data)
        
        # 4. Feedback Loop
        print("    Checking RH deviation...")
        while self.running:
            actual_rh = last_data.get('relative_humidity_control')
            if actual_rh is None:
                print("    Warning: No RH reading. Retrying...")
                last_data = self._wait_and_log(1.0, on_data)
                continue
                
            deviation = abs(actual_rh - target_rh)
            print(f"    Current RH: {actual_rh:.1f}% (Target: {target_rh:.1f}%, Deviation: {deviation:.1f}%)")
            
            if deviation <= stabilization_tolerance:
                print(f"    RH within {stabilization_tolerance}% tolerance. Proceeding.")
                return True, last_data.get('dry_flow', dry_flow), last_data.get('wet_flow', wet_flow)
            
            print("    Deviation > 5%. Adjusting flows...")
            current_dry = last_data.get('dry_flow', dry_flow)
            current_wet = last_data.get('wet_flow', wet_flow)
            
            new_dry, new_wet = self.adjust_flows_for_rh(
                target_rh=target_rh,
                actual_rh=actual_rh,
                current_dry_flow=current_dry,
                current_wet_flow=current_wet,
                max_flow=max_flow
            )
            
            self.set_flow_rates(dry_flow=new_dry, wet_flow=new_wet, max_flow=max_flow)
            
            print("    Waiting 30s after adjustment...")
            last_data = self._wait_and_log(30.0, on_data)
            
        return False, dry_flow, wet_flow
    
    def run_automated_experiment(self, direction: str = 'up', steps: int = 10, 
                                 duration: float = 5.0, max_flow: float = 2.0,
                                 control_interval: float = 5.0, rh_tolerance: float = 5.0,
                                 stabilization_time: float = 60.0, stabilization_tolerance: float = 2.0,
                                 on_data: Optional[Callable[[Dict], None]] = None):
        if not self.dry_mfc or not self.wet_mfc:
            raise RuntimeError("Both dry and wet MFCs must be connected for automated experiments")
        
        if not self.hygrometer:
            raise RuntimeError("Hygrometer must be connected for automated experiments")
        
        # Convert duration from minutes to seconds for internal calculations
        duration_seconds = duration * 60.0
        
        print("\n" + "=" * 60)
        print("Starting Automated Humidity Ramp Experiment")
        print("=" * 60)
        print(f"Direction: {direction.upper()}")
        print(f"Steps: {steps}")
        print(f"Step Duration: {duration:.1f} minutes")
        print(f"Target Flow: {max_flow:.3f} L/min")
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
        if self.plotter:
            self.plotter.start(data_source_callback=self.read_all_sensors)
        
        self.running = True
        
        try:
            for step in range(steps + 1):
                if not self.running:
                    break
                
                target_rh = start_rh + (step * rh_step)
                target_rh = max(0.0, min(100.0, target_rh))
                
                print(f"\n--- Step {step}/{steps} ---")
                print(f"Target RH: {target_rh:.1f}%")
                
                # Stabilize flows for this target RH
                stabilization_success, dry_flow, wet_flow = self.stabilize_flows_for_rh(
                    target_rh=target_rh,
                    max_flow=max_flow,
                    on_data=on_data
                )
                
                if not stabilization_success:
                    print(f"    Warning: Could not fully stabilize flows for step {step} (or stopped)")
                else:
                    print(f"    Flows stabilized for step {step}!")
                
                print(f"\nStarting data collection phase for step {step}...")
                
                # Data collection loop
                self._wait_and_log(duration_seconds, on_data)
                
                print(f"Step {step} complete\n")
            
            print("\n" + "=" * 60)
            print("Experiment Complete!")
            print("=" * 60)
            
        except KeyboardInterrupt:
            print("\n\nExperiment stopped by user")
        finally:
            self.running = False
            if self.plotter:
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

