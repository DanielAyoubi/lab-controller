<p align="center">
  <img src="docs/logo.svg" alt="ACME - Aerosol and Cloud Microphysics Experiments" width="520">
</p>

# ACME controller

ACME (Aerosol and Cloud Microphysics Experiments) is a small PyQt6 app to run lab
instruments (mass flow controllers, RH probes, chillers, O₂ meters, …) and to script
simple experiments such as humidity cycles.

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
   a CSV file in the log folder: `data/YYYY-MM-DD/monitor_HHMMSS.csv`.
3. **Manual control** has a row for each setpoint a device accepts (MFC flow, chiller
   temperature, …).
4. **RH control** Pick the RH reading to follow, which MFC carries the humid air and which the dry, a target and a total
   flow, then click **Hold RH**. A PID moves the humid share of the flow to hit and stay at the picked RH.
   The line under the button reports the target it is holding and the humid share it asks for.
5. **Experiment** tab: fill the step table with the *Humidity cycle* form, or type steps
   yourself. Each step holds for its time in minutes and sets the values in its row. An
   empty cell leaves that setpoint unchanged. **Start experiment** logs to
   `experiment_HHMMSS.csv` and saves a PNG summary next to it when the experiment ends
   or is stopped. Experiment name can be set and is added to file names. Anything
   that is not a letter, digit, dash or underscore becomes an underscore, and the name is cut
   at 40 characters.

In the humidity cycle, the *humid share* is the percentage of the total flow sent
through the humid MFC. The dry MFC supplies the rest. With a saturating bubbler this
share is roughly the RH.

**Disconnect** (or closing the app) sets all MFC flows to 0.

## Setup catalog

Keep one JSON file per rig or experiment type in `setups/`, and switch between them with
File → Open from setup catalog. The program reopens the last setup you used.

```json
{
  "log_folder": "data",
  "poll_interval": 2.0,
  "devices": [
    {"name": "Humid MFC", "type": "vogtlin_mfc", "port": "COM23", "baudrate": 9600, "address": 24},
    {"name": "RH upstream", "type": "vaisala_rh", "port": "COM24", "baudrate": 19200, "address": 240}
  ],
  "computed_rh": [
    {"name": "Cell RH", "temperature_from": "Julabo chiller", "dewpoint_from": "RH upstream", "calibrated": true}
  ],
  "rh_control": {"source": "RH downstream rh", "humid_mfc": "Humid MFC", "dry_mfc": "Dry MFC",
                 "target": 60.0, "total_flow": 2.0, "kp": 1.0, "ki": 0.03, "kd": 0.0}
}
```

- A device's `name` must be unique. It prefixes its columns, e.g. `Humid MFC flow`.
- `computed_rh`: any number of RH columns worked out from two devices you already have —
  one that measures temperature (for example the Julabo's external probe) and one that
  measures dew point. Each entry adds one column under its own `name`, from the Magnus
  formula. With `calibrated` true, that result is then passed through the linear fit in
  `calibrated_rh` in `humidity.py` (a salt-deliquescence fit; change the two numbers there
  to match your own cell). List the same pair twice under different names to log the raw
  and the calibrated value side by side. An entry whose devices are not in the setup is
  ignored. Edit the list in the **Devices…** dialog.
- `rh_control`: what the RH control box starts with. The box writes back the source, the two
  MFCs, the target and the total flow, so they are there next time. The PID gains `kp`, `ki`
  and `kd` have no boxes in the window: retune a rig by editing them here.
- A relative `log_folder` is relative to the app folder.

## Device catalog

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

2. Add it to `DEVICE_TYPES` in `devices/__init__.py`. That is what puts the driver in the
   device catalog above.

The Devices dialog, manual controls, plot, CSV and experiment table then pick it up
automatically. Readings with a new unit get their own plot panel. A device with an
`address` setting (Modbus) must also accept a `timeout` argument, because the scan passes
a short one to sweep addresses quickly.
