import csv
import os
import queue
import time
from datetime import datetime

from PyQt6.QtCore import QThread, pyqtSignal

from control import PID
from devices import DEVICE_TYPES
from experiment import save_summary_plot
from humidity import calibrated_rh, rh_from_dewpoint

RECONNECT_INTERVAL = 10  # seconds between attempts to reach a device that is not answering


def data_units(setup):
    units = {}
    for device in setup["devices"]:
        for reading, unit in DEVICE_TYPES[device["type"]].readings.items():
            units[f"{device['name']} {reading}"] = unit
    # A computed RH channel only exists while both of the devices it reads are in the setup.
    for entry in setup["computed_rh"]:
        if (f"{entry['dewpoint_from']} dewpoint" in units
                and f"{entry['temperature_from']} temperature" in units):
            units[entry["name"]] = "%"
    return units


class Worker(QThread):
    """The only thread that talks to the hardware, because serial ports are not thread-safe.

    The GUI sends it commands through `commands`:
        ("set", device name, control, value)
        ("start", steps, experiment name)
        ("stop",)
        ("rh_control", settings, on)
    """

    new_data = pyqtSignal(dict)
    message = pyqtSignal(str)
    # Emitted when the worker itself turns the RH loop on or off, so the button can follow.
    rh_control_state = pyqtSignal(bool)
    # Emitted, with the reason, when no device answers the first try and the worker gives up.
    connection_failed = pyqtSignal(str)

    def __init__(self, setup):
        super().__init__()
        self.setup = setup
        self.units = data_units(setup)
        self.commands = queue.Queue()
        self.running = True

        self.devices = {}
        for device in setup["devices"]:
            device_class = DEVICE_TYPES[device["type"]]
            self.devices[device["name"]] = device_class(**{key: device[key] for key in device_class.settings})
        self.connected = set()
        self.last_attempt = {name: 0 for name in self.devices}

        self.rh = setup["rh_control"]
        self.rh_enabled = False
        self.pid = None
        self.last_rh_time = 0
        self.last_row = None

        self.steps = []
        self.step_index = 0
        self.step_end = 0
        self.log_file = None
        self.log_writer = None
        self.log_path = None

    def run(self):
        for name in self.devices:
            self.try_connect(name)
        # With nothing answering there is nothing to plot or log.
        if not self.connected:
            self.connection_failed.emit("No device answered. Check the settings under Devices… "
                                        "and connect again.")
            return
        self.open_log("monitor")
        next_poll = 0
        while self.running:
            while not self.commands.empty():
                command = self.commands.get()
                if command[0] == "set":
                    # The window locks manual control during an experiment, but a click can still
                    # be queued in the moment before the first row shows the run has started.
                    if self.steps:
                        self.message.emit(f"Cannot set {command[1]} {command[2]}: an experiment is running.")
                    else:
                        self.set_value(command[1], command[2], command[3])
                elif command[0] == "start":
                    self.start_experiment(command[1], command[2])
                elif command[0] == "stop" and self.steps:
                    self.stop_experiment("Experiment stopped.")
                elif command[0] == "rh_control":
                    self.set_rh_control(command[1], command[2])

            if self.steps and time.time() >= self.step_end:
                self.next_step()

            if time.time() >= next_poll:
                next_poll = time.time() + self.setup["poll_interval"]
                self.poll()

            time.sleep(0.05)

        if self.steps:
            self.stop_experiment("Experiment stopped by disconnect.")
        self.close_log()
        for name in self.connected:
            device = self.devices[name]
            # Stop the gas when the app lets go of an MFC.
            if "flow" in device.controls:
                try:
                    device.set("flow", 0.0)
                except Exception as error:
                    self.message.emit(f"{name}: could not set the flow to 0 ({error})")
            device.disconnect()
        self.message.emit("Disconnected.")

    def poll(self):
        row = {"time": datetime.now().replace(microsecond=0), "step": ""}
        if self.steps:
            row["step"] = self.step_index + 1
            row["step end"] = self.step_end
        for column in self.units:
            row[column] = None

        for name, device in self.devices.items():
            if name not in self.connected:
                if time.time() - self.last_attempt[name] < RECONNECT_INTERVAL:
                    continue
                self.try_connect(name)
                if name not in self.connected:
                    continue
            try:
                for reading, value in device.read().items():
                    row[f"{name} {reading}"] = value
            except Exception as error:
                self.message.emit(f"{name}: read failed, will reconnect ({error})")
                self.connected.discard(name)
                self.last_attempt[name] = time.time()
                try:
                    device.disconnect()
                except Exception:
                    pass

        for entry in self.setup["computed_rh"]:
            if entry["name"] not in self.units:
                continue
            dewpoint = row[f"{entry['dewpoint_from']} dewpoint"]
            temperature = row[f"{entry['temperature_from']} temperature"]
            if dewpoint is not None and temperature is not None:
                rh = rh_from_dewpoint(dewpoint, temperature)
                row[entry["name"]] = calibrated_rh(rh) if entry["calibrated"] else rh

        self.update_rh_control(row)

        self.log_writer.writerow(row)
        # Flush every row so the CSV can be watched live and a crash loses nothing.
        self.log_file.flush()
        self.new_data.emit(row)
        self.last_row = row

    def try_connect(self, name):
        self.last_attempt[name] = time.time()
        try:
            self.devices[name].connect()
            self.connected.add(name)
            self.message.emit(f"{name} connected.")
        except Exception as error:
            self.message.emit(f"{name}: not answering ({error})")

    def set_value(self, name, control, value):
        if name not in self.connected:
            self.message.emit(f"Cannot set {name} {control}: device is not connected.")
            return
        try:
            self.devices[name].set(control, value)
            self.message.emit(f"{name} {control} set to {value}")
        except Exception as error:
            self.message.emit(f"Cannot set {name} {control}: {error}")

    def set_rh_control(self, settings, on):
        self.rh = settings
        if self.pid is not None:
            self.pid.kp = settings["kp"]
            self.pid.ki = settings["ki"]
            self.pid.kd = settings["kd"]
        if on == self.rh_enabled:
            return
        if on:
            humid = settings["humid_mfc"]
            dry = settings["dry_mfc"]
            if self.steps:
                self.message.emit("RH control cannot run during an experiment: the experiment sets the flows.")
            elif settings["source"] not in self.units:
                self.message.emit("RH control needs an RH reading to follow.")
            elif humid == dry or humid not in self.devices or dry not in self.devices:
                self.message.emit("RH control needs two different MFCs.")
            elif settings["total_flow"] <= 0:
                self.message.emit("RH control needs a total flow above 0.")
            else:
                # Start from the share the humid MFC is set to now, so the flows do not jump.
                share = 50.0
                setpoint = self.last_row.get(f"{humid} setpoint") if self.last_row else None
                if setpoint is not None:
                    share = min(100.0, max(0.0, 100.0 * setpoint / settings["total_flow"]))
                self.pid = PID(settings["kp"], settings["ki"], settings["kd"], share)
                self.last_rh_time = 0
                self.rh_enabled = True
                self.message.emit(f"RH control on, holding {settings['target']:g} %.")
        else:
            self.rh_enabled = False
            self.pid = None
            self.message.emit("RH control off. The flows stay where they are.")
        self.rh_control_state.emit(self.rh_enabled)

    def update_rh_control(self, row):
        if not self.rh_enabled:
            return
        # The target and the share below are for the status line in the window only. They are
        # not in `units`, so they are neither logged nor plotted: the target is what the user
        # typed, and the share is the humid MFC setpoint over the total flow.
        row["RH control setpoint"] = self.rh["target"]
        humid = self.rh["humid_mfc"]
        dry = self.rh["dry_mfc"]
        measurement = row[self.rh["source"]]
        # Without a reading or an MFC, hold the flows where they are instead of integrating blindly.
        if measurement is None or humid not in self.connected or dry not in self.connected:
            return

        now = time.time()
        dt = now - self.last_rh_time
        # A first pass, a gap while a device was away, or a clock step: one poll interval is safer
        # than integrating a long, zero or negative dt.
        if dt <= 0 or dt > 10 * self.setup["poll_interval"]:
            dt = self.setup["poll_interval"]
        self.last_rh_time = now
        share = self.pid.update(self.rh["target"], measurement, dt)
        row["RH control share"] = share

        humid_flow = round(self.rh["total_flow"] * share / 100, 4)
        dry_flow = round(self.rh["total_flow"] - humid_flow, 4)
        for name, flow in ((humid, humid_flow), (dry, dry_flow)):
            try:
                self.devices[name].set("flow", flow)
            except Exception as error:
                self.message.emit(f"{name}: setting the flow failed, will reconnect ({error})")
                self.connected.discard(name)
                self.last_attempt[name] = time.time()

    def start_experiment(self, steps, name=""):
        if self.rh_enabled:
            self.set_rh_control(self.rh, False)
            self.message.emit("RH control switched off: the experiment sets the flows itself.")
        if self.steps:
            self.stop_experiment("Previous experiment stopped.")
        self.open_log("experiment", name)
        self.steps = steps
        self.step_index = -1
        self.step_end = 0  # so the first step starts straight away

    def next_step(self):
        self.step_index += 1
        if self.step_index == len(self.steps):
            # set flows to 0 when experiment finishes
            for name, device in self.devices.items():
                if "flow" in device.controls:
                    try:
                        device.set("flow", 0.0)
                    except Exception as error:
                        self.message.emit(f"{name}: could not set the flow to 0 ({error})")
            self.stop_experiment("Experiment finished.")
            return
        step = self.steps[self.step_index]
        for (name, control), value in step["setpoints"].items():
            self.set_value(name, control, value)
        self.step_end = time.time() + step["minutes"] * 60
        self.message.emit(f"Step {self.step_index + 1}/{len(self.steps)} started, holding {step['minutes']:g} min.")

    def stop_experiment(self, text):
        self.steps = []
        experiment_csv = self.log_path
        self.close_log()
        try:
            png_path = save_summary_plot(experiment_csv, self.units)
            self.message.emit(f"{text} Data saved to {experiment_csv} and {png_path}")
        except Exception as error:
            self.message.emit(f"{text} Data saved to {experiment_csv}, but the plot failed: {error}")
        if self.running:
            self.open_log("monitor")

    def open_log(self, prefix, name=""):
        self.close_log()
        now = datetime.now()
        folder = os.path.join(self.setup["log_folder"], now.strftime("%Y-%m-%d"))
        os.makedirs(folder, exist_ok=True)
        # The time comes first, so a day's files still sort in the order they were recorded.
        suffix = "".join(char if char.isalnum() or char in "-_" else "_" for char in name.strip())
        while "__" in suffix:  # collapse runs of "_" left behind by replaced characters
            suffix = suffix.replace("__", "_")
        suffix = suffix.strip("_")[:40]
        self.log_path = os.path.join(folder, f"{prefix}_{now:%H%M%S}{'_' + suffix if suffix else ''}.csv")
        self.log_file = open(self.log_path, "w", newline="", encoding="utf-8")
        # extrasaction: the row also carries the RH control fields and the step end time the
        # window shows, and those are deliberately not columns.
        self.log_writer = csv.DictWriter(self.log_file, ["time", "step"] + list(self.units),
                                         extrasaction="ignore")
        self.log_writer.writeheader()

    def close_log(self):
        if self.log_file is not None:
            self.log_file.close()
            self.log_file = None
