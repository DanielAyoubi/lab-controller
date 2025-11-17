import time
from src.cli.parser import parse_cli_args
from src.devices.controller import Controller


def main():
    args = parse_cli_args()

    # Load configuration from config file
    config = {}
    try:
        import importlib.util

        spec = importlib.util.spec_from_file_location("config", args.config)
        config_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(config_module)
        if hasattr(config_module, "CONFIG"):
            config = config_module.CONFIG.copy()
        else:
            print(f"Warning: Config file {args.config} does not contain CONFIG dictionary")
            print("Using empty configuration\n")
    except FileNotFoundError:
        print(f"Config file not found: {args.config}")
        print("Please create a config.py file with your settings\n")
        return
    except Exception as e:
        print(f"Error loading config: {e}")
        print("Cannot continue without configuration\n")
        return

    # Create control system
    print("=" * 60)
    print("N-SIM Microscope Environmental Control System")
    print("=" * 60)

    controller = Controller(config)

    # Connect to devices
    if not controller.connect_devices():
        print("\nWarning: Some devices failed to connect")
        response = input("Continue anyway? (y/n): ")
        if response.lower() != "y":
            print("Exiting...")
            return

    # Check if running automated experiment
    if args.experiment:
        # Run automated experiment
        try:
            controller.run_automated_experiment(
                direction=args.direction,
                steps=args.steps,
                duration=args.duration,
                max_flow=args.max_flow,
                control_interval=args.control_interval,
                rh_tolerance=args.rh_tolerance
            )
        finally:
            controller.stop()
            print("\nSystem shutdown complete")
    else:
        # Set flow rates if specified
        if args.dry_flow is not None or args.wet_flow is not None:
            controller.set_flow_rates(
                dry_flow=args.dry_flow, 
                wet_flow=args.wet_flow,
                max_flow=args.max_flow
            )
            time.sleep(1)  # Wait for setpoint to stabilize

        # Start monitoring
        try:
            controller.start_monitoring(interval=args.interval)
        finally:
            controller.stop()
            print("\nSystem shutdown complete")


if __name__ == "__main__":
    main()
