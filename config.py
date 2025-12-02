CONFIG = {
    # Data logging settings
    "log_dir": "data",
    "log_prefix": "nsim_log",

    # Plotting settings
    "max_plot_points": 500,  # Maximum number of points to display
    "plot_update_interval": 1000,  # Update interval in milliseconds

    # Serial port settings

    # Dry air mass flow controller
    "dry_mfc_enabled": True,
    "dry_mfc_port": "COM6",  # Change to your port (e.g., 'COM3' on Windows)
    "dry_mfc_address": 1,

    # Wet air mass flow controller
    "wet_mfc_enabled": True,
    "wet_mfc_port": "COM7",  # Change to your port (e.g., 'COM4' on Windows)
    "wet_mfc_address": 247,

    # DewMaster hygrometer
    "hygrometer_enabled": True,
    "hygrometer_port": "COM9",  # Change to your port (e.g., 'COM5' on Windows)

    # Communication settings
    "mfc_baudrate": 9600,
    "hygrometer_baudrate": 19200,

    # Thermocouple (USB) settings
    "t_probe_enabled": True,
    "t_probe_vendor_id": 0x2177,
    "t_probe_product_id": 0x0004,

    # Relative humidity control settings
    "rh_control_source": "cell_calc",  # Options: "dewmaster" (DewMaster native), "calculated" (dewpoint+ambient), "cell_calc" (dewpoint+cell)
    
    # Automated experiment settings
    "experiment_direction": "up",       # "up" for 0% to 100% RH, "down" for 100% to 0% RH
    "experiment_steps": 10,             # Number of steps between start and end RH
    "experiment_duration": 60.0,        # Total experiment duration in minutes
    "max_flow": 2.0,                   # Maximum/target total flow rate (dry + wet) in L/min
    "control_interval": 5.0,           # Time between control updates in seconds
    "rh_tolerance": 5.0,               # Maximum allowed deviation from target RH before adjustment (%)
    
    # Experiment stabilization settings
    "stabilization_time": 60.0,        # Maximum time to stabilize flows at each step (seconds)
    "stabilization_tolerance": 2.0,    # RH tolerance for considering flows stable (%)
}
