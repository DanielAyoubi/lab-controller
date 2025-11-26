import time
import argparse
from src.cli.parser import parse_cli_args
from src.devices.controller import Controller


def load_config(config_path: str) -> dict:
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location("config", config_path)
        config_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(config_module)
        
        if hasattr(config_module, "CONFIG"):
            return config_module.CONFIG.copy()
        else:
            print(f"Warning: Config file {config_path} does not contain CONFIG dictionary")
            print("Using empty configuration\n")
            return {}
            
    except FileNotFoundError:
        print(f"Config file not found: {config_path}")
        print("Please create a config.py file with your settings\n")
        raise SystemExit(1)
        
    except Exception as e:
        print(f"Error loading config: {e}")
        print("Cannot continue without configuration\n")
        raise SystemExit(1)


def setup_controller(config: dict) -> Controller:
    # Display system information
    print("=" * 60)
    print("N-SIM Microscope Environmental Control System")
    print("=" * 60)
    print(f"RH Control Source: {config.get('rh_control_source', 'cell_calc')}")
    print("=" * 60)

    # Create controller
    controller = Controller(config)

    # Connect to devices
    if not controller.connect_devices():
        print("\nWarning: Some devices failed to connect")
        response = input("Continue anyway? (y/n): ")
        if response.lower() != "y":
            print("Exiting...")
            raise SystemExit(1)
    
    return controller


def run_experiment(controller: Controller, config: dict):
    # Run automated humidity ramp experiment.
    controller.run_automated_experiment(
        direction=config.get('experiment_direction', 'up'),
        steps=config.get('experiment_steps', 10),
        duration=config.get('experiment_duration', 60.0),
        max_flow=config.get('max_flow', 2.0),
        control_interval=config.get('control_interval', 5.0),
        rh_tolerance=config.get('rh_tolerance', 5.0),
        stabilization_time=config.get('stabilization_time', 60.0),
        stabilization_tolerance=config.get('stabilization_tolerance', 2.0)
    )


def run_monitoring(controller: Controller, config: dict, args: argparse.Namespace):
    # Run continuous monitoring mode with optional manual flow control.
    # Set flow rates if specified
    if args.dry_flow is not None or args.wet_flow is not None:
        controller.set_flow_rates(
            dry_flow=args.dry_flow, 
            wet_flow=args.wet_flow,
            max_flow=config.get('max_flow', 2.0)
        )
        time.sleep(3)  # Wait for setpoint to stabilize

    # Start monitoring
    controller.start_monitoring(interval=config.get('control_interval', 5))


def main():
    args = parse_cli_args()
    config = load_config(args.config)

    controller = setup_controller(config)

    # Run the appropriate mode
    try:
        if args.experiment:
            run_experiment(controller, config)
        else:
            run_monitoring(controller, config, args)
    finally:
        controller.stop()
        print("\nSystem shutdown complete")


if __name__ == "__main__":
    main()
