import time, math
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Tuple, Callable

from src.devices.vogtlin_mfc import VogtlinMFC
from src.devices.hygrometer import Hygrometer
from src.devices.thermocouple import Thermocouple
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
        self.t_probe: Optional[Thermocouple] = None
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
            'relative_humidity', 'rh_device',
            'chiller_temp', 'chiller_setpoint'
        ]

    def add_message(self, msg: str):
        ts = datetime.now().isoformat(timespec='seconds')
        entry = f"[{ts}] {msg}"
        try:
            self.connect_messages.append(entry)
        except Exception:
            pass
        
        
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
            results['dry_mfc'] = self.dry_mfc.is_connected()

        # Wet air MFC
        if 'wet_mfc_port' in self.config and self.config.get('wet_mfc_enabled', True):
            self.wet_mfc = VogtlinMFC(
                port=self.config['wet_mfc_port'],
                address=self.config.get('wet_mfc_address', 2),
                name="Wet Air MFC"
            )
            results['wet_mfc'] = self.wet_mfc.is_connected()

        # Hygrometer (Hygrometer)
        if 'hygrometer_port' in self.config and self.config.get('hygrometer_enabled', True):
            self.hygrometer = Hygrometer(
                port=self.config['hygrometer_port'],
                baudrate=self.config.get('hygrometer_baudrate', 9600)
            )
            results['hygrometer'] = self.hygrometer.is_connected()

        # Temperature Probe (USB thermocouple) — attempt if either vendor/product IDs present or enabled flag
        if ('t_probe_vendor_id' in self.config and 't_probe_product_id' in self.config) and self.config.get('t_probe_enabled'):
            vendor_id = self.config.get('t_probe_vendor_id', Thermocouple.DEFAULT_VENDOR_ID)
            product_id = self.config.get('t_probe_product_id', Thermocouple.DEFAULT_PRODUCT_ID)
            self.t_probe = Thermocouple(
                vendor_id=vendor_id,
                product_id=product_id,
            )
            results['t_probe'] = self.t_probe.is_connected()

        # Chiller
        if 'chiller_port' in self.config and self.config.get('chiller_enabled', True):
            self.chiller = JulaboChiller(
                port=self.config['chiller_port'],
                baudrate=self.config.get('chiller_baudrate', 9600)
            )
            results['chiller'] = self.chiller.is_connected()

        # Determine overall connected status (at least one device)
        self.connected = any(results.values()) if results else False
        return results
    
    def disconnect_devices(self):
        print("\nDisconnecting devices...")
        
        if self.dry_mfc:
            self.dry_mfc.disconnect()
        
        if self.wet_mfc:
            self.wet_mfc.disconnect()
        
        if self.hygrometer:
            self.hygrometer.disconnect()

        if self.t_probe:
            self.t_probe.disconnect()

        if self.chiller:
            self.chiller.disconnect()
            
        self.running = False
        self.connected = False
    
    def read_all_sensors(self) -> Dict[str, Optional[float]]:
        data = {
            'timestamp': datetime.now().isoformat(),
            'dry_flow': None, 'wet_flow': None,
            'dry_flow_setpoint': None, 'wet_flow_setpoint': None,
            'cell_temp': None, 'hygrometer_temp': None, 'dewpoint_temp': None,
            'relative_humidity': None,
            'rh_device': None,
            'chiller_temp': None, 'chiller_setpoint': None
        }
        
        # Read dry MFC
        if self.dry_mfc:
            try:
                data['dry_flow'] = self.dry_mfc.get_flow()
                data['dry_flow_setpoint'] = self.dry_mfc.get_setpoint()
            except Exception as e:
                self.add_message(f"Error reading dry MFC: {e}")
        
        # Read wet MFC
        if self.wet_mfc:
            try:
                data['wet_flow'] = self.wet_mfc.get_flow()
                data['wet_flow_setpoint'] = self.wet_mfc.get_setpoint()
            except Exception as e:
                self.add_message(f"Error reading wet MFC: {e}")
        
        # Read hygrometer
        if self.hygrometer:
            try:
                readings = self.hygrometer.get_readings()
                if readings:
                    # Driver returns 'ambient_temp' for ambient/hygrometer temp
                    data['hygrometer_temp'] = readings.get('hygrometer_temp') or readings.get('ambient_temp')
                    data['dewpoint_temp'] = readings.get('dewpoint_temp')
                    data['rh_device'] = readings.get('relative_humidity_device') or readings.get('relative_humidity')
            except Exception as e:
                self.add_message(f"Error reading hygrometer: {e}")

        # Read thermocouple
        if self.t_probe:
            try:
                data['thermocouple_temp'] = self.t_probe.get_temperature()
            except Exception as e:
                self.add_message(f"Error reading thermocouple: {e}")

        # Read chiller
        if self.chiller:
            try:
                data['chiller_temp'] = self.chiller.get_current_temperature()
                data['chiller_setpoint'] = self.chiller.get_setpoint_temperature()
            except Exception as e:
                self.add_message(f"Error reading chiller: {e}")

        # Calculate RH
        if self.hygrometer and data['dewpoint_temp'] is not None:
            temp_source = self.config.get('rh_temperature_source', 'hygrometer')
            
            # Determine the temperature to use for RH calculation
            calc_temp = None
            if temp_source == 'thermocouple':
                calc_temp = data.get('thermocouple_temp')
            elif temp_source == 'chiller':
                calc_temp = data.get('chiller_temp')
            else: # 'hygrometer' or default
                calc_temp = data.get('hygrometer_temp')
            
            # Calculate RH if we have a valid temperature
            if calc_temp is not None:
                try:
                    data['relative_humidity'] = self.hygrometer.compute_relative_humidity(
                        dp=data['dewpoint_temp'], t=calc_temp
                    )
                except Exception as e:
                    self.add_message(f"Error computing relative humidity: {e}")
            else:
                self.add_message("RH calculation skipped: no valid temperature available for RH computation")
        
        return data

    
    def set_flow_rates(self, dry_flow: Optional[float] = None, wet_flow: Optional[float] = None, 
                       max_flow: Optional[float] = None, ramp_flow=True):
        # Validate total flow doesn't exceed maximum
        if max_flow is not None:
            total = (dry_flow or 0) + (wet_flow or 0)
            if total > max_flow:
                self.add_message(f"Requested total flow {total:.2f} exceeds maximum {max_flow:.2f}. Aborting set.")
                return False

        success = True
        if dry_flow is not None and self.dry_mfc:
            try:
                if self.dry_mfc.set_flow(dry_flow):
                    self.add_message(f"Dry MFC setpoint set to {dry_flow:.3f}")
                else:
                    self.add_message("Failed to set dry MFC flow")
                    success = False
            except Exception as e:
                self.add_message(f"Error setting dry MFC: {e}")
                success = False

        if wet_flow is not None and self.wet_mfc:
            try:
                if self.wet_mfc.set_flow(wet_flow):
                    self.add_message(f"Wet MFC setpoint set to {wet_flow:.3f}")
                else:
                    self.add_message("Failed to set wet MFC flow")
                    success = False
            except Exception as e:
                self.add_message(f"Error setting wet MFC: {e}")
                success = False

        return success

    def set_chiller_temperature(self, temperature: float):
        if self.chiller:
            self.chiller.set_setpoint_temperature(temperature)
            # Ensure control is started
            self.chiller.start_control()
            self.add_message(f"Chiller setpoint set to {temperature:.2f} °C")
        else:
            print("Chiller not connected")
    
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
        self.add_message(f"Stabilizing flows for {target_rh:.1f}% RH")
        
        # 1. Calculate initial flows
        dry_flow, wet_flow = self.calculate_flow_rates_for_rh(target_rh, max_flow)
        
        # 2. Set flows directly
        self.add_message(f"Setting flows to Dry: {dry_flow:.3f}, Wet: {wet_flow:.3f}")
        self.set_flow_rates(dry_flow=dry_flow, wet_flow=wet_flow, max_flow=max_flow)
        
        # 3. Equilibrate
        self.add_message(f"Equilibrating for {stabilization_time} seconds")
        start_time = time.time()
        last_data = {}
        
        while (time.time() - start_time) < stabilization_time and self.running:
            cycle_start = time.time()

            # Read sensors
            try:
                last_data = self.read_all_sensors()
            except Exception as e:
                self.add_message(f"Error reading sensors during stabilization: {e}")
                last_data = {}

            # Log and Plot (protect logger)
            try:
                self.logger.log_data(last_data)
            except Exception as e:
                self.add_message(f"Logger error during stabilization: {e}")

            # Callback (protect user callback)
            if on_data:
                try:
                    on_data(last_data)
                except Exception as e:
                    self.add_message(f"on_data callback error: {e}")

            # Wait to ensure 1s interval
            elapsed = time.time() - cycle_start
            if elapsed < 1.0:
                time.sleep(1.0 - elapsed)
        
        # 4. Check RH deviation
        self.add_message("Checking RH deviation")
        
        if not self.running:
            return False, dry_flow, wet_flow

        actual_rh = last_data.get('relative_humidity')
        
        if actual_rh is not None:
            deviation = abs(actual_rh - target_rh)
            self.add_message(f"Current RH: {actual_rh:.1f}% (Target: {target_rh:.1f}%, Deviation: {deviation:.1f}%)")
            
            final_dry = last_data.get('dry_flow')
            if final_dry is None:
                final_dry = dry_flow
                
            final_wet = last_data.get('wet_flow')
            if final_wet is None:
                final_wet = wet_flow

            if deviation <= stabilization_tolerance:
                self.add_message(f"RH within {stabilization_tolerance}% tolerance. Proceeding.")
                return True, final_dry, final_wet
            else:
                self.add_message(f"Warning: RH deviation {deviation:.1f}% exceeds tolerance {stabilization_tolerance}%. Proceeding anyway.")
                return False, final_dry, final_wet
        else:
            self.add_message("Warning: No RH reading available. Proceeding anyway.")
            return False, dry_flow, wet_flow
    

    def run_automated_experiment(self, direction: str, steps: int, duration: float, 
                               max_flow: float, control_interval: float, rh_tolerance: float,
                               stabilization_time: float, stabilization_tolerance: float,
                               on_data: Optional[Callable[[Dict], None]] = None):
        self.running = True
        
        # Start logging
        self.logger.start_new_log(self.log_fields)
        
        try:
            msg = f"Starting experiment: {direction}, {steps} steps, {duration} min"
            self.add_message(msg)
            
            # Define RH targets based on direction
            if direction == "up":
                targets = [i * (100.0 / steps) for i in range(steps + 1)]
            else:
                targets = [100.0 - (i * (100.0 / steps)) for i in range(steps + 1)]
                
            step_duration_sec = (duration * 60) / len(targets)
            
            for target_rh in targets:
                if not self.running:
                    break
                    
                msg = f"\n=== Target RH: {target_rh:.1f}% ==="
                self.add_message(msg)
                
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
                msg = f"    Holding for {step_duration_sec:.1f} seconds..."
                self.add_message(msg)
                start_hold = time.time()
                while (time.time() - start_hold) < step_duration_sec and self.running:
                    cycle_start = time.time()

                    # Read and Log (protected)
                    try:
                        data = self.read_all_sensors()
                    except Exception as e:
                        self.add_message(f"Error reading sensors during hold: {e}")
                        data = {}

                    try:
                        self.logger.log_data(data)
                    except Exception as e:
                        self.add_message(f"Logger error during hold: {e}")

                    if on_data:
                        try:
                            on_data(data)
                        except Exception as e:
                            self.add_message(f"on_data callback error during hold: {e}")

                    # Wait for next control interval
                    elapsed = time.time() - cycle_start
                    if elapsed < control_interval:
                        time.sleep(control_interval - elapsed)
        finally:
            self.running = False
            self.logger.close()
            msg = "Experiment finished."
            self.add_message(msg)

    def update_settings(self, new_config: Dict):
        self.config.update(new_config)
        
        # Update logger settings
        log_dir = new_config.get('log_dir', 'data')
        log_prefix = new_config.get('log_prefix', 'nsim_log')
        
        if self.logger is not None:
            self.logger.output_dir = Path(log_dir)
            self.logger.filename_prefix = log_prefix
            self.logger.output_dir.mkdir(parents=True, exist_ok=True)
