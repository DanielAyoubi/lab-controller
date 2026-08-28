import serial
import time
import math
import re
import struct
import inspect

from pymodbus.client import ModbusSerialClient

def read_holding_registers_compat(client, address, count, slave):
    """Call read_holding_registers regardless of pymodbus's kwarg naming for
    the slave/unit id, which has changed across versions (unit -> slave ->
    device_id)."""
    params = inspect.signature(client.read_holding_registers).parameters
    kwargs = {"address": address, "count": count}
    for name in ("slave", "unit", "device_id"):
        if name in params:
            kwargs[name] = slave
            break
    return client.read_holding_registers(**kwargs)


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
                    return {
                        "dewpoint": float(m.group("dp")),
                        "temp": float(m.group("at")),
                    }

            # Nudge if stalled - no buffer reset needed
            if (time.time() - last_nudge) > self.nudge_interval:
                self.ser.write(b"\r")
                self.ser.flush()
                last_nudge = time.time()

            time.sleep(0.05)

        return None




class VaisalaRHProbe:
    """Vaisala HMP110 RH/T probe over Modbus RTU.

    Reports RH directly (no dew-point conversion needed), plus temperature and
    the probe's own dew-point calculation.
    """

    def __init__(self, port: str, slave_addr: int = 240, baudrate: int = 19200,
                 timeout: float = 1.0, name: str = "Vaisala RH"):
        self.port = port
        self.slave_addr = slave_addr
        self.baudrate = baudrate
        self.timeout = timeout
        self.name = name
        self.client = None
        self.connected = False
        # Quantities already reported as unavailable, so the warning is printed
        # once per probe rather than on every poll.
        self._unavailable: set = set()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    def connect(self) -> bool:
        # Close any stale client first so reconnecting after a dropout re-opens
        # the port cleanly instead of failing on an already-open handle.
        self.disconnect()
        self.client = ModbusSerialClient(
            port=self.port, timeout=self.timeout, baudrate=self.baudrate,
            bytesize=8, stopbits=2, parity="N",
        )
        if not self.client.connect():
            print(f"Error opening {self.name} port {self.port}")
            self.client = None
            self.connected = False
            return False

        # Opening the port only proves the USB adapter is present. Probe with a
        # real register read so a powered-off probe reports as failed.
        try:
            self.read_measurements()
        except Exception as e:
            print(f"{self.name} on {self.port} (addr={self.slave_addr}): port "
                  f"opened but device did not respond (powered off?): {e}")
            self.disconnect()
            return False

        print(f"Connected to {self.name} at {self.port} (addr={self.slave_addr})")
        self.connected = True
        return True

    def disconnect(self):
        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None
        self.connected = False

    def is_connected(self) -> bool:
        return self.connected

    def read(self):
        """One poll, keyed by the channel keys declared in the registry.

        A register the probe cannot currently populate reads back as a float
        NaN rather than as an error, so each quantity is reported as None
        instead — a NaN would otherwise travel all the way to the CSV column
        and the plot, where it looks like a reading that simply never draws.
        The first time a quantity does this it is printed once, because the
        usual cause is a probe model that does not compute it at all.
        """
        if self.client is None:
            return None
        try:
            rh, t, dp = self.read_measurements()
        except Exception as e:
            print(f"Error reading {self.name}: {e}")
            return None
        return {key: self._usable(key, value) for key, value in
                (("rh", rh), ("temp", t), ("dewpoint", dp))}

    def _usable(self, key: str, value: float):
        """``value`` unless the probe reported it as unavailable (NaN)."""
        if value is not None and math.isfinite(value):
            return value
        if key not in self._unavailable:
            self._unavailable.add(key)
            print(f"{self.name}: {key} reads as unavailable (NaN) — the probe "
                  f"is not producing that quantity on its Modbus registers.")
        return None

    def regs_to_float(self, registers: list[int], hi_idx: int) -> float:
        """HMP110 stores 32-bit floats as two 16-bit regs, little-endian word order."""
        raw = registers[hi_idx].to_bytes(2, "big") + registers[hi_idx - 1].to_bytes(2, "big")
        return struct.unpack("!f", raw)[0]


    def read_holding_registers_compat(self, client, address, count, slave):
        """See :func:`read_holding_registers_compat`. Kept as a method because
        notebooks call it through a probe instance."""
        return read_holding_registers_compat(client, address, count, slave)


    def read_measurements(self):
        rr = self.read_holding_registers_compat(self.client, 0, 10, self.slave_addr)
        if rr.isError():
            raise IOError(rr)
        regs = rr.registers
        rh = self.regs_to_float(regs, 1)   # relative humidity [%RH]
        t = self.regs_to_float(regs, 3)    # temperature [°C]
        dp = self.regs_to_float(regs, 9)   # dew point [°C]
        return rh, t, dp



# ── Discovery ────────────────────────────────────────────────────────────────
SCAN_TIMEOUT = 0.15


def scan_vaisala(port, baudrate, addresses, timeout=SCAN_TIMEOUT,
                 should_stop=None, on_probe=None):
    found = []
    client = ModbusSerialClient(
        port=port, timeout=timeout, baudrate=baudrate,
        bytesize=8, stopbits=2, parity="N", retries=0,
    )
    if not client.connect():
        print(f"Vaisala scan: cannot open {port}")
        if on_probe:
            for _ in addresses:
                on_probe()
        return found

    try:
        for addr in addresses:
            if should_stop and should_stop():
                break
            try:
                rr = read_holding_registers_compat(client, 0, 10, addr)
                if not rr.isError():
                    found.append(addr)
            except Exception:
                pass
            if on_probe:
                on_probe()
    finally:
        try:
            client.close()
        except Exception:
            pass
    return found


def probe_dewmaster(port, baudrate, addresses=(None,), timeout=None,
                    should_stop=None, on_probe=None):
    device = EdgeTechHygrometer(port, baudrate, timeout=0.5, name="DewMaster scan",
                                read_timeout=1.5, nudge_interval=0.4)
    try:
        ok = bool(device.connect())
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
