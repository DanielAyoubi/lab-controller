import re
import time

import serial

# An analog Brooks 5850S behind an Arduino UNO R4 (firmware AIBrooksControllerV11): the Arduino
# drives the 0-5 V setpoint from its DAC and reads the 0-5 V flow signal on its ADC.
# `?help` on the port lists the ASCII commands; `?` reads and `>` writes, one per line.
STATUS_HEADER = "BROOKS CONTROLLER STATUS"
ML_PER_L = 1000.0 # controller runs in ml/m, convert to L/min
# With no gas flowing the flow signal still reads 20-30 mL/min, so anything below this reads as 0.
ZERO_CLAMP = 0.03  # L/min


class BrooksMFC:
    label = "Brooks MFC (Arduino)"
    settings = {"port": ""}
    readings = {"flow": "L/min", "setpoint": "L/min"}
    controls = {"flow": "L/min"}

    def __init__(self, port, timeout=0.5):
        self.port = port
        self.timeout = timeout
        self.serial = None

    def connect(self):
        self.disconnect()
        self.serial = serial.Serial(self.port, timeout=self.timeout)
        try:
            self.serial.write(b"\n")
            time.sleep(0.1)
            status = self.status() # Setpoints are whole numbers in the active unit, so only ml/m gives a usable resolution.
            if status["Unit"] != "ml/m":
                raise ValueError(f"{self.port}: the Brooks controller is set to {status['Unit']}; "
                                 "set it to ml/m (send '>unit 0') to use it here")
        except Exception:
            self.disconnect()
            raise

    def disconnect(self):
        if self.serial is not None:
            self.serial.close()
            self.serial = None

    def read(self):
        status = self.status()
        flow = float(status["Live Flow"].split()[0]) / ML_PER_L
        if flow < ZERO_CLAMP:
            flow = 0.0
        # A stopped controller forces the valve signal to 0 V, whatever setpoint it keeps.
        setpoint = float(status["Setpoint"]) / ML_PER_L if status["State"] == "RUNNING" else 0.0
        return {"flow": flow, "setpoint": setpoint}

    def set(self, name, value):
        # The firmware takes whole ml/m and truncates decimals, so round here instead.
        reply = self.query(f">flow {round(value * ML_PER_L)}")
        if not reply.startswith("<OK"):
            raise ValueError(f"setpoint {value:g} L/min refused: {reply.lstrip('<')}")
        if self.status()["State"] != "RUNNING":
            self.query(">control 1")

    def query(self, command):
        self.serial.reset_input_buffer()
        self.serial.write(f"{command}\n".encode("ascii"))
        return self.serial.readline().decode("ascii", errors="replace").strip()

    def status(self):
        header = self.query("?status")
        if STATUS_HEADER not in header:
            raise ValueError(f"{self.port}: no Brooks controller status (got {header!r})")
        fields = {}
        while True:
            line = self.serial.readline().decode("ascii", errors="replace").strip()
            if not line:
                raise TimeoutError(f"{self.port}: the Brooks status block stopped early")
            if line.startswith("<---"):
                break
            match = re.fullmatch(r"<([^:]+):\s*(.*)", line)
            if match:
                fields[match[1]] = match[2]
        return fields
