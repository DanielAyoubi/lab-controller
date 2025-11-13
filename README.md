# N-SIM Microscope Environmental Control System

A Python-based control and monitoring system for Nikon SIM (Structured Illumination Microscopy) microscope environmental parameters.

## Features

- **Mass Flow Control**: Interface with 2 Vögtlin mass flow controllers
  - Dry air flow controller
  - Wet air flow controller
  - Read current flow rates
  - Set flow rate setpoints
  
- **Environmental Monitoring**: Interface with DewMaster chilled mirror hygrometer
  - Ambient temperature measurement
  - Dewpoint temperature measurement
  - Relative humidity measurement

- **Data Logging**: Automatic CSV logging of all parameters with timestamps

- **Real-time Visualization**: Dynamic plots with live updates showing:
  - Mass flow rates (actual vs setpoint)
  - Temperature trends
  - Humidity levels

## Installation

### Requirements

- Python 3.7 or higher
- Serial ports for device communication

### Setup

1. Clone this repository:
```bash
git clone https://github.com/DanielAyoubi/N-SIM-Microscope.git
cd N-SIM-Microscope
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Configure your hardware:
Edit `config.py` to match your serial port configuration:
```python
CONFIG = {
    'dry_mfc_port': '/dev/ttyUSB0',  # Your dry air MFC port
    'wet_mfc_port': '/dev/ttyUSB1',  # Your wet air MFC port
    'hygrometer_port': '/dev/ttyUSB2',  # Your hygrometer port
    # ... other settings
}
```

## Usage

### Basic Usage

Run the control system with default settings:
```bash
python main.py
```

### Command Line Options

```bash
python main.py --help
```

Available options:
- `--config CONFIG`: Path to configuration file (default: config.py)
- `--dry-mfc PORT`: Dry air MFC serial port
- `--wet-mfc PORT`: Wet air MFC serial port
- `--hygrometer PORT`: Hygrometer serial port
- `--interval SECONDS`: Sampling interval in seconds (default: 1.0)
- `--dry-flow RATE`: Set dry air flow rate in ml/min
- `--wet-flow RATE`: Set wet air flow rate in ml/min

### Examples

1. **Start monitoring with custom ports:**
```bash
python main.py --dry-mfc /dev/ttyUSB0 --wet-mfc /dev/ttyUSB1 --hygrometer /dev/ttyUSB2
```

2. **Set flow rates and start monitoring:**
```bash
python main.py --dry-flow 100.0 --wet-flow 50.0
```

3. **Use custom sampling interval:**
```bash
python main.py --interval 2.0
```

4. **Run demo with simulated data (no hardware required):**
```bash
python demo.py
```

5. **Explore API usage examples:**
```bash
python examples.py
```

### Stopping the System

Press `Ctrl+C` to gracefully stop monitoring and disconnect from devices.

## Project Structure

```
N-SIM-Microscope/
├── main.py                 # Main application entry point
├── config.py              # Configuration file
├── demo.py                # Demo with simulated data (no hardware needed)
├── examples.py            # API usage examples
├── requirements.txt       # Python dependencies
├── README.md             # This file
├── src/
│   ├── devices/          # Device interfaces
│   │   ├── vogtlin_mfc.py      # Vögtlin MFC interface
│   │   └── dewmaster.py        # DewMaster hygrometer interface
│   ├── logging/          # Data logging
│   │   └── data_logger.py      # CSV logging functionality
│   └── visualization/    # Plotting and visualization
│       └── plotter.py          # Real-time plotting
├── tests/                # Unit tests
│   └── test_system.py        # Test suite
└── data/                 # Log files directory (created automatically)
```

## Data Format

Log files are saved in CSV format with the following columns:
- `timestamp`: ISO format timestamp
- `dry_flow`: Dry air actual flow rate (ml/min)
- `dry_setpoint`: Dry air setpoint (ml/min)
- `wet_flow`: Wet air actual flow rate (ml/min)
- `wet_setpoint`: Wet air setpoint (ml/min)
- `ambient_temp`: Ambient temperature (°C)
- `dewpoint_temp`: Dewpoint temperature (°C)
- `relative_humidity`: Relative humidity (%)

## Troubleshooting

### Serial Port Issues

**Linux:**
- Check available ports: `ls /dev/tty*`
- Add user to dialout group: `sudo usermod -a -G dialout $USER`
- Log out and log back in for changes to take effect

**Windows:**
- Check Device Manager for COM port numbers
- Ensure drivers are installed for USB-serial adapters

### Connection Errors

If devices fail to connect:
1. Verify correct serial port names in configuration
2. Check that devices are powered on
3. Verify baud rates match device settings (default: 9600)
4. Ensure no other software is using the serial ports

### Testing Without Hardware

To test the system without physical devices:
1. Run the demo: `python demo.py`
2. Explore the examples: `python examples.py`
3. Run unit tests: `python tests/test_system.py`

## Device Communication Protocols

### Vögtlin MFC
- Default baud rate: 9600
- Protocol: ASCII commands over RS-232/RS-485
- Commands are sent with device address prefix

### DewMaster Hygrometer
- Default baud rate: 9600
- Protocol: ASCII commands over RS-232
- Returns comma-separated values for readings

**Note:** Communication protocols may vary by model. Adjust the device interface files if needed for your specific hardware.

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## License

This project is provided as-is for research and educational purposes.

## Acknowledgments

Developed for environmental control monitoring of Nikon SIM microscope setups.