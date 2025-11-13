"""
N-SIM Microscope Control System - Main Application

This is the main control application that integrates all components:
- Vögtlin mass flow controllers (dry and wet air)
- DewMaster hygrometer
- Data logging
- Dynamic visualization
"""

import time
import signal
import sys

from src.cli.parser import parse_cli_args
from src.devices.controller import Controller


def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully"""
    print("\n\nShutdown signal received...")
    sys.exit(0)


def main():
    args = parse_cli_args()
    
    # Build configuration
    config = {
        'log_dir': 'data',
        'log_prefix': 'nsim_log',
        'max_plot_points': 500,
        'plot_update_interval': 1000,
        'mfc_baudrate': 9600,
        'hygrometer_baudrate': 9600
    }
    
    # Load config file if it exists
    try:
        if args.config:
            import importlib.util
            spec = importlib.util.spec_from_file_location("config", args.config)
            config_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(config_module)
            if hasattr(config_module, 'CONFIG'):
                config.update(config_module.CONFIG)
    except FileNotFoundError:
        print(f"Config file not found: {args.config}")
        print("Using default configuration and command-line arguments\n")
    except Exception as e:
        print(f"Error loading config: {e}")
        print("Using default configuration and command-line arguments\n")
    
    # Create control system
    print("=" * 60)
    print("N-SIM Microscope Environmental Control System")
    print("=" * 60)
    
    controller = Controller(config)
    
    # Register signal handler
    signal.signal(signal.SIGINT, signal_handler)
    
    # Connect to devices
    if not controller.connect_devices():
        print("\nWarning: Some devices failed to connect")
        response = input("Continue anyway? (y/n): ")
        if response.lower() != 'y':
            print("Exiting...")
            return
    
    # Set flow rates if specified
    if args.dry_flow is not None or args.wet_flow is not None:
        controller.set_flow_rates(args.dry_flow, args.wet_flow)
        time.sleep(1)  # Wait for setpoint to stabilize
    
    # Start monitoring
    try:
        controller.start_monitoring(interval=args.interval)
    finally:
        controller.stop()
        print("\nSystem shutdown complete")


if __name__ == '__main__':
    main()
