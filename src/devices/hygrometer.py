import serial
import time
import re
import math

class Hygrometer:
    def __init__(self, port: str, baudrate: int, timeout: float = 2.0, name: str = "Hygrometer"):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.name = name
        self.ser = None
        self.connected = False
        # Regex for: "DP = -7.6 C  AT = 24.1 C  RH = 23.5"
        self.data_pattern = re.compile(r"DP\s*=\s*(?P<dp>-?\d+\.\d)\s*C.*?AT\s*=\s*(?P<at>-?\d+\.\d)\s*C.*?RH\s*=\s*(?P<rh>-?\d+\.\d)", re.IGNORECASE)

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    def connect(self):
        try:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
            time.sleep(1)
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
            self.connected = True
            print(f"Connected to {self.name} on {self.port} at {self.baudrate} baud.")
            return True
        except Exception as e:
            raise RuntimeError(f"Failed to connect to {self.name}: {e}")

    def disconnect(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
            print(f"Disconnected {self.name}.")

    def is_connected(self) -> bool:
        return self.connected

    def _reconnect(self):
        """Close and reopen the serial port after a write failure."""
        try:
            self.ser.close()
        except Exception:
            pass
        self.connected = False
        try:
            self.connect()
        except Exception as e:
            print(f"Reconnect failed for {self.name}: {e}")

    def get_readings(self):
        if not self.ser or not self.ser.is_open:
            return None

        # Clear input buffer only once before starting
        self.ser.reset_input_buffer()
        try:
            self.ser.write(b"P\r")
            self.ser.flush()
        except (serial.SerialException, OSError) as e:
            print(f"Write error on {self.name}, reconnecting: {e}")
            self._reconnect()
            return None
        
        start_time = time.time()
        last_nudge = start_time
        buffer = b""
        
        while (time.time() - start_time) < 5.0:
            if self.ser.in_waiting:
                buffer += self.ser.read(self.ser.in_waiting)
                decoded = buffer.decode(errors="ignore")
                if m := self.data_pattern.search(decoded):
                    dewpoint = float(m.group("dp"))
                    ambient = float(m.group("at"))
                    return {
                        "dewpoint_temp": dewpoint,
                        "ambient_temp": ambient,
                        "relative_humidity_calculated": self.compute_relative_humidity(dewpoint, ambient)
                    }

            # Nudge if stalled (every 1.0s) - no buffer reset needed
            if (time.time() - last_nudge) > 1.0:
                self.ser.write(b"\r")
                self.ser.flush()
                last_nudge = time.time()

            time.sleep(0.05)

        return None

    def compute_relative_humidity(self, dp: float, t: float) -> float:
        """Compute RH (%) from dew point (dp) and ambient temp (t) using Magnus formula."""
        a, b = 17.625, 243.04
        try:
            if dp >= t: return 100.0
            num = math.exp(a * dp / (b + dp))
            den = math.exp(a * t / (b + t))
            return max(0.0, min(100.0, 100.0 * num / den))
        except Exception:
            return float('nan')

