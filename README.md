# N-SIM Environmental Control System

A desktop application for controlling the environmental humidity chamber of an N-SIM microscope. The lab setup is **modular**: you declare which instruments are connected — Vögtlin mass flow controllers, an EdgeTech DewMaster chilled-mirror hygrometer, a Vaisala HMP110 RH probe, a Julabo chiller, a PyroScience FireSting O₂ meter — give each a display tag and a role, and the app wires up the controls, plot and logs around them.

## Features

- **Modular Device Setup** — Add devices by type, COM port and tag under Settings → Devices (up to 8 of each type). Assign roles (wet flow / dry flow / RH source / temperature source / O₂ source) to tell the control loops what each one does; the rest are logged and plotted as monitors
- **Mass Flow Control** — Vögtlin Modbus RTU MFCs; manual and ramped setpoints, one row per MFC
- **Humidity & Temperature Probes** — EdgeTech DewMaster (dew-point + ambient temperature) and Vaisala HMP110 (direct RH over Modbus)
- **Chiller** — Julabo ASCII serial driver; temperature setpoint and external probe readback
- **Feedforward + PI RH Control** — Automatic wet/dry flow ratio adjustment to hold a target RH; a static feedforward model jumps straight to the right ratio (fast settling) while a gentle PI(D) term trims the residual, with a dead-time-aware settling guard and deadband. The feedforward is calibrated from a flow-ramp log (see below)
- **Automated RH Ramp Experiment** — Steps wet-flow ratio from 0 → 100 % (or reverse) with configurable hold time, pre-conditioning phase, and RH stop limits; saves CSV log and PNG summary plot
- **Real-time Plot** — 3-panel live chart (flows / temperatures / percentages) built from whatever is connected. Each device gets one colour, used in every panel it appears in; a setpoint is the dashed twin of its own measurement; each trace carries a marker shape that also appears in the legend, so lines stay easy to tell apart. The saved PNG matches the screen exactly
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

