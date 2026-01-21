import time, math
import numpy as np
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Tuple, Callable

from src.devices.vogtlin_mfc import VogtlinMFC
from src.devices.hygrometer import Hygrometer
from src.devices.chiller import JulaboChiller
from src.logging.data_logger import DataLogger


class Controller:
    def __init__(self, config: Dict):
        self.config = config
        self.running = False
        self.connected = False
        # Messages produced during connect/disconnect attempts
        self.connect_messages = []

        # Initialize devices
        self.dry_mfc: Optional[VogtlinMFC] = None
        self.wet_mfc: Optional[VogtlinMFC] = None
        self.hygrometer: Optional[Hygrometer] = None
        self.chiller: Optional[JulaboChiller] = None
        
        # Initialize logger
        self.logger = DataLogger(
            output_dir=self.config.get('log_dir', 'data'),
            filename_prefix=self.config.get('log_prefix', 'nsim_log')
        )

        # Data fields for logging
        self.log_fields = [
            'timestamp',
            'dry_flow', 'wet_flow', 
            'dry_flow_setpoint', 'wet_flow_setpoint',
            'hygrometer_temp', 'dewpoint_temp',
            'rh_hygrometer', 'rh_chiller',
            'chiller_temp', 'chiller_setpoint'
        ]
        
        # RH Control State
        self.rh_control_active = False
        self.rh_setpoint = 50.0
        self.rh_control_total_flow = 2.0
        self.rh_params = {
            'Kp': 0.02, 
            'Ki': 0.001,
            'Kd': 0.0,
            'integral_limit': 0.5 
        }
        self.pid_state = {
            'last_error': 0.0,
            'integral': 0.0,
            'last_time': time.time()
        }
        
        
    def is_connected(self) -> bool:
        return self.connected
        
    def connect_devices(self) -> Dict[str, bool]:
        results: Dict[str, bool] = {}

        # Dry air MFC
        if 'dry_mfc_port' in self.config and self.config.get('dry_mfc_enabled', True):
            self.dry_mfc = VogtlinMFC(
                port=self.config['dry_mfc_port'],
                address=self.config.get('dry_mfc_address', 1),
                name="Dry Air MFC"
            )
            try:
                results['dry_mfc'] = bool(self.dry_mfc.connect())
            except Exception as e:
                print(f"Error connecting dry MFC: {e}")
                results['dry_mfc'] = self.dry_mfc.is_connected()

        # Wet air MFC
        if 'wet_mfc_port' in self.config and self.config.get('wet_mfc_enabled', True):
            self.wet_mfc = VogtlinMFC(
                port=self.config['wet_mfc_port'],
                address=self.config.get('wet_mfc_address', 2),
                name="Wet Air MFC"
            )
            try:
                results['wet_mfc'] = bool(self.wet_mfc.connect())
            except Exception as e:
                print(f"Error connecting wet MFC: {e}")
                results['wet_mfc'] = self.wet_mfc.is_connected()

        # Hygrometer (Hygrometer)
        if 'hygrometer_port' in self.config and self.config.get('hygrometer_enabled', True):
            self.hygrometer = Hygrometer(
                port=self.config['hygrometer_port'],
                baudrate=self.config.get('hygrometer_baudrate', 9600)
            )
            try:
                # Hygrometer.connect() raises on failure
                results['hygrometer'] = bool(self.hygrometer.connect())
            except Exception as e:
                print(f"Error connecting hygrometer: {e}")
                results['hygrometer'] = self.hygrometer.is_connected()

        # Chiller
        if 'chiller_port' in self.config and self.config.get('chiller_enabled', True):
            self.chiller = JulaboChiller(
                port=self.config['chiller_port'],
                baudrate=self.config.get('chiller_baudrate', 9600)
            )
            try:
                results['chiller'] = bool(self.chiller.connect())
            except Exception as e:
                print(f"Error connecting chiller: {e}")
                results['chiller'] = self.chiller.is_connected()

        # Determine overall connected status (at least one device)
        self.connected = any(results.values()) if results else False
        print(f"Controller connected: {self.connected} (Details: {results})")
        return results
    
    def disconnect_devices(self):
        print("\nDisconnecting devices...")
        
        if self.dry_mfc:
            self.dry_mfc.disconnect()
        
        if self.wet_mfc:
            self.wet_mfc.disconnect()
        
        if self.hygrometer:
            self.hygrometer.disconnect()

        if self.chiller:
            self.chiller.disconnect()
            
        self.running = False
        self.connected = False
    
    def read_all_sensors(self) -> Dict[str, Optional[float]]:
        data = {
            'timestamp': datetime.now().isoformat(),
            'dry_flow': None, 'wet_flow': None,
            'dry_flow_setpoint': None, 'wet_flow_setpoint': None,
            'hygrometer_temp': None, 'dewpoint_temp': None,
            'rh_hygrometer': None, 'rh_chiller': None,
            'chiller_temp': None, 'chiller_setpoint': None
        }
        
        # Read dry MFC
        if self.dry_mfc:
            try:
                data['dry_flow'] = self.dry_mfc.get_flow()
                data['dry_flow_setpoint'] = self.dry_mfc.get_setpoint()
            except Exception as e:
                print(f"Error reading dry MFC: {e}")
        
        # Read wet MFC
        if self.wet_mfc:
            try:
                data['wet_flow'] = self.wet_mfc.get_flow()
                data['wet_flow_setpoint'] = self.wet_mfc.get_setpoint()
            except Exception as e:
                print(f"Error reading wet MFC: {e}")
        
        # Read hygrometer
        if self.hygrometer:
            try:
                readings = self.hygrometer.get_readings()
                if readings:
                    # Driver returns 'ambient_temp' for ambient/hygrometer temp
                    data['hygrometer_temp'] = readings.get('hygrometer_temp') or readings.get('ambient_temp')
                    data['dewpoint_temp'] = readings.get('dewpoint_temp')
            except Exception as e:
                print(f"Error reading hygrometer: {e}")

        # Read chiller
        if self.chiller:
            try:
                data['chiller_temp'] = self.chiller.get_external_temperature()
                data['chiller_setpoint'] = self.chiller.get_setpoint_temperature()
            except Exception as e:
                print(f"Error reading chiller: {e}")

        # Calculate RH
        if self.hygrometer and data['dewpoint_temp'] is not None:
            # Calculate RH using Hygrometer Ambient Temp (rh_hygrometer)
            if data['hygrometer_temp'] is not None:
                try:
                    val = self.hygrometer.compute_relative_humidity(
                        dp=data['dewpoint_temp'], t=float(data['hygrometer_temp'])
                    )
                    if val is not None and math.isfinite(val):
                        data['rh_hygrometer'] = val
                except Exception as e:
                    print(f"Error computing rh_hygrometer: {e}")

            # Calculate RH using Chiller Temp (rh_chiller)
            if data['chiller_temp'] is not None:
                try:
                    val = self.hygrometer.compute_relative_humidity(
                        dp=data['dewpoint_temp'], t=float(data['chiller_temp'])
                    )
                    if val is not None and math.isfinite(val):
                        data['rh_chiller'] = val
                except Exception as e:
                    print(f"Error computing rh_chiller: {e}")
        
        return data

    
    def set_flow_rates(self, dry_flow: Optional[float] = None, wet_flow: Optional[float] = None, 
                       max_flow: Optional[float] = None, ramp_flow=True):
        # Validate total flow doesn't exceed maximum
        if max_flow is not None:
            total = (dry_flow or 0) + (wet_flow or 0)
            if total > max_flow:
                print(f"Requested total flow {total:.2f} exceeds maximum {max_flow:.2f}. Aborting set.")
                return False

        # Ramping Logic
        if ramp_flow:
            current_dry = 0.0
            current_wet = 0.0
            
            # Read current setpoints
            if self.dry_mfc:
                current_dry = self.dry_mfc.get_setpoint()
            if self.wet_mfc:
                current_wet = self.wet_mfc.get_setpoint()
            
            # Calculate changes
            dry_diff = (dry_flow - current_dry) if (dry_flow is not None and self.dry_mfc) else 0.0
            wet_diff = (wet_flow - current_wet) if (wet_flow is not None and self.wet_mfc) else 0.0
            
            max_delta = max(abs(dry_diff), abs(wet_diff))
            step_size = 0.05 # L/min
            
            if max_delta > step_size:
                steps = int(max_delta / step_size)
                # Cap max steps to avoid too long blocking (e.g. if reading was wrong and diff is huge)
                if steps > 100: 
                    steps = 100 
                
                if steps > 0:
                    print(f"Ramping flows over {steps} steps...")
                    for i in range(1, steps + 1):
                        frac = i / steps
                        
                        if dry_flow is not None and self.dry_mfc:
                            val = current_dry + dry_diff * frac
                            self.dry_mfc.set_flow(val)
                            
                        if wet_flow is not None and self.wet_mfc:
                            val = current_wet + wet_diff * frac
                            self.wet_mfc.set_flow(val)
                        
                        time.sleep(0.1)

        # Final Set (Ensure exact target)
        success = True
        if dry_flow is not None and self.dry_mfc:
            try:
                if self.dry_mfc.set_flow(dry_flow):
                    print(f"Dry MFC setpoint set to {dry_flow:.3f}")
                else:
                    print("Failed to set dry MFC flow")
                    success = False
            except Exception as e:
                print(f"Error setting dry MFC: {e}")
                success = False

        if wet_flow is not None and self.wet_mfc:
            try:
                if self.wet_mfc.set_flow(wet_flow):
                    print(f"Wet MFC setpoint set to {wet_flow:.3f}")
                else:
                    print("Failed to set wet MFC flow")
                    success = False
            except Exception as e:
                print(f"Error setting wet MFC: {e}")
                success = False

        return success

    def set_chiller_temperature(self, temperature: float):
        if self.chiller:
            self.chiller.set_setpoint_temperature(temperature)
            # Ensure control is started
            self.chiller.start_control()
            print(f"Chiller setpoint set to {temperature:.2f} °C")
        else:
            print("Chiller not connected")
    
    
    def read_and_log(self, on_data: Optional[Callable[[Dict], None]] = None) -> Dict:
        """Helper to read sensors, log data, and trigger callback."""
        try:
            data = self.read_all_sensors()
        except Exception as e:
            print(f"Error reading sensors: {e}")
            data = {}

        try:
            self.logger.log_data(data)
        except Exception as e:
            print(f"Logger error: {e}")

        if on_data:
            try:
                on_data(data)
            except Exception as e:
                print(f"Callback error: {e}")
        return data

    def wait_and_log(self, duration: float, on_data: Optional[Callable[[Dict], None]] = None, interval: float = 1.0):
        """Waits for duration seconds while continuing to log data."""
        start = time.time()
        while (time.time() - start) < duration and self.running:
            cycle_start = time.time()
            self.read_and_log(on_data)
            elapsed = time.time() - cycle_start
            if elapsed < interval:
                time.sleep(interval - elapsed)

    def set_rh_control_active(self, active: bool, target: float = None, total_flow: float = None):
        if active:
            self.rh_control_active = True
            if target is not None:
                self.rh_setpoint = target
            if total_flow is not None:
                self.rh_control_total_flow = total_flow
            self.pid_state = {'last_error': 0.0, 'integral': 0.0, 'last_time': time.time()}
            print(f"RH Control Activated: Target={self.rh_setpoint}%, Flow={self.rh_control_total_flow} L/min")
        else:
            self.rh_control_active = False
            print("RH Control Deactivated")

    def update_rh_control_loop(self, current_rh: Optional[float]):
        if not self.rh_control_active or current_rh is None:
            return

        now = time.time()
        dt = now - self.pid_state['last_time']
        if dt < 1.0: 
            return
            
        error = self.rh_setpoint - current_rh
        
        # Proportional
        p_term = self.rh_params['Kp'] * error
        
        # Integral
        self.pid_state['integral'] += error * dt
        # Anti-windup
        limit = self.rh_params['integral_limit'] / self.rh_params['Ki'] if self.rh_params['Ki'] > 0 else 0
        self.pid_state['integral'] = max(-limit, min(limit, self.pid_state['integral']))
        i_term = self.rh_params['Ki'] * self.pid_state['integral']
        
        output_change = p_term + i_term
        
        # Calculate current wet ratio
        curr_dry_sp = self.dry_mfc.get_setpoint() if self.dry_mfc else 0
        curr_wet_sp = self.wet_mfc.get_setpoint() if self.wet_mfc else 0
        total_sp = curr_dry_sp + curr_wet_sp
        
        if total_sp <= 0.01:
            # Start guess
            new_wet_ratio = max(0.0, min(1.0, self.rh_setpoint / 100.0))
        else:
            current_wet_ratio = curr_wet_sp / total_sp
            new_wet_ratio = current_wet_ratio + output_change

        new_wet_ratio = max(0.0, min(1.0, new_wet_ratio))
        
        new_wet = new_wet_ratio * self.rh_control_total_flow
        new_dry = (1.0 - new_wet_ratio) * self.rh_control_total_flow
        
        self.pid_state['last_error'] = error
        self.pid_state['last_time'] = now
        
        # Only update if change is significant or first run
        if abs(output_change) > 0.0001: 
            # print(f"RH Control: Target {self.rh_setpoint}%, Curr {current_rh:.1f}%, Err {error:.1f} -> New Wet Ratio {new_wet_ratio:.3f}")
            self.set_flow_rates(dry_flow=new_dry, wet_flow=new_wet, max_flow=self.rh_control_total_flow * 1.1, ramp_flow=False)

    def tune_flows_for_rh(self, target_rh: float, max_flow: float, 
                          rh_tolerance: float = 1.0, 
                          stabilization_tolerance: float = 0.5,
                          equilibration_time: float = 100.0,
                          stability_poll_time: float = 30.0, 
                          timeout: float = 600.0,
                          on_data: Optional[Callable[[Dict], None]] = None) -> Tuple[bool, float, float]:
        
        print(f"Tuning flows for {target_rh:.1f}% RH (Target +/-{rh_tolerance}%, Stable +/-{stabilization_tolerance}%)")
        
        start_time = time.time()
        
        # Initial guess based on theoretical linear mixing
        current_wet_ratio = max(0.0, min(1.0, target_rh / 100.0))
        
        # Keep track of flows
        dry_flow = 0.0
        wet_flow = 0.0
        
        iteration = 0
        Kp = 0.01  # Proportional gain for RH control
        
        while (time.time() - start_time) < timeout and self.running:
            iteration += 1
            
            # Calculates flows
            wet_flow = current_wet_ratio * max_flow
            dry_flow = max_flow - wet_flow
            
            # Set flows
            print(f"Iteration {iteration}: Ratio {current_wet_ratio:.3f} (Dry: {dry_flow:.3f}, Wet: {wet_flow:.3f})")
            self.set_flow_rates(dry_flow=dry_flow, wet_flow=wet_flow, max_flow=max_flow)
            
            # Wait for equilibration (tubes to adjust)
            # print(f"  Equilibrating for {equilibration_time:.1f}s...")
            self.wait_and_log(equilibration_time, on_data)
            if not self.running: 
                break
            
            # Monitoring stability
            # print(f"  Monitoring stability for {stability_poll_time:.1f}s...")
            rh_values = []
            monitor_start = time.time()
                
            while (time.time() - monitor_start) < stability_poll_time and self.running:
                data = self.read_and_log(on_data)
                # Use Chiller-based RH for control as it represents sample temperature
                val = data.get('rh_chiller')
                if val is not None and isinstance(val, (int, float)):
                    rh_values.append(val)
                
                # Sleep approx 1s between reads (read_and_log takes time, but mainly we want spacing)
                time.sleep(1.0) 
            
            if not rh_values:
                print("  No RH data received. Retrying...")
                continue
                
            avg_rh = np.mean(rh_values)
            # Range is max - min
            range_rh = np.max(rh_values) - np.min(rh_values)
            
            error = target_rh - avg_rh
            
            print(f"  Stats: Avg RH {avg_rh:.2f}%, Range {range_rh:.2f}, Error {error:.2f}")

            # Criteria: 
            # 1. Error within rh_tolerance
            # 2. Stability (fluctuation/range) within stabilization_tolerance
            is_stable = range_rh < stabilization_tolerance
            is_accurate = abs(error) < rh_tolerance
            
            if is_stable and is_accurate:
                print(f"  Success: Target {target_rh}% reached and stable.")
                return True, dry_flow, wet_flow
            
            # Adjust ratio
            adjustment = Kp * error
            
            # Update ratio
            current_wet_ratio += adjustment
            current_wet_ratio = max(0.0, min(1.0, current_wet_ratio))
            
        return False, dry_flow, wet_flow
    

    def run_automated_experiment(self, min_rh: float, max_rh: float, direction: str, steps: int, 
                               max_flow: float, control_interval: float, rh_tolerance: float,
                               stabilization_time: float, stabilization_tolerance: float,
                               on_data: Optional[Callable[[Dict], None]] = None):
        self.running = True
        
        # Start logging
        self.logger.start_new_log(self.log_fields)
        
        try:
            print(f"Starting experiment: {direction}, Range {min_rh}-{max_rh}%, {steps} steps")
            
            # Generate targets
            if steps < 1: 
                steps = 1
            
            # Determine start and end based on direction
            if direction.lower() == "up":
                start_val = min_rh
                end_val = max_rh
            else:
                start_val = max_rh
                end_val = min_rh
                
            targets = []
            for i in range(steps + 1):
                t = start_val + (end_val - start_val) * (i / float(steps))
                targets.append(t)
            
            for target_rh in targets:
                if not self.running:
                    break
                    
                print(f"\n=== Target RH: {target_rh:.1f}% ===")
                
                # Tune flows (Closed Loop)
                # We use stabilization_time as the timeout for the whole tuning process of this step?
                # Or just pass a reasonable timeout (e.g. 10 mins)
                # The user config 'stabilization_time' might be small (60s). 
                # Let's ensure timeout is sufficient.
                step_timeout = max(stabilization_time, 600.0) 

                is_stable, dry, wet = self.tune_flows_for_rh(
                    target_rh=target_rh,
                    max_flow=max_flow,
                    rh_tolerance=rh_tolerance,
                    stabilization_tolerance=stabilization_tolerance,
                    equilibration_time=100.0,   
                    stability_poll_time=30.0,  
                    timeout=step_timeout,
                    on_data=on_data
                )
                
                if not self.running:
                    break

                # Hold briefly to record stable data
                print("    Step stable. Holding for 10s...")
                self.wait_and_log(10.0, on_data)
                
        finally:
            self.running = False
            self.logger.close()
            print("Experiment finished.")

    def update_settings(self, new_config: Dict):
        self.config.update(new_config)
        
        # Update logger settings
        log_dir = new_config.get('log_dir', 'data')
        log_prefix = new_config.get('log_prefix', 'nsim_log')
        
        if self.logger is not None:
            self.logger.output_dir = Path(log_dir)
            self.logger.filename_prefix = log_prefix
            self.logger.output_dir.mkdir(parents=True, exist_ok=True)
