import serial
import time


class FireStingO2:
    """PyroScience FireSting O2 meter, legacy ASCII protocol (firmware < 4).

    Commands are CR-terminated; the device echoes a recognized command back
    (the echo for MSR/TMP arrives once the measurement completes). Results are
    read from register block 3 as integers scaled x1000.
    """

    # Result block 3 register: air saturation in e-3 %airsat.
    REG_AIRSAT = 4
    # Air-saturated gas at the calibration conditions contains 20.95 % O2.
    O2_FRACTION_AIR = 0.2095
    # The device reports -300000 (-300 after scaling) for invalid values.
    INVALID = -300.0

    def __init__(self, port: str, baudrate: int = 19200, timeout: float = 1.0,
                 name: str = "FireSting O2", channel: int = 1,
                 read_timeout: float = 4.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.name = name
        self.channel = channel
        # Max seconds to wait for a command echo/response. MSR/TMP only echo
        # once the optical measurement finishes, so this must cover that.
        self.read_timeout = read_timeout
        self.ser = None
        self.connected = False

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    def connect(self):
        # Close any stale handle first so reconnecting after a dropout re-opens
        # the port cleanly.
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None
        try:
            self.ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
            time.sleep(0.5)
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
        except Exception as e:
            self.ser = None
            self.connected = False
            raise RuntimeError(f"Failed to open {self.name} port {self.port}: {e}")

        # Opening the USB-serial adapter succeeds even when the meter itself is
        # absent, so confirm the device echoes a command before reporting
        # success. #LOGO is a cheap no-op that legacy firmware always echoes.
        try:
            verified = self._send("#LOGO") is not None
        except (serial.SerialException, OSError):
            verified = False
        if not verified:
            print(f"{self.name} on {self.port}: port opened but no response "
                  f"(device off?).")
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None
            self.connected = False
            return False

        self.connected = True
        print(f"Connected to {self.name} on {self.port} at {self.baudrate} baud.")
        return True

    def disconnect(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
            print(f"Disconnected {self.name}.")
        self.connected = False

    def is_connected(self) -> bool:
        return self.connected

    def _reconnect(self):
        try:
            self.ser.close()
        except Exception:
            pass
        self.connected = False
        try:
            self.connect()
        except Exception as e:
            print(f"Reconnect failed for {self.name}: {e}")

    def read(self):
        if not self.ser or not self.ser.is_open:
            return None
        try:
            return self._query()
        except (serial.SerialException, OSError) as e:
            print(f"Serial error on {self.name}, reconnecting: {e}")
            self._reconnect()
            return None

    # Kept for notebooks/scripts that predate the uniform Device interface.
    get_readings = read

    def _query(self):
        """Trigger one measurement and return {"oxygen": %O2}, or None.

        Serial/OS errors propagate to the caller (get_readings reconnects;
        connect treats them as a failed verification) — this method never
        reconnects itself.
        """
        ch = self.channel
        # The oxygen computation is temperature-compensated from the sample
        # temp register, which holds an invalid sentinel until TMP is
        # triggered — so refresh temperature before each oxygen measurement.
        if self._send(f"TMP {ch}") is None:
            return None
        if self._send(f"MSR {ch}") is None:
            return None
        resp = self._send(f"REA {ch} 3 {self.REG_AIRSAT}")
        if resp is None:
            return None
        # Response: "REA <ch> 3 <reg> <value>", value = %airsat x1000.
        try:
            air_sat = int(resp.split()[-1]) / 1000.0
        except (ValueError, IndexError):
            print(f"{self.name}: unexpected response {resp!r}")
            return None
        if air_sat <= self.INVALID:
            return None
        return {"oxygen": air_sat * self.O2_FRACTION_AIR}

    def _send(self, cmd: str):
        """Send one command and read the CR-terminated response.

        Returns the decoded response line, or None on timeout.
        """
        self.ser.reset_input_buffer()
        self.ser.write((cmd + "\r").encode("ascii"))
        self.ser.flush()

        deadline = time.time() + self.read_timeout
        buffer = b""
        while time.time() < deadline:
            if self.ser.in_waiting:
                buffer += self.ser.read(self.ser.in_waiting)
                if buffer.endswith(b"\r"):
                    return buffer.decode("ascii", errors="ignore").strip()
            time.sleep(0.02)
        return None
