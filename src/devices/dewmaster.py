import serial
import time
import re
import math

class DewMaster:
    def __init__(self, port: str, baudrate: int, timeout: float = 2.0, name: str = "DewMaster"):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.name = name
        self.ser = None

        # regex for data lines like:
        # "11/13/25  13:41:50   DP =    2.0 C  AT  =   24.1 C  RH  =   23.5    SERVOLOCK"
        self.data_pattern = re.compile(r"DP\s*=\s*(?P<dp>-?\d+\.\d)\s*C.*?AT\s*=\s*(?P<at>-?\d+\.\d)\s*C.*?RH\s*=\s*(?P<rh>-?\d+\.\d)", re.IGNORECASE)

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self):
        self.disconnect()

    def connect(self):
        try:
            self.ser = serial.Serial(
                self.port,
                self.baudrate,
                timeout=self.timeout,
            )
            time.sleep(1)
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
            return True
        except Exception as e:
            raise RuntimeError(f"Failed to connect to {self.name}: {e}")

    def disconnect(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
            print(f"Disconnected {self.name}.")

    def get_readings(self):
        self._write("P")
        lines = self._read_lines(1)

        for line in lines:
            m = self.data_pattern.search(line)
            if m:
                dewpoint = float(m.group("dp"))
                ambient = float(m.group("at"))
                rh_device = float(m.group("rh"))  # Native RH reading from device
                rh_calculated = self.compute_relative_humidity(dewpoint, ambient)
                return {
                    "dewpoint_temp": dewpoint,
                    "ambient_temp": ambient,
                    "relative_humidity_device": rh_device,
                    "relative_humidity_calculated": rh_calculated
                }

        return None

    def compute_relative_humidity(self, dewpoint_c: float, ambient_c: float) -> float:
        """Compute relative humidity (%) from dew point and ambient temperature (C).

        Uses the Magnus formula for saturation vapor pressure.
        RH = 100 * (exp(a*Td/(b+Td)) / exp(a*T/(b+T)))
        with a=17.625, b=243.04. Returns value clipped to [0, 100].
        """
        a = 17.625
        b = 243.04
        try:
            # Avoid division issues; if dewpoint exceeds ambient, limit to 100%
            if dewpoint_c >= ambient_c:
                return 100.0
            num = math.exp(a * dewpoint_c / (b + dewpoint_c))
            den = math.exp(a * ambient_c / (b + ambient_c))
            rh = 100.0 * num / den
            return max(0.0, min(100.0, rh))
        except Exception:
            return float('nan')

    # --------------------------------------------------------
    # Helper functions
    # --------------------------------------------------------
    def _write(self, cmd: str):
        if not self.ser or not self.ser.is_open:
            raise RuntimeError("Serial port not open.")
        self.ser.write(cmd.encode() + b"\r")
        self.ser.flush()
        time.sleep(0.1)

    def _read_lines(self, duration: float = 1.0) -> list[str]:
        if not self.ser:
            return []
        lines = []
        start = time.time()
        while time.time() - start < duration:
            line = self.ser.readline().decode(errors="ignore").strip()
            if line:
                lines.append(line)
        return lines

