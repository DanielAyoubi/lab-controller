import serial
import time
import re
import struct
import inspect

from pymodbus.client import ModbusSerialClient

class EdgeTechHygrometer:
    def __init__(self, port: str, baudrate: int, timeout: float = 2.0, name: str = "Hygrometer",
                 read_timeout: float = 5.0, nudge_interval: float = 1.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.name = name
        # Max seconds to wait for a complete reading, and how often to re-send CR
        # (a "nudge") while waiting for the device to respond.
        self.read_timeout = read_timeout
        self.nudge_interval = nudge_interval
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
            time.sleep(1)
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
        except Exception as e:
            self.ser = None
            self.connected = False
            raise RuntimeError(f"Failed to open {self.name} port {self.port}: {e}")

        # Opening the USB-serial adapter succeeds even when the DewMaster itself is
        # powered off, so confirm we can actually read a value before reporting
        # success. _query() does not auto-reconnect, so there is no recursion here.
        try:
            verified = self._query() is not None
        except (serial.SerialException, OSError):
            verified = False
        if not verified:
            print(f"{self.name} on {self.port}: port opened but no valid reading "
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

    def get_readings(self):
        if not self.ser or not self.ser.is_open:
            return None
        try:
            return self._query()
        except (serial.SerialException, OSError) as e:
            print(f"Serial error on {self.name}, reconnecting: {e}")
            self._reconnect()
            return None

    def _query(self):
        """Send one poll and read until a valid reading or timeout.

        Returns the parsed reading dict, or None on timeout. Serial/OS errors
        propagate to the caller (get_readings reconnects; connect treats them as
        a failed verification) — this method never reconnects itself.
        """
        # Clear input buffer only once before starting
        self.ser.reset_input_buffer()
        self.ser.write(b"P\r")
        self.ser.flush()

        start_time = time.time()
        last_nudge = start_time
        buffer = b""

        while (time.time() - start_time) < self.read_timeout:
            if self.ser.in_waiting:
                buffer += self.ser.read(self.ser.in_waiting)
                decoded = buffer.decode(errors="ignore")
                if m := self.data_pattern.search(decoded):
                    dewpoint = float(m.group("dp"))
                    ambient = float(m.group("at"))
                    return {
                        "dewpoint_temp": dewpoint,
                        "hygrometer_temp": ambient,
                    }

            # Nudge if stalled - no buffer reset needed
            if (time.time() - last_nudge) > self.nudge_interval:
                self.ser.write(b"\r")
                self.ser.flush()
                last_nudge = time.time()

            time.sleep(0.05)

        return None




class VaisalaRHProbe:
    def __init__(self, port: str, slave_addr: int = 240):
        self.client = ModbusSerialClient(
            port=port, timeout=1, baudrate=19200, bytesize=8, stopbits=2, parity="N"
        )
        self.slave_addr = slave_addr
        if not self.client.connect():
            raise IOError(f"Failed to connect to {port}")


    def regs_to_float(self, registers: list[int], hi_idx: int) -> float:
        """HMP110 stores 32-bit floats as two 16-bit regs, little-endian word order."""
        raw = registers[hi_idx].to_bytes(2, "big") + registers[hi_idx - 1].to_bytes(2, "big")
        return struct.unpack("!f", raw)[0]


    def read_holding_registers_compat(self, client, address, count, slave):
        """Call read_holding_registers regardless of pymodbus's kwarg naming
        for the slave/unit id, which has changed across versions (unit -> slave
        -> device_id)."""
        sig = inspect.signature(client.read_holding_registers)
        params = sig.parameters
        kwargs = {"address": address, "count": count}
        for name in ("slave", "unit", "device_id"):
            if name in params:
                kwargs[name] = slave
                break
        return client.read_holding_registers(**kwargs)


    def read_measurements(self, client: ModbusSerialClient):
        rr = self.read_holding_registers_compat(client, 0, 10, self.slave_addr)
        if rr.isError():
            raise IOError(rr)
        regs = rr.registers
        rh = self.regs_to_float(regs, 1)   # relative humidity [%RH]
        t = self.regs_to_float(regs, 3)    # temperature [°C]
        dp = self.regs_to_float(regs, 9)   # dew point [°C]
        return rh, t, dp

