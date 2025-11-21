"""
Configuration file for N-SIM Microscope Control System

Edit this file to match your hardware setup.
"""

CONFIG = {
    # Data logging settings
    'log_dir': 'data',
    'log_prefix': 'nsim_log',
    
    # Plotting settings
    'max_plot_points': 500,  # Maximum number of points to display
    'plot_update_interval': 1000,  # Update interval in milliseconds
    
    # Serial port settings
    # Dry air mass flow controller
    'dry_mfc_enabled': True,
    'dry_mfc_port': 'COM6',  # Change to your port (e.g., 'COM3' on Windows)
    'dry_mfc_address': 1,
    
    # Wet air mass flow controller
    'wet_mfc_enabled': True,
    'wet_mfc_port': 'COM7',  # Change to your port (e.g., 'COM4' on Windows)
    'wet_mfc_address': 247,
    
    # DewMaster hygrometer
    'hygrometer_enabled': True,
    'hygrometer_port': 'COM3',  # Change to your port (e.g., 'COM5' on Windows)
    
    # Communication settings
    'mfc_baudrate': 9600,
    'hygrometer_baudrate': 9600,

    # Thermocouple (USB) settings
    't_probe_enabled': True,
    't_probe_vendor_id': 0x2177,
    't_probe_product_id': 0x0004,
}
