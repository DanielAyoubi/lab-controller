<p align="center">
  <img src="docs/logo.svg" alt="ACME - Aerosol and Cloud Microphysics Experiments" width="520">
</p>

# ACME controller

ACME (Aerosol and Cloud Microphysics Experiments) is a small PyQt6 app to run lab
instruments (mass flow controllers, RH probes, chillers, O₂ meters, …) and to script
simple experiments such as humidity cycles.

The window is built from a **setup file** that lists the devices on the rig. Only the
controls, plot panels and CSV columns for those devices appear.

## Run

```
git clone https://github.com/DanielAyoubi/ACME-controller.git
cd ACME-controller
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

## Using it

1. **Devices…** lists the devices in the current setup. Add a device, pick its COM port,
   or click **Detect devices…** to scan the serial ports. A quick scan tries default and
   already-used addresses. A deep scan also sweeps Modbus addresses 1–247.
2. **Connect** starts polling. Every reading goes to the plot, to *Latest readings* and to
   a CSV file in the log folder: `data/YYYY-MM-DD/monitor_HHMMSS.csv`. Each row is written
   to disk as soon as it is read.
3. **Manual control** has a row for each setpoint a device accepts (MFC flow, chiller
   temperature, …).
4. **RH control** holds the RH at a target instead of you chasing it by hand. Pick the RH
   reading to follow, which MFC carries the humid air and which the dry, a target and a total
   flow, then click **Hold RH**. A PID moves the humid share of the flow; the total flow stays
   where you set it. The target and the gains can be changed while it holds. `Kp` is % share per
   % RH, `Ki` per % RH second and `Kd` per % RH per second; start with `Kd` at 0, since the RH
   signal is noisy. The loop waits quietly while a reading or an MFC is missing, and switches
   itself off when an experiment starts, because the step table sets the same two flows.
5. **Experiment** tab: fill the step table with the *Humidity cycle* form, or type steps
   yourself. Each step holds for its time in minutes and sets the values in its row. An
   empty cell leaves that setpoint unchanged. **Start experiment** logs to
   `experiment_HHMMSS.csv` and saves a PNG summary next to it when the experiment ends
   or is stopped.

In the humidity cycle, the *humid share* is the percentage of the total flow sent
through the humid MFC. The dry MFC supplies the rest. With a saturating bubbler this
share is roughly the RH.

**Disconnect** (or closing the app) sets all MFC flows to 0.

## Setup files

Keep one JSON file per rig or experiment type in `setups/`, and switch between them with
File → Open setup. The app reopens the last setup you used.

```json
{
  "log_folder": "data",
  "poll_interval": 2.0,
  "devices": [
    {"name": "Humid MFC", "type": "vogtlin_mfc", "port": "COM23", "baudrate": 9600, "address": 24},
    {"name": "RH upstream", "type": "vaisala_rh", "port": "COM24", "baudrate": 19200, "address": 240}
  ],
  "cell_rh": {"dewpoint_from": "", "temperature_from": ""},
  "rh_control": {"source": "RH downstream rh", "humid_mfc": "Humid MFC", "dry_mfc": "Dry MFC",
                 "target": 60.0, "total_flow": 2.0, "kp": 1.0, "ki": 0.03, "kd": 0.0}
}
```

- A device's `name` must be unique. It prefixes its columns, e.g. `Humid MFC flow`.
- `cell_rh`: pick a device that measures dew point and another that measures temperature
  (for example the Julabo's external probe). The app then adds `Cell RH` (Magnus formula)
  and `Cell RH calibrated` (salt-deliquescence fit in `humidity.py`).
- `rh_control`: what the RH control box starts with. The box writes back to it, so the last
  target and gains are there next time. With a `source` set, the log gains the columns
  `RH control setpoint` and `RH control share` (the humid share the PID asks for).
- A relative `log_folder` is relative to the app folder.

## Supported devices

| type | device | readings | setpoints |
|------|--------|----------|-----------|
| `vogtlin_mfc` | Vögtlin MFC, Modbus RTU | flow, setpoint | flow |
| `vaisala_rh` | Vaisala HMP110, Modbus RTU | rh, temperature, dewpoint | – |
| `dewmaster` | EdgeTech DewMaster, serial | rh, temperature, dewpoint | – |
| `julabo_chiller` | Julabo chiller, serial | temperature (external probe), setpoint | temperature |
| `firesting_o2` | PyroScience FireSting O₂, legacy firmware | oxygen | – |

## Adding a new device

1. Create `devices/my_device.py` with a class like this:

   ```python
   class MyDevice:
       label = "My device"                            # shown in the Devices dialog
       settings = {"port": "", "baudrate": 9600}      # connection settings and their defaults
       readings = {"pressure": "mbar"}                # what read() returns, and the units
       controls = {"pressure": "mbar"}                # what set() accepts ({} if nothing)

       def __init__(self, port, baudrate=9600): ...
       def connect(self): ...          # open the port and prove the device answers; raise if not
       def disconnect(self): ...
       def read(self): ...             # return {"pressure": 1013.2}; raise on failure, None if unavailable
       def set(self, name, value): ... # only needed when controls is not empty
   ```

2. Add it to `DEVICE_TYPES` in `devices/__init__.py`.

The Devices dialog, manual controls, plot, CSV and experiment table then pick it up
automatically. Readings with a new unit get their own plot panel. A device with an
`address` setting (Modbus) must also accept a `timeout` argument, because the scan passes
a short one to sweep addresses quickly.
