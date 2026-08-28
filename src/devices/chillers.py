import serial
import time

class JulaboChiller:
    def __init__(self, port, baudrate=9600, timeout=1, name: str = "Chiller"):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.name = name
        self.ser = None
        self.connected = False

    def __enter__(self):
        self.connect()
        return self

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
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS, # 8 data bits (standard with Parity None) [cite: 22]
                parity=serial.PARITY_NONE, # Default parity often None [cite: 22]
                stopbits=serial.STOPBITS_ONE,
                timeout=self.timeout
            )
        except serial.SerialException as e:
            print(f"Error opening Chiller serial port {self.port}: {e}")
            self.ser = None
            self.connected = False
            return False

        # Opening the port only confirms the USB adapter — verify the chiller is
        # powered on and answering before reporting a successful connection.
        if not self._probe():
            print(f"Chiller on {self.port}: port opened but device did not respond "
                  f"(powered off?).")
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None
            self.connected = False
            return False

        print(f"Connected to Chiller on {self.port} at {self.baudrate} baud.")
        self.connected = True
        return True

    def _probe(self) -> bool:
        try:
            self.ser.reset_input_buffer()
            self.ser.write(b"version\r\n")
            self.ser.flush()
            time.sleep(0.1)
            resp = self.ser.readline().decode("ascii", errors="ignore").strip()
            return bool(resp)
        except Exception:
            return False

    def disconnect(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("Chiller connection closed.")
            self.ser = None
        self.connected = False

    def is_connected(self) -> bool:
        return self.connected

    def _reconnect(self):
        try:
            self.ser.close()
        except Exception:
            pass
        self.connected = False
        self.ser = None
        try:
            self.connect()
        except Exception as e:
            print(f"Chiller reconnect failed: {e}")

    def send_command(self, command):
        # Appends Carriage Return (Hex 0D) and Line Feed (Hex 0A) as per.
        if not self.ser or not self.ser.is_open:
            return None

        # Command structure requires CR + LF terminators
        full_command = f"{command}\r\n"

        try:
            self.ser.write(full_command.encode('ascii'))
        except (serial.SerialException, OSError) as e:
            print(f"Chiller write error, reconnecting: {e}")
            self._reconnect()
            return None
        time.sleep(0.1) # Small delay for processing

    def read_response(self):
        if not self.ser or not self.ser.is_open:
            return None

        try:
            # Read line ending in LF (0A)
            response = self.ser.readline().decode('ascii').strip()
            return response
        except Exception as e:
            print(f"Error reading response: {e}")
            return None

    def get_status(self):
        self.send_command("status")
        return self.read_response()

    def _query_float(self, command: str):
        self.send_command(command)
        resp = self.read_response()
        try:
            return float(resp) if resp else None
        except (ValueError, TypeError):
            return None

    def get_internal_temperature(self):
        return self._query_float("in_pv_00")

    def get_external_temperature(self):
        return self._query_float("in_pv_02")

    def get_setpoint_temperature(self):
        return self._query_float("in_sp_00")

    def set_setpoint_temperature(self, temperature):
        # Ensure format matches "OUT_SP_00_55.5" structure
        command = f"out_sp_00 {temperature}"
        self.send_command(command)
        print(f"Set temperature to {temperature}")

    # Name the "temp_setpoint" capability probes for (see registry.DeviceType.caps).
    set_temperature = set_setpoint_temperature

    def read(self) -> dict:
        return {
            "temp": self.get_external_temperature(),
            "setpoint": self.get_setpoint_temperature(),
        }

    def start_control(self):
        self.send_command("out_mode_05 1")
        print("Sent START command.")

    def close(self):
        self.disconnect()


# ── Discovery ────────────────────────────────────────────────────────────────

def probe_julabo(port, baudrate, addresses=(None,), timeout=None,
                 should_stop=None, on_probe=None):
    device = JulaboChiller(port, baudrate, timeout=0.5, name="Julabo scan")
    ok = False
    try:
        if device.connect():
            ok = device.get_setpoint_temperature() is not None
    except Exception:
        ok = False
    finally:
        try:
            device.disconnect()
        except Exception:
            pass
    if on_probe:
        on_probe()
    return [None] if ok else []