3. **Declare your lab setup:**

   Either edit the `devices` array in `src/configs/config.json`, or start the app
   and use **Settings → Devices** (see [Devices](#devices) below):
   ```json
   {
     "devices": [
       {"id": "wet_mfc", "type": "vogtlin_mfc", "tag": "Wet MFC",
        "role": "wet_flow", "enabled": true, "port": "COM4",
        "baudrate": 9600, "address": 1},
       {"id": "dry_mfc", "type": "vogtlin_mfc", "tag": "Dry MFC",
        "role": "dry_flow", "enabled": true, "port": "COM6",
        "baudrate": 9600, "address": 247},
       {"id": "hygro", "type": "dewmaster_hygrometer", "tag": "Hygrometer",
        "role": "rh_source", "enabled": true, "port": "COM7",
        "baudrate": 19200}
     ]
   }
   ```

4. **Run the application:**
   ```
   python main.py
   ```

## Configuration

All settings live in a single JSON file, **`src/configs/config.json`**. It holds
both the machine-specific device settings and the application/experiment defaults.

Settings can also be changed at runtime through the **Settings** dialog (General / Devices / Experiment tabs). Changes apply immediately **and** are written back to `config.json` (plain JSON, rewritten in full on save).

### Devices

The lab setup is modular: you declare which instruments are connected and what
each one is for. Add, remove and edit devices under **Settings → Devices** — one
card per device — or edit the `devices` array in `config.json` directly. Up to
**8 devices of each type** are supported.

Each device has:

| Field | Description |
|-------|-------------|
| **Type** | Listed in the picker as **Vögtlin MFC**, **DewMaster**, **Vaisala**, **Julabo**, **FireSting** (`vogtlin_mfc`, `dewmaster_hygrometer`, `vaisala_rh`, `julabo_chiller`, `firesting_o2` in `config.json`) |
| **Tag** | Display name, e.g. "Wet MFC". Shown in the plot legend and next to its controls. Safe to rename at any time. |
| **Role** | Usually automatic — only MFCs ask you to pick (wet / dry). See below |
| **Port** (+ baud rate, Modbus address) | Connection settings; which fields appear depends on the type |
| **Enabled** | Unchecked devices are skipped on Connect |

#### Roles

A **tag** is cosmetic; a **role** decides behaviour and fixes the standard CSV
column names. **In most cases you never have to set one.**

An RH probe is always the RH source, a chiller always the temperature source, an
O₂ meter always the O₂ source — so the first one you add takes that role
automatically. The only role you actually choose is which MFC is the **wet** line
and which the **dry** one, because that cannot be inferred.

| Role | Set by | Used for |
|------|--------|----------|
| `wet_flow` / `dry_flow` | You, on the MFC card | The pair the RH control loop and the ramp experiment drive |
| `rh_source` | Automatic | The probe the RH reading is taken from |
| `temp_source` | Automatic | The temperature used to compute RH |
| `o2_source` | Automatic | The O₂ reading logged as `oxygen` |
| `none` | — | Monitor only: still connected, plotted and logged, just not driving anything |

**Several probes of the same kind** — e.g. one before and one after a flow cell —
are perfectly normal: give them tags that say so ("RH before cell", "RH after
cell"). **Each probe measures, logs and plots entirely on its own**, whatever
its role — you get one trace per probe, under its own tag.

The role only answers a question the app has to resolve to a single device:
*which* reading should the RH control loop steer on, and which probe fills the
fixed-name columns (`dewpoint_temp`, `rh_chiller`) that analysis scripts look
for. That is the checkbox on the card — "Use this probe's reading for RH
control". Tick it on the other probe to swap. The same applies to multiple
chillers or O₂ meters.

**RH control and the experiment's RH mode require the wet and dry MFC roles plus
an RH probe.** Without them the app offers the open-loop flow ramp only, and the
RH panel explains what is missing.

#### What gets logged

Every device writes `<tag>_<channel>` columns, named after the tag you gave it —
a probe tagged "RH before cell" logs `rh_before_cell_rh`, `rh_before_cell_temp`,
`rh_before_cell_dewpoint`. Renaming a device renames its columns; if a log is
open at the time, the app starts a fresh file so the header always matches.
Role-holders additionally write the original canonical column names
(`wet_flow`, `dry_flow`, `dewpoint_temp`, `chiller_temp`, `oxygen`, …), so
existing analysis scripts and notebooks keep working unchanged.

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

The controller commands the wet-flow ratio as **`wet_ratio = target_RH / 100`** (the feedforward), then trims the small remaining error with PI(D). This is the plant physics — with a saturating bubbler on the wet line, steady-state RH ≈ 100 · wet_ratio — so it is derived in code on every step, with no calibration to maintain. The feedforward is what makes settling fast; any departure from it (bubbler under-saturation, probe offset) is learned at runtime by the integral term.

| Key | Default | Description |
|-----|---------|-------------|
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

## Project Structure

```
lab-controller/
├── main.py                          # Entry point — creates QApplication and MainWindow
├── requirements.txt
├── src/
│   ├── configs/
│   │   └── config.json              # Machine-specific configuration
│   ├── devices/
│   │   ├── registry.py              # Device types, channels, roles, CSV/plot generators
│   │   ├── controller.py            # Central orchestrator: device set by role, RH loop, experiment runner
│   │   ├── mass_flow_controllers.py # Vögtlin Modbus RTU driver (minimalmodbus, big-endian 32-bit floats)
│   │   ├── RH_probes.py             # EdgeTech DewMaster + Vaisala HMP110 drivers
│   │   ├── chillers.py              # Julabo ASCII serial driver
│   │   ├── O2_monitors.py           # PyroScience FireSting O₂ driver
│   │   └── pid_controller.py        # RH feedforward + PI(D) trim with dead-time-aware settling guard
│   ├── gui/
│   │   ├── main_window.py           # Main window: device-driven left panel + right panel plot
│   │   ├── workers.py               # PollWorker, FlowRampWorker, ExperimentWorker (QThread)
│   │   ├── settings_dialog.py       # Three-tab settings dialog (General / Devices / Experiment)
│   │   └── widgets/
│   │       ├── device_editor.py     # Add/remove/tag/role device cards for the Devices tab
│   │       └── plot_widget.py       # RealTimePlotWidget — 3 shared-x pyqtgraph panels
│   └── utility/
│       ├── data_logger.py           # CSV logger with date sub-folders, 8 KB write buffer
│       ├── plot_saver.py            # Saves a plain quick-look 3-panel PNG at experiment end
│       ├── compute_RH.py            # Magnus formula: RH from dew-point and ambient temp
│       └── update_settings.py       # Config path, applies runtime settings, saves config.json
└── data/                            # Log output directory (created automatically)
```

## Data Logging

CSV files are written to `<log_dir>/<DD_MM_YYYY>/<prefix>_<timestamp>.csv`. The
column set follows your device list.

**Per-device columns** — every device writes one column per channel, prefixed
with its tag: `wet_mfc_flow`, `wet_mfc_setpoint`, `rh_before_cell_rh`,
`rh_after_cell_rh`, `julabo_temp`, `firesting_oxygen`, …

**Canonical columns** — devices holding a role also write the original fixed
names, so existing analysis scripts and notebooks keep working:

| Column | Written by | Description |
|--------|-----------|-------------|
| `timestamp` | — | ISO 8601 timestamp |
| `dry_flow` / `dry_flow_setpoint` | `dry_flow` role | Dry MFC actual flow / setpoint (L/min) |
| `wet_flow` / `wet_flow_setpoint` | `wet_flow` role | Wet MFC actual flow / setpoint (L/min) |
| `dewpoint_temp` | `rh_source` role | Dew-point temperature (°C) |
| `hygrometer_temp` | `rh_source` role | RH source's own ambient temperature (°C) |
| `rh_probe` | `rh_source` role | RH reported directly by the probe (Vaisala) |
| `chiller_temp` / `chiller_setpoint` | `temp_source` role | External probe temperature / setpoint (°C) |
| `oxygen` | `o2_source` role | O₂ (%) |
| `rh_hygrometer` | computed | RH from dew-point + the RH source's own temp. Only written for a dew-point-only probe (DewMaster) — a Vaisala reports RH directly as `rh_probe`, so deriving it again would duplicate the reading |
| `rh_chiller` | computed | RH from dew-point + the external probe temp |
| `rh_chiller_calibrated` | computed | `rh_chiller` corrected by the cell calibration fit |

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
