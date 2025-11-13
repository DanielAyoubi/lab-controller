import time
from datetime import datetime
from typing import Optional, Dict

from src.devices.vogtlin_mfc import VogtlinMFC
from src.devices.dewmaster import DewMasterHygrometer
from src.devices.temperature_probe import TemperatureProbe
from src.logging.data_logger import DataLogger
from src.visualization.plotter import DynamicPlotter


class Controller:
    def __init__(self, config: Dict):
        self.config = config
        self.running = False
        
        # Initialize devices
        self.dry_mfc: Optional[VogtlinMFC] = None
        self.wet_mfc: Optional[VogtlinMFC] = None
        self.hygrometer: Optional[DewMasterHygrometer] = None
        self.t_probe: Optional[TemperatureProbe] = None
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
            'dry_setpoint',
            'wet_flow',
            'wet_setpoint',
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
            self.hygrometer = DewMasterHygrometer(
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
            self.t_probe = TemperatureProbe(
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
        """
        Read data from all sensors.
        
        Returns:
            Dictionary containing all sensor readings
        """
        data = {
            'timestamp': datetime.now().isoformat(),
            'dry_flow': None,
            'dry_setpoint': None,
            'wet_flow': None,
            'wet_setpoint': None,
            'cell_temp': None,
            'ambient_temp': None,
            'dewpoint_temp': None,
            'relative_humidity': None
        }
        
        # Read dry MFC
        if self.dry_mfc:
            data['dry_flow'] = self.dry_mfc.get_flow()
            data['dry_setpoint'] = self.dry_mfc.get_setpoint()
        
        # Read wet MFC
        if self.wet_mfc:
            data['wet_flow'] = self.wet_mfc.get_flow()
            data['wet_setpoint'] = self.wet_mfc.get_setpoint()
        
        # Read hygrometer
        if self.hygrometer:
            readings = self.hygrometer.get_readings()
            if readings:
                data['ambient_temp'] = readings.get('ambient_temp')
                data['dewpoint_temp'] = readings.get('dewpoint_temp')
                data['relative_humidity'] = readings.get('relative_humidity')

        if self.t_probe:
            data['cell_temp'] = self.T_probe.get_temperature()
        
        return data
    
    def set_flow_rates(self, dry_flow: Optional[float] = None, wet_flow: Optional[float] = None):
        """
        Set flow rates for MFCs.
        
        Args:
            dry_flow: Desired dry air flow rate (ml/min)
            wet_flow: Desired wet air flow rate (ml/min)
        """
        if dry_flow is not None and self.dry_mfc:
            if self.dry_mfc.set_flow(dry_flow):
                print(f"Set dry air flow to {dry_flow} ml/min")
            else:
                print("Failed to set dry air flow")
        
        if wet_flow is not None and self.wet_mfc:
            if self.wet_mfc.set_flow(wet_flow):
                print(f"Set wet air flow to {wet_flow} ml/min")
            else:
                print("Failed to set wet air flow")
    
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
                print(f"  Dry Air:  {data['dry_flow']:.2f} ml/min (SP: {data['dry_setpoint']:.2f})")
                print(f"  Wet Air:  {data['wet_flow']:.2f} ml/min (SP: {data['wet_setpoint']:.2f})")
                print(f"  Ambient:  {data['ambient_temp']:.2f} °C")
                print(f"  Dewpoint: {data['dewpoint_temp']:.2f} °C")
                print(f"  Humidity: {data['relative_humidity']:.1f} %\n")
                
                # Wait for next sample
                time.sleep(interval)
                
        except KeyboardInterrupt:
            print("\n\nMonitoring stopped by user")
        finally:
            self.running = False
            self.plotter.stop()
    
    def stop(self):
        """Stop the control system"""
        self.running = False
        self.disconnect_devices()
