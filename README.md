# N-SIM Environmental Control System

A desktop application for controlling the environmental humidity chamber of an N-SIM microscope. It manages two Vögtlin mass flow controllers (dry/wet air), a DewMaster chilled-mirror hygrometer, and a Julabo chiller to regulate relative humidity (RH).

## Features

- **Mass Flow Control** — Vögtlin Modbus RTU MFCs for dry and wet air; manual and ramped setpoints
- **Hygrometer** — DewMaster serial driver; dew-point, ambient temperature, and RH readings
- **Chiller** — Julabo ASCII serial driver; temperature setpoint and external probe readback
- **Feedforward + PI RH Control** — Automatic wet/dry flow ratio adjustment to hold a target RH; a static feedforward model jumps straight to the right ratio (fast settling) while a gentle PI(D) term trims the residual, with a dead-time-aware settling guard and deadband. The feedforward is calibrated from a flow-ramp log (see below)
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

3. **Set up the config file for this machine:**

   Open `src/configs/config.json` and set the COM ports, baud rates, addresses,
   and enable flags for this machine (plus any experiment defaults you want to change):
   ```json
   {
     "dry_mfc_port": "COM6",
     "wet_mfc_port": "COM7",
     "hygrometer_port": "COM9",
     "chiller_port": "COM8",
     "mfc_baudrate": 9600,
     "hygrometer_baudrate": 19200,
     "chiller_baudrate": 9600,
     "dry_mfc_address": 1,
     "wet_mfc_address": 247,
     "dry_mfc_enabled": true,
     "wet_mfc_enabled": true,
     "hygrometer_enabled": true,
     "chiller_enabled": true
   }
   ```

4. **Run the application:**
   ```
   python main.py
   ```

## Building a standalone executable

To run the app without Python installed, package it into a single Windows
executable with PyInstaller:

```
build.bat
```

This installs PyInstaller (if needed), builds from `LabController.spec`, and
produces:

| File | Purpose |
|------|---------|
| `dist\LabController.exe` | The application — double-click to run |
| `dist\config.json` | Editable config; set COM ports / settings here |

**Distribute both files together** (keep them in the same folder). On startup the
exe prefers the `config.json` sitting next to it, so device ports can be changed
without rebuilding. A default copy is also bundled inside the exe as a fallback.

> To build manually instead of using the script:
> `.venv\Scripts\pyinstaller --noconfirm --clean LabController.spec`

## Configuration

All settings live in a single JSON file, **`src/configs/config.json`**. It holds
both the machine-specific device settings and the application/experiment defaults.

Settings can also be changed at runtime through the **Settings** dialog (General / Devices / Experiment tabs) — changes are held in memory for the session only and are not written back to `config.json`.

### Device settings

| Key | Default | Description |
|-----|---------|-------------|
| `dry_mfc_port` / `wet_mfc_port` | — | COM ports for Vögtlin MFCs |
| `hygrometer_port` | — | COM port for DewMaster |
| `chiller_port` | — | COM port for Julabo chiller |
| `mfc_baudrate` | 9600 | Baud rate for both MFCs |
| `hygrometer_baudrate` | 19200 | Baud rate for the hygrometer |
| `chiller_baudrate` | 9600 | Baud rate for the chiller |
| `dry_mfc_address` / `wet_mfc_address` | 1 / 247 | Modbus unit addresses |
| `dry/wet_mfc_enabled` | true | Enable/disable each MFC |
| `hygrometer_enabled` / `chiller_enabled` | true | Enable/disable hygrometer / chiller |

### Logging & plot

| Key | Default | Description |
|-----|---------|-------------|
| `log_dir` / `log_prefix` | `data` / `nsim_log` | CSV output directory and filename prefix |
| `max_plot_points` | 500 | Max points kept in the live plot before old ones drop off |
| `control_interval` | 2000 ms | Sensor poll period (**milliseconds**) |

