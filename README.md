# N-SIM Environmental Control System

A desktop application for controlling the environmental humidity chamber of an N-SIM microscope. It manages two Vögtlin mass flow controllers (dry/wet air), a DewMaster chilled-mirror hygrometer, and a Julabo chiller to regulate relative humidity (RH).

## Features

- **Mass Flow Control** — Vögtlin Modbus RTU MFCs for dry and wet air; manual and ramped setpoints
- **Hygrometer** — DewMaster serial driver; dew-point, ambient temperature, and RH readings
- **Chiller** — Julabo ASCII serial driver; temperature setpoint and external probe readback
- **PID RH Control** — Automatic wet/dry flow ratio adjustment to hold a target RH; settling guard, deadband, dynamic step clamping, and optional D term
- **Automated RH Ramp Experiment** — Steps wet-flow ratio from 0 → 100 % (or reverse) with configurable hold time, pre-conditioning phase, and RH stop limits; saves CSV log and PNG summary plot
- **Real-time Plot** — 3-panel live chart: flow rates, temperatures, RH
- **CSV Data Logging** — Timestamped CSV written to date-organised sub-folders; separate files for background monitoring and experiments

## Requirements

- Python 3.10+
- Windows (COM port names; Linux/macOS would need minor port-name changes)
- Serial/USB adapters for each device

## Setup

1. **Clone the repository:**
   ```
   git clone <repo-url>
   cd lab-controller
   ```

2. **Create / activate a virtual environment and install dependencies:**
   ```
   python -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   ```

3. **Set machine-specific device settings:**

   Copy the template and edit it for this machine:
   ```
   cp src\configs\local_config.example.py src\configs\local_config.py
   ```
   Then open `src/configs/local_config.py` and fill in the correct values:
   ```python
   LOCAL_CONFIG = {
       # COM ports
       "dry_mfc_port":    "COM6",
       "wet_mfc_port":    "COM7",
       "hygrometer_port": "COM9",
       "chiller_port":    "COM8",
       # Baud rates
       "mfc_baudrate":        9600,
       "hygrometer_baudrate": 19200,
       "chiller_baudrate":    9600,
       # Modbus addresses
       "dry_mfc_address": 1,
       "wet_mfc_address": 247,
       # Enable / disable devices
       "dry_mfc_enabled":    True,
       "wet_mfc_enabled":    True,
       "hygrometer_enabled": True,
       "chiller_enabled":    True,
   }
   ```
   `local_config.py` is gitignored — it stays on the machine permanently and is never committed.

4. **Run the application:**
   ```
   python main.py
   ```

## Configuration

Configuration is split across two files:

- **`src/configs/config.py`** (committed) — application and experiment defaults. Edit this to change experiment behaviour for everyone.
- **`src/configs/local_config.py`** (gitignored) — all device-specific settings for this machine. Keys here override `config.py` at startup.

Settings can also be changed at runtime through the **Settings** dialog (General / Devices / Experiment tabs) — changes are held in memory for the session only.

### `local_config.py` keys (device settings)

| Key | Default | Description |
|-----|---------|-------------|
| `dry_mfc_port` / `wet_mfc_port` | — | COM ports for Vögtlin MFCs |
| `hygrometer_port` | — | COM port for DewMaster |
| `chiller_port` | — | COM port for Julabo chiller |
| `mfc_baudrate` | 9600 | Baud rate for both MFCs |
| `hygrometer_baudrate` | 19200 | Baud rate for the hygrometer |
| `chiller_baudrate` | 9600 | Baud rate for the chiller |
| `dry_mfc_address` / `wet_mfc_address` | 1 / 247 | Modbus unit addresses |
| `dry/wet_mfc_enabled` | True | Enable/disable each MFC |
| `hygrometer_enabled` / `chiller_enabled` | True | Enable/disable hygrometer / chiller |

### `config.py` keys (application & experiment settings)

| Key | Default | Description |
|-----|---------|-------------|
| `control_interval` | 5000 ms | Sensor poll period |
| `max_flow` | 2.0 L/min | Total flow used during experiments |
| `log_dir` / `log_prefix` | `data` / `nsim_log` | CSV output directory and filename prefix |
| `experiment_step_size` | 5.0 % | Wet-flow increment per experiment step |
| `experiment_hold_time` | 180 s | Wait time at each step |
| `experiment_rh_lower` / `experiment_rh_upper` | 0 / 90 % | RH limits for experiment stop and pre-conditioning |
| `rh_kp` / `rh_ki` / `rh_kd` | 0.02 / 0.001 / 0.05 | PID gains (set `rh_kd = 0` to disable D term) |
| `rh_deadband` | 1.0 % | Minimum RH error that triggers a correction |
| `rh_settling_time` | 200 s | Max wait after a full-scale flow change |
| `rh_settling_time_min` | 30 s | Min wait regardless of step size |
| `rh_max_step` | 0.05 | Wet-ratio change ceiling at 100 % error |

