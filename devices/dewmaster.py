import re
import time

import serial

from humidity import rh_from_dewpoint

# A reading looks like "DP = -7.6 C  AT = 24.1 C  RH = 23.5". A regex is used because
# the buffer can hold partial or several lines while the reply trickles in.
READING = re.compile(r"DP\s*=\s*(-?\d+\.\d)\s*C.*?AT\s*=\s*(-?\d+\.\d)\s*C", re.IGNORECASE)


class DewMaster:
    label = "EdgeTech DewMaster"
    settings = {"port": "", "baudrate": 19200}
    readings = {"RH": "%", "temperature": "°C", "dewpoint": "°C"}
    controls = {}

    def __init__(self, port, baudrate=19200, timeout=5.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial = None

    def connect(self):
        self.disconnect()
        self.serial = serial.Serial(self.port, self.baudrate, timeout=0.5)
        time.sleep(1)
        try:
            self.read()
        except Exception:
            self.disconnect()
            raise

    def disconnect(self):
        if self.serial is not None:
            self.serial.close()
            self.serial = None

    def read(self):
        self.serial.reset_input_buffer()
        self.serial.write(b"P\r")
        start = time.time()
        last_nudge = start
        buffer = ""
        while time.time() - start < self.timeout:
            if self.serial.in_waiting:
                buffer += self.serial.read(self.serial.in_waiting).decode(errors="ignore")
                match = READING.search(buffer)
                if match:
                    dewpoint = float(match.group(1))
                    temperature = float(match.group(2))
                    return {"RH": rh_from_dewpoint(dewpoint, temperature), "temperature": temperature,
                            "dewpoint": dewpoint}
            # The DewMaster sometimes stalls; a bare carriage return wakes it up.
            if time.time() - last_nudge > 1.0:
                self.serial.write(b"\r")
                last_nudge = time.time()
            time.sleep(0.05)
        raise TimeoutError(f"No reading from DewMaster on {self.port}")