### Flow

| Key | Default | Description |
|-----|---------|-------------|
| `max_flow` | 1.0 L/min | Total combined flow; dry + wet always sums to this during experiments |
| `flow_ramp_step` | 0.05 L/min | Increment per step when ramping manual flow changes (1 s/step) |

### Experiment

| Key | Default | Description |
|-----|---------|-------------|
| `experiment_mode` | `flow` | `flow` = open-loop wet-flow ramp; `rh` = PI-controlled RH ramp |
| `experiment_hold_time` | 180 s | Wait time collecting data at each step |
| `experiment_flow_start` / `_end` / `_step` | 0.0 / 2.0 / 0.1 L/min | Flow-mode wet-flow ramp range and increment |
| `experiment_rh_lower` / `_upper` / `experiment_rh_step` | 0 / 90 / 5 % | RH-mode ramp range and increment (also the pre-conditioning bounds) |
| `experiment_stability_readings` | 5 | RH-mode: consecutive in-deadband readings required for "stable" |
| `experiment_stability_timeout` | 800 s | RH-mode: max wait for stability before moving on |

### RH control loop — feedforward

The controller commands the wet-flow ratio as **`wet_ratio = rh_ff_gain · (target_RH / 100) + rh_ff_offset`** (the feedforward), then trims the small remaining error with PI(D). The feedforward is what makes settling fast; calibrate it with the tool described in [Calibrating the RH feedforward](#calibrating-the-rh-feedforward).

| Key | Default | Description |
|-----|---------|-------------|
| `rh_ff_gain` | 1.0 | Feedforward slope. Physics gives ≈ 1.0 (RH ≈ 100 · wet_ratio); raise it if the bubbler under-saturates |
| `rh_ff_offset` | 0.0 | Feedforward intercept (wet-ratio offset). Usually ≈ 0 |
| `rh_dead_time` | 25 s | Transport delay between a flow change and the hygrometer registering it. Floors the wait between corrections so each move is judged after its effect arrives |
| `rh_trim_limit` | 0.6 | Ceiling on the feedback wet-ratio added to the feedforward (prevents a noisy reading flinging the ratio) |

### RH control loop — PI(D) trim & guards

These act only on the *residual* error the feedforward leaves behind, so the gains are deliberately gentle.

| Key | Default | Description |
|-----|---------|-------------|
| `rh_kp` | 0.01 | Proportional trim gain |
| `rh_ki` | 0.002 | Integral trim gain — accumulates the (≈ constant) calibration bias; carried across setpoints |
| `rh_kd` | 0.05 | Derivative gain on the measurement (set `0.0` to disable the D term) |
| `rh_derivative_filter_tau` | 30 s | Low-pass filter time constant for the D term |
| `rh_integral_limit` | 0.5 | Anti-windup ceiling on the integral accumulator |
| `rh_deadband` | 1.0 % | Ignore RH errors smaller than this to avoid chasing sensor noise |
| `rh_settling_time` | 200 s | Max wait after a full-scale flow change before the next correction |
| `rh_settling_time_min` | 10 s | Min wait after any flow change (floored at `rh_dead_time`) |

## Calibrating the RH feedforward

The RH controller assumes a **static inverse model** of the plant: with a saturating
bubble bath on the wet line and dry gas on the other, the steady-state RH is, to
first order, just the mixing ratio — so the wet-flow ratio needed for a target RH is

```
wet_ratio = rh_ff_gain · (target_RH / 100) + rh_ff_offset
```

`rh_ff_gain ≈ 1` and `rh_ff_offset ≈ 0` are the physics defaults, but a real bubbler
slightly under-saturates and the probe has a small offset, so the true line is a bit
off. Calibrating these two numbers lets the feedforward land the **first** flow move
within ~1 % RH instead of crawling there, which is the bulk of the speed-up.

### How it works

A **flow-mode** experiment steps the wet flow open-loop and holds at each step, so the
settled RH at every step is a clean `(RH, wet_ratio)` sample of the map above. The
calibration tool:

1. Reads the experiment's CSV log.
2. Groups the rows into steps (by changes in the commanded wet ratio) and averages the
   **settled tail** of each step (last 50 % of its rows), discarding the transient.
3. Least-squares fits the line `wet_ratio = gain · (RH / 100) + offset` and reports the
   two values plus the fit quality (R²).

### How to use it

1. Run a **flow-mode** ramp (`experiment_mode: "flow"`, e.g. wet flow 0 → `max_flow`)
   so the chamber visits a spread of RH values and settles at each.
2. Run the tool on the resulting log:

   ```
   .venv\Scripts\python -m src.utility.calibrate_feedforward
   ```

   With no arguments it picks the most recent `RH_ramp_*.csv` under `data/`. Pass a
   path to choose a specific log:

   ```
   .venv\Scripts\python -m src.utility.calibrate_feedforward data\24_06_2026\RH_ramp_20260624_101500.csv
   ```

3. It prints the per-step points, the fitted line, and suggested values:

   ```
        RH (%)  wet_ratio   rows
          2.03     0.0000     20
         ...
         94.04     1.0000     20

     Fit:  wet_ratio = 1.0871·(RH/100) + -0.0216     R² = 1.0000

     Suggested config.json values:
       "rh_ff_gain": 1.0871,
       "rh_ff_offset": -0.0216,
   ```

4. Copy those two values into `config.json`, or let the tool write them for you
   (comments/formatting preserved — though `config.json` is comment-free by default):

   ```
   .venv\Scripts\python -m src.utility.calibrate_feedforward --apply
   ```

**Options:**

| Flag | Description |
|------|-------------|
| `--rh chiller\|hygrometer\|calibrated\|auto` | Which RH column to fit against. Default `auto` picks the best-populated; use `chiller` to match what the controller tracks when the chiller probe is connected |
| `--settle-frac <0–1>` | Fraction of each step's tail averaged as "settled" (default `0.5`) |
| `--apply` | Write `rh_ff_gain` / `rh_ff_offset` back into `src/configs/config.json` |

The tool warns if R² < 0.95 (noisy or not-yet-settled data — try a longer
`experiment_hold_time`) or if the gain is far from the ~1.0 the physics predicts.
`rh_dead_time` is not fitted this way; if you want it precise, read the lag between a
flow step and the RH starting to move in the same log and set it to that.

## Project Structure

```
lab-controller/
├── main.py                          # Entry point — creates QApplication and MainWindow
├── requirements.txt
├── src/
│   ├── configs/
│   │   └── config.json              # Machine-specific configuration
│   ├── devices/
│   │   ├── controller.py            # Central orchestrator: device refs, RH loop, experiment runner
│   │   ├── vogtlin_mfc.py           # Modbus RTU driver (minimalmodbus, big-endian 32-bit floats)
│   │   ├── hygrometer.py            # DewMaster serial driver (Magnus formula RH)
│   │   ├── chiller.py               # Julabo ASCII serial driver
│   │   └── pid_controller.py        # RH feedforward + PI(D) trim with dead-time-aware settling guard
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
│       ├── calibrate_feedforward.py # Fits rh_ff_gain/offset from a flow-ramp log (CLI tool)
│       └── update_settings.py       # Applies runtime settings changes to controller/logger/PID
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

**Device not connecting** — Check the COM port name in `config.json` (or the Settings → Devices dialog), confirm the device is powered on, and ensure no other software (e.g. PuTTY, another Python process) is holding the port open.

**Wrong readings after settings change** — Port and baud rate changes only take effect after disconnecting and reconnecting devices.

**Experiment never reaches stability** — Increase `experiment_stability_timeout` or widen `rh_deadband` if the hygrometer is noisy. The pre-conditioning phase will time out and proceed after the timeout regardless.