## Project Structure

```
lab-controller/
├── main.py                          # Entry point — creates QApplication and MainWindow
├── requirements.txt
├── src/
│   ├── configs/
│   │   ├── config.py                # Default configuration (committed)
│   │   ├── local_config.py          # Machine-specific device settings (gitignored)
│   │   └── local_config.example.py  # Template for local_config.py
│   ├── devices/
│   │   ├── controller.py            # Central orchestrator: device refs, PI loop, experiment runner
│   │   ├── vogtlin_mfc.py           # Modbus RTU driver (minimalmodbus, big-endian 32-bit floats)
│   │   ├── hygrometer.py            # DewMaster serial driver (Magnus formula RH)
│   │   ├── chiller.py               # Julabo ASCII serial driver
│   │   └── pid_controller.py        # RH PID with settling guard, deadband, dynamic step cap
│   ├── gui/
│   │   ├── main_window.py           # Main window: left panel controls + right panel plot
│   │   ├── workers.py               # PollWorker, FlowRampWorker, ExperimentWorker (QThread)
│   │   ├── settings_dialog.py       # Three-tab settings dialog (General / Devices / Experiment)
│   │   └── widgets/
│   │       └── plot_widget.py       # RealTimePlotWidget — 3 shared-x Matplotlib subplots
│   └── utility/
│       ├── data_logger.py           # CSV logger with date sub-folders, 8 KB write buffer
│       ├── plot_saver.py            # Saves smoothed 3-panel PNG at experiment end
│       ├── compute_RH.py            # Magnus formula: RH from dew-point and ambient temp
│       └── update_settings.py       # Applies runtime settings changes to controller/logger/PID
├── tests/                           # pytest test suite
└── data/                            # Log output directory (created automatically)
```

## Data Logging

CSV files are written to `<log_dir>/<DD_MM_YYYY>/<prefix>_<timestamp>.csv`. Columns:

| Column | Description |
|--------|-------------|
| `timestamp` | ISO 8601 timestamp |
| `dry_flow` | Dry MFC actual flow (L/min) |
| `wet_flow` | Wet MFC actual flow (L/min) |
| `dry_flow_setpoint` | Dry MFC setpoint (L/min) |
| `wet_flow_setpoint` | Wet MFC setpoint (L/min) |
| `hygrometer_temp` | Hygrometer ambient temperature (°C) |
| `dewpoint_temp` | Dew-point temperature (°C) |
| `rh_hygrometer` | RH computed from hygrometer ambient temp |
| `rh_chiller` | RH computed from chiller external probe temp |
| `chiller_temp` | Chiller external probe temperature (°C) |
| `chiller_setpoint` | Chiller temperature setpoint (°C) |

At experiment end a smoothed PNG summary plot is saved alongside the CSV.

## Device Protocols

### Vögtlin MFCs
- Modbus RTU over RS-485
- 32-bit floats packed across two consecutive 16-bit registers, big-endian byte order
- Default baud rate: 9600; addresses: dry = 1, wet = 247

### DewMaster Hygrometer
- RS-232 serial, 19200 baud
- Sends `P\r`; parses `DP / AT / RH` response line
- RH re-derived from dew-point via the Magnus formula

### Julabo Chiller
- RS-232 serial, 9600 baud
- ASCII commands: `in_pv_02` (external temp), `out_sp_00 <val>` (setpoint), `out_mode_05 1/0` (start/stop), terminated with `\r\n`

## Troubleshooting

**Device not connecting** — Check the COM port name in `local_config.py` (or the Settings → Devices dialog), confirm the device is powered on, and ensure no other software (e.g. PuTTY, another Python process) is holding the port open.

**Wrong readings after settings change** — Port and baud rate changes only take effect after disconnecting and reconnecting devices.

**Experiment never reaches stability** — Increase `experiment_stability_timeout` or widen `rh_deadband` if the hygrometer is noisy. The pre-conditioning phase will time out and proceed after the timeout regardless.
