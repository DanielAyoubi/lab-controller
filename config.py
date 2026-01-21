CONFIG = {
    # Data logging settings
    "log_dir": "data",
    "log_prefix": "nsim_log",

    # Plotting settings
    "max_plot_points": 500,  # Maximum number of points to display

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

    # Julabo Chiller
    "chiller_enabled": True,
    "chiller_port": "COM8", # Change to your port

    # Communication settings
    "mfc_baudrate": 9600,
    "chiller_baudrate": 9600,
    "hygrometer_baudrate": 19200,

    # Automated experiment settings
    "experiment_direction": "up",       # "up" or "down"
    "experiment_min_rh": 0.0,
    "experiment_max_rh": 100.0,
    "experiment_steps": 10,             # Number of steps between start and end RH
    "max_flow": 1.0,                   # Maximum/target total flow rate (dry + wet) in L/min
    "control_interval": 5000,  # Update interval in milliseconds
    "rh_tolerance": 1.0,               # Maximum allowed deviation from target RH (%)
    
    # Experiment stabilization settings
    "stabilization_time": 600.0,        # Maximum timeout per step (seconds)
    "stabilization_tolerance": 0.5,    # RH fluctuation tolerance for considering flows stable (%)
}
