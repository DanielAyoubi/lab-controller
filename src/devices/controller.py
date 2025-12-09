import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Tuple, Callable

from src.devices.vogtlin_mfc import VogtlinMFC
from src.devices.dewmaster import DewMaster
from src.devices.thermocouple import Thermocouple
from src.logging.data_logger import DataLogger


class Controller:
    def __init__(self, config: Dict):
        self.config = config
        self.running = False
        self.connected = False
        
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
        
        # Data fields for logging
        self.log_fields = [
            'timestamp',
            'dry_flow', 'wet_flow', 
            'dry_flow_setpoint', 'wet_flow_setpoint',
            'cell_temp', 'ambient_temp', 'dewpoint_temp',
            'relative_humidity', 'rh_device', 'rh_cell'
        ]
        
    def is_connected(self) -> bool:
        return self.connected
        
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
        
        self.connected = success
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
            
        self.connected = False
    
    def read_all_sensors(self) -> Dict[str, Optional[float]]:
        data = {
            'timestamp': datetime.now().isoformat(),
            'dry_flow': None, 'wet_flow': None,
            'dry_flow_setpoint': None, 'wet_flow_setpoint': None,
            'cell_temp': None, 'ambient_temp': None, 'dewpoint_temp': None,
            'relative_humidity': None,
            'rh_device': None,
            'rh_cell': None
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
                data['rh_device'] = readings.get('relative_humidity_device')

        # Read thermocouple
        if self.t_probe:
            data['cell_temp'] = self.t_probe.get_temperature()

        # Calculate RH
        if self.hygrometer and data['dewpoint_temp'] is not None:
            # Calculate RH based on cell temperature
            if data['cell_temp'] is not None:
                data['rh_cell'] = self.hygrometer.compute_relative_humidity(
                    data['dewpoint_temp'], data['cell_temp']
                )
            
            # Determine which RH to use for control/logging as primary 'relative_humidity'
            # For now, let's keep the logic based on config, or default to rh_cell if available?
            # The user didn't specify which one controls the experiment, but implied we want to see both.
            # Let's keep 'relative_humidity' as the one defined by 'rh_temperature_source' for backward compatibility
            
            temp_source = self.config.get('rh_temperature_source', 'ambient')
            if temp_source == 'cell' and data['rh_cell'] is not None:
                data['relative_humidity'] = data['rh_cell']
            elif data['rh_device'] is not None:
                data['relative_humidity'] = data['rh_device']
            elif data['ambient_temp'] is not None:
                 data['relative_humidity'] = self.hygrometer.compute_relative_humidity(
                    data['dewpoint_temp'], data['ambient_temp']
                )
        
        return data

    
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
    
    def calculate_flow_rates_for_rh(self, target_rh: float, total_flow: float) -> Tuple[float, float]:
        # Assumes: Dry air stream is at 0% RH & Wet air stream is at 100% RH (saturated)
        target_rh = max(0.0, min(100.0, target_rh))
        wet_flow = (target_rh / 100.0) * total_flow
        dry_flow = total_flow - wet_flow
        return dry_flow, wet_flow
    
    def stabilize_flows_for_rh(self, target_rh: float, max_flow: float, 
                               on_data: Optional[Callable[[Dict], None]] = None, stabilization_tolerance: float = 2.0,
                               stabilization_time: float = 60.0) -> Tuple[bool, float, float]:
        # Stabilize flow rates to achieve stable RH within tolerance of target.
        print(f"    Stabilizing flows for {target_rh:.1f}% RH")
        
        # 1. Calculate initial flows
        dry_flow, wet_flow = self.calculate_flow_rates_for_rh(target_rh, max_flow)
        
        # 2. Set flows directly (No ramping)
        print(f"    Setting flows to Dry: {dry_flow:.3f}, Wet: {wet_flow:.3f}...")
        self.set_flow_rates(dry_flow=dry_flow, wet_flow=wet_flow, max_flow=max_flow)
        
        # 3. Equilibrate
        print(f"    Equilibrating for {stabilization_time} seconds...")
        
        start_time = time.time()
        last_data = {}
        
        while (time.time() - start_time) < stabilization_time and self.running:
            cycle_start = time.time()
            
            # Read sensors
            last_data = self.read_all_sensors()
            
            # Log and Plot
            self.logger.log_data(last_data)
            
            # Callback
            if on_data:
                on_data(last_data)
            
            # Wait to ensure 1s interval
            elapsed = time.time() - cycle_start
            if elapsed < 1.0:
                time.sleep(1.0 - elapsed)
        
        # 4. Check RH deviation
        print("    Checking RH deviation...")
        
        if not self.running:
            return False, dry_flow, wet_flow

        actual_rh = last_data.get('relative_humidity')
        
        if actual_rh is not None:
            deviation = abs(actual_rh - target_rh)
            print(f"    Current RH: {actual_rh:.1f}% (Target: {target_rh:.1f}%, Deviation: {deviation:.1f}%)")
            
            final_dry = last_data.get('dry_flow')
            if final_dry is None:
                final_dry = dry_flow
                
            final_wet = last_data.get('wet_flow')
            if final_wet is None:
                final_wet = wet_flow

            if deviation <= stabilization_tolerance:
                print(f"    RH within {stabilization_tolerance}% tolerance. Proceeding.")
                return True, final_dry, final_wet
            else:
                print(f"    Warning: RH deviation {deviation:.1f}% exceeds tolerance {stabilization_tolerance}%. Proceeding anyway.")
                return False, final_dry, final_wet
        else:
            print("    Warning: No RH reading available. Proceeding anyway.")
            return False, dry_flow, wet_flow
    

    def run_automated_experiment(self, direction: str, steps: int, duration: float, 
                               max_flow: float, control_interval: float, rh_tolerance: float,
                               stabilization_time: float, stabilization_tolerance: float,
                               on_data: Optional[Callable[[Dict], None]] = None):
        self.running = True
        print(f"Starting experiment: {direction}, {steps} steps, {duration} min")
        
        # Define RH targets based on direction
        if direction == "up":
            targets = [i * (100.0 / steps) for i in range(steps + 1)]
        else:
            targets = [100.0 - (i * (100.0 / steps)) for i in range(steps + 1)]
            
        step_duration_sec = (duration * 60) / len(targets)
        
        for target_rh in targets:
            if not self.running:
                break
                
            print(f"\n=== Target RH: {target_rh:.1f}% ===")
            
            # 1. Stabilize
            is_stable, dry, wet = self.stabilize_flows_for_rh(
                target_rh=target_rh,
                max_flow=max_flow,
                on_data=on_data,
                stabilization_tolerance=stabilization_tolerance,
                stabilization_time=stabilization_time
            )
            
            if not self.running:
                break

            # 2. Hold for step duration
            print(f"    Holding for {step_duration_sec:.1f} seconds...")
            start_hold = time.time()
            while (time.time() - start_hold) < step_duration_sec and self.running:
                cycle_start = time.time()
                
                # Read and Log
                data = self.read_all_sensors()
                self.logger.log_data(data)
                if on_data:
                    on_data(data)
                
                # Wait for next control interval
                elapsed = time.time() - cycle_start
                if elapsed < control_interval:
                    time.sleep(control_interval - elapsed)
                    
        self.running = False
        print("Experiment finished.")

    def update_settings(self, new_config: Dict):
        self.config.update(new_config)
        
        # Update logger settings
        log_dir = new_config.get('log_dir', 'data')
        log_prefix = new_config.get('log_prefix', 'nsim_log')
        
        self.logger.output_dir = Path(log_dir)
        self.logger.filename_prefix = log_prefix
        self.logger.output_dir.mkdir(parents=True, exist_ok=True)

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

