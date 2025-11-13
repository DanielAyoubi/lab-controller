import serial
import time
import re
from typing import Optional, Dict

class DewMaster:
    """
    Wrapper class for Edgetech Instruments DewMaster hygrometer via RS-232.
    """

    def __init__(self, port: str, baudrate: int = 9600, timeout: float = 1.0, name: str = "DewMaster"):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.name = name
        self.ser: Optional[serial.Serial] = None

        # regex for data lines like:
        # "11/13/25  13:41:50   DP =    2.0 C  AT  =   24.1 C  RH  =   23.5    SERVOLOCK"
        self.data_pattern = re.compile(
            r"(?P<date>\d{2}/\d{2}/\d{2})\s+(?P<time>\d{2}:\d{2}:\d{2}).*?DP\s*=\s*(?P<dp>[-\d.]+)\s*C.*?"
            r"AT\s*=\s*(?P<at>[-\d.]+)\s*C.*?RH\s*=\s*(?P<rh>[-\d.]+)"
        )

    # --------------------------------------------------------
    # Context manager interface
    # --------------------------------------------------------
    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    # --------------------------------------------------------
    # Connection management
    # --------------------------------------------------------
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

    # --------------------------------------------------------
    # Low-level helpers
    # --------------------------------------------------------
    def _write(self, cmd: str):
        """Send a command with carriage return."""
        if not self.ser or not self.ser.is_open:
            raise RuntimeError("Serial port not open.")
        self.ser.write(cmd.encode())
        self.ser.write(b"\r")
        self.ser.flush()
        time.sleep(0.1)

    def _read_lines(self, duration: float = 1.0) -> list[str]:
        """Read lines for a short period."""
        if not self.ser:
            return []
        lines = []
        start = time.time()
        while time.time() - start < duration:
            line = self.ser.readline().decode(errors="ignore").strip()
            if line:
                lines.append(line)
        return lines

    # --------------------------------------------------------
    # High-level commands
    # --------------------------------------------------------
    def set_output_interval(self, seconds: int = 1):
        """Set automatic serial output interval in seconds."""
        self._write("P")
        time.sleep(0.5)
        self._write("O")
        time.sleep(0.5)
        self._write(str(seconds))
        ack = self._read_lines(5)
        print("\n:".join(ack))

    def poll(self) -> Optional[Dict[str, float]]:
        """Request one measurement (P command) and parse the result."""
        self._write("P")
        lines = self._read_lines(1)
        for line in lines:
            m = self.data_pattern.search(line)
            if m:
                data = {k: (float(v) if k in ("dp", "at", "rh") else v)
                        for k, v in m.groupdict().items()}
                return data
        return None

    def read_stream(self, duration: float = 10.0):
        """Read continuous automatic output for a given duration."""
        print(f"Reading continuous output for {duration}s...")
        start = time.time()
        while time.time() - start < duration:
            line = self.ser.readline().decode(errors="ignore").strip()
            if not line:
                continue
            m = self.data_pattern.search(line)
            if m:
                dp = float(m.group("dp"))
                at = float(m.group("at"))
                rh = float(m.group("rh"))
                print(f"DP={dp:6.2f}°C  AT={at:6.2f}°C  RH={rh:6.2f}%")
        print("Done.")
