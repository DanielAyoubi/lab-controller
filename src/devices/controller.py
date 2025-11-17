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
        
        # Data fields for logging
        self.log_fields = [
            'timestamp',
            'dry_flow',
            'wet_flow',
            'cell_temp',
            'ambient_temp',
            'dewpoint_temp',
            'relative_humidity'
        ]
        
    def connect_devices(self) -> bool:
        success = True
        
        # Connect dry air MFC
        if 'dry_mfc_port' in self.config:
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
        if 'wet_mfc_port' in self.config:
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
        if 'hygrometer_port' in self.config:
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

        if 't_probe' in self.config:
            print(f"Connecting to Temperature Probe on {self.config['t_probe_port']}...")
            self.t_probe = Thermocouple(
                port=self.config['t_probe_port'],
                baudrate=self.config.get('t_probe_baudrate', 9600)
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
    
    def read_all_sensors(self) -> Dict[str, float]:
        data = {
            'timestamp': datetime.now().isoformat(),
            'dry_flow': None,
            'wet_flow': None,
            'cell_temp': None,
            'ambient_temp': None,
            'dewpoint_temp': None,
            'relative_humidity': None
        }
        
        # Read dry MFC
        if self.dry_mfc:
            data['dry_flow'] = self.dry_mfc.get_flow()
        
        # Read wet MFC
        if self.wet_mfc:
            data['wet_flow'] = self.wet_mfc.get_flow()
        
        # Read hygrometer
        if self.hygrometer:
            readings = self.hygrometer.get_readings()
            if readings:
                data['ambient_temp'] = readings.get('ambient_temp')
                data['dewpoint_temp'] = readings.get('dewpoint_temp')
                data['relative_humidity'] = readings.get('relative_humidity')

        if self.t_probe:
            data['cell_temp'] = self.t_probe.get_temperature()
        
        return data
    
    def set_flow_rates(self, dry_flow: Optional[float] = None, wet_flow: Optional[float] = None, 
                       max_flow: Optional[float] = None, timeout: int = 10):
        """
        Set flow rates for dry and/or wet MFCs.
        
        Args:
            dry_flow: Dry air flow rate in L/min
            wet_flow: Wet air flow rate in L/min
            max_flow: Maximum allowed total flow rate in L/min (for validation)
        """
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
            time.sleep(timeout) # Let flow equilibrate
    
    def start_monitoring(self, interval: float = 5.0):
        """
        Start continuous monitoring and logging.
        
        Args:
            interval: Sampling interval in seconds
        """
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
                # Read all sensors
                data = self.read_all_sensors()
                
                # Log data
                self.logger.log_data(data)
                
                # Add to plotter
                self.plotter.add_data_point(data)
                
                # Display current readings
                print(f"[{data['timestamp']}]")
                dry_sp = self.dry_mfc.get_setpoint() if self.dry_mfc else None
                wet_sp = self.wet_mfc.get_setpoint() if self.wet_mfc else None
                if dry_sp is not None:
                    print(f"  Dry Air:  {data['dry_flow']:.3f} L/min (SP: {dry_sp:.3f})")
                else:
                    print(f"  Dry Air:  {data['dry_flow']:.3f} L/min")
                if wet_sp is not None:
                    print(f"  Wet Air:  {data['wet_flow']:.3f} L/min (SP: {wet_sp:.3f})")
                else:
                    print(f"  Wet Air:  {data['wet_flow']:.3f} L/min")
                if data['ambient_temp'] is not None:
                    print(f"  Ambient:  {data['ambient_temp']:.2f} °C")
                if data['dewpoint_temp'] is not None:
                    print(f"  Dewpoint: {data['dewpoint_temp']:.2f} °C")
                if data['relative_humidity'] is not None:
                    print(f"  Humidity: {data['relative_humidity']:.1f} %\n")
                
                # Wait for next sample
                time.sleep(interval)
                
        except KeyboardInterrupt:
            print("\n\nMonitoring stopped by user")
        finally:
            self.running = False
            self.plotter.stop()
    
    def calculate_flow_rates_for_rh(self, target_rh: float, total_flow: float) -> Tuple[float, float]:
        """
        Calculate required dry and wet flow rates to achieve target relative humidity.
        
        Assumes:
        - Dry air stream is at 0% RH
        - Wet air stream is at 100% RH (saturated)
        - Simple mixing model: RH_result ≈ (wet_flow / total_flow) * 100
        
        Args:
            target_rh: Target relative humidity (0-100)
            total_flow: Total flow rate in L/min
            
        Returns:
            Tuple of (dry_flow, wet_flow) in L/min
        """
        # Clamp target RH to valid range
        target_rh = max(0.0, min(100.0, target_rh))
        
        # Calculate wet flow as fraction of total flow
        wet_flow = (target_rh / 100.0) * total_flow
        dry_flow = total_flow - wet_flow
        
        return dry_flow, wet_flow
    
    def adjust_flows_for_rh(self, target_rh: float, actual_rh: float, 
                            current_dry_flow: float, current_wet_flow: float,
                            max_flow: float, adjustment_factor: float = 0.05) -> Tuple[float, float]:
        """
        Adjust flow rates to reduce deviation from target RH.
        Aims to maintain max_flow as total, but allows going below if needed.
        
        Args:
            target_rh: Target relative humidity (0-100)
            actual_rh: Measured relative humidity (0-100)
            current_dry_flow: Current dry air flow rate in L/min
            current_wet_flow: Current wet air flow rate in L/min
            max_flow: Maximum/target total flow rate in L/min
            adjustment_factor: Proportional adjustment factor (0-1)
            
        Returns:
            Tuple of (new_dry_flow, new_wet_flow) in L/min
        """
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
            # Clamp wet flow to max_flow
            new_wet_flow = min(max_flow, new_wet_flow)
        
        # Ensure total doesn't exceed max_flow
        new_total = new_dry_flow + new_wet_flow
        if new_total > max_flow:
            # Scale down proportionally
            scale = max_flow / new_total
            new_dry_flow *= scale
            new_wet_flow *= scale
        
        return new_dry_flow, new_wet_flow
    
    def run_automated_experiment(self, direction: str = 'up', steps: int = 10, 
                                 duration: float = 5.0, max_flow: float = 2.0,
                                 control_interval: float = 5.0, rh_tolerance: float = 5.0):
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
        print("=" * 60 + "\n")
        
        # Determine start and end RH
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
                # Calculate target RH for this step
                target_rh = start_rh + (step * rh_step)
                
                # Clamp to valid range
                target_rh = max(0.0, min(100.0, target_rh))
                
                print(f"\n--- Step {step}/{steps} ---")
                print(f"Target RH: {target_rh:.1f}%")
                
                # Calculate initial flow rates (aim for max_flow as total)
                dry_flow, wet_flow = self.calculate_flow_rates_for_rh(target_rh, max_flow)
                
                # Set initial flow rates (validate against max_flow - allows going below)
                self.set_flow_rates(dry_flow=dry_flow, wet_flow=wet_flow, max_flow=max_flow)
                time.sleep(2.0)  # Wait for flows to stabilize
                
                # Control loop for this step
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
                    
                    actual_rh = data.get('relative_humidity')
                    
                    # Control update
                    if (current_time - last_control_time) >= control_interval and actual_rh is not None:
                        deviation = abs(actual_rh - target_rh)
                        
                        elapsed_min = (current_time - step_start_time) / 60.0
                        step_duration_min = step_duration_seconds / 60.0
                        cell_temp = data.get('cell_temp')
                        ambient_temp = data.get('ambient_temp')
                        dewpoint_temp = data.get('dewpoint_temp')

                        print(f"  Time: {elapsed_min:.2f} min / {step_duration_min:.2f} min ({current_time - step_start_time:.1f}s / {step_duration_seconds:.1f}s)")
                        print(f"  Target RH: {target_rh:.1f}% | Actual RH: {actual_rh:.1f}% | Deviation: {deviation:.1f}%")
                        print(f"  Dry Flow: {data.get('dry_flow', 0):.3f} L/min | Wet Flow: {data.get('wet_flow', 0):.3f} L/min")

                        temps_parts = []
                        if cell_temp is not None:
                            temps_parts.append(f"Cell Temp: {cell_temp:.2f}°C")
                        if ambient_temp is not None:
                            temps_parts.append(f"Ambient Temp: {ambient_temp:.2f}°C")
                        if dewpoint_temp is not None:
                            temps_parts.append(f"Dewpoint: {dewpoint_temp:.2f}°C")
                        if temps_parts:
                            print("  " + " | ".join(temps_parts))
                        
                        # If deviation exceeds tolerance, adjust flows
                        if deviation > rh_tolerance:
                            print(f"  ⚠ Deviation {deviation:.1f}% exceeds tolerance {rh_tolerance:.1f}% - Adjusting flows...")
                            
                            current_dry = data.get('dry_flow', dry_flow)
                            current_wet = data.get('wet_flow', wet_flow)
                            
                            new_dry, new_wet = self.adjust_flows_for_rh(
                                target_rh=target_rh,
                                actual_rh=actual_rh,
                                current_dry_flow=current_dry,
                                current_wet_flow=current_wet,
                                max_flow=max_flow,
                                adjustment_factor=0.05  # 5% adjustment per control cycle
                            )
                            
                            self.set_flow_rates(dry_flow=new_dry, wet_flow=new_wet, max_flow=max_flow)
                            dry_flow, wet_flow = new_dry, new_wet
                            time.sleep(1.0)  # Brief pause after adjustment
                        else:
                            print("  ✓ Within tolerance")
                        
                        last_control_time = current_time
                        print()
                    
                    # Small sleep to avoid excessive CPU usage
                    time.sleep(0.5)
                
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
