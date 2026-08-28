from typing import Optional
import minimalmodbus
import serial
import struct
import time


class VogtlinMFC:
    # Register map (base addresses) https://www.voegtlin.com/data/329-3042_en_manualsmart_digicom.pdf
    REG = {
        "flow": 0x0000,
        "temperature": 0x0002,
        "setpoint": 0x0006,
        "valve_signal": 0x000A,
    }

    def __init__(
        self, port: str, address: int, baudrate: int = 9600, name: str = "MFC"
    ):
        self.port = port
        self.baudrate = baudrate
        self.address = address
        self.name = name
        self.instrument: Optional[minimalmodbus.Instrument] = None
        self.connected = False

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    def connect(self) -> bool:
        # Close any stale handle first so reconnecting after a dropout re-opens
        # the port cleanly instead of failing on an already-open handle.
        if self.instrument is not None:
            try:
                self.instrument.serial.close()
            except Exception:
                pass
            self.instrument = None
        try:
            self.instrument = minimalmodbus.Instrument(
                self.port, self.address, mode=minimalmodbus.MODE_RTU
            )
            self.instrument.serial.baudrate = self.baudrate
            self.instrument.serial.timeout = 0.5
            time.sleep(0.5)  # wait for bus to stabilize
        except Exception as e:
            print(f"Error opening {self.name} port {self.port}: {e}")
            self.instrument = None
            self.connected = False
            return False

        # Opening the serial port only proves the USB adapter is present — it does
        # not prove the MFC is powered on and answering on this Modbus address.
        # Probe with a real register read so a powered-off device reports as failed.
        try:
            self._read_float(self.REG["flow"])
        except Exception as e:
            print(f"{self.name} on {self.port} (addr={self.address}): "
                  f"port opened but device did not respond (powered off?): {e}")
            try:
                self.instrument.serial.close()
            except Exception:
                pass
            self.instrument = None
            self.connected = False
            return False

        print(f"Connected to {self.name} at {self.port} (addr={self.address})")
        self.connected = True
        return True

    def disconnect(self):
        if self.instrument and self.instrument.serial.is_open:
            try:
                self.set_flow(0.0)
            except Exception:
                pass
            self.instrument.serial.close()
            print(f"Disconnected {self.name}.")
        self.connected = False

    def is_connected(self) -> bool:
        return self.connected

    def _read_float(self, address: int) -> float:
        regs = self.instrument.read_registers(address, 2)
        raw_bytes = struct.pack(">HH", *regs)
        return struct.unpack(">f", raw_bytes)[0]

    def _write_float(self, address: int, value: float):
        raw_bytes = struct.pack(">f", value)
        regs = list(struct.unpack(">HH", raw_bytes))
        self.instrument.write_registers(address, regs)

    def get_flow(self) -> float:
        return self._read_float(self.REG["flow"])

    def get_temperature(self) -> float:
        return self._read_float(self.REG["temperature"])

    def get_valve_signal(self) -> float:
        return self._read_float(self.REG["valve_signal"])

    def get_setpoint(self) -> float:
        return self._read_float(self.REG["setpoint"])

    def set_flow(self, value: float) -> bool:
        try:
            self._write_float(self.REG["setpoint"], value)
            return True
        except Exception as e:
            print(f"Error setting flow on {self.name}: {e}")
            return False

    def read(self) -> dict:
        return {"flow": self.get_flow(), "setpoint": self.get_setpoint()}

    def get_status(self) -> dict:
        return {
            "flow": self.get_flow(),
            "setpoint": self.get_setpoint(),
            "temperature": self.get_temperature(),
            "valve_signal": self.get_valve_signal(),
        }


# ── Discovery ────────────────────────────────────────────────────────────────

# Time to wait for a reply while sweeping addresses. A Vogtlin answers a
# 2-register read in well under 20 ms at 9600 baud, but a USB-serial adapter
# adds its own latency (FTDI ships with a 16 ms latency timer), so anything
# below ~50 ms starts missing live devices. Only *silent* addresses cost the
# full timeout — minimalmodbus reads a known number of bytes and returns as
# soon as they arrive — so a hit is cheap and a miss is the 0.1 s.
SCAN_TIMEOUT = 0.1


def scan(port, baudrate, addresses, timeout=SCAN_TIMEOUT,
         should_stop=None, on_probe=None):
    found = []
    ser = None
    try:
        ser = serial.Serial(port=port, baudrate=baudrate, bytesize=8,
                            parity=serial.PARITY_NONE, stopbits=1,
                            timeout=timeout, write_timeout=2.0)
    except Exception as e:
        print(f"MFC scan: cannot open {port}: {e}")
        # Still report the skipped work so the progress bar stays truthful.
        if on_probe:
            for _ in addresses:
                on_probe()
        return found

    try:
        instrument = minimalmodbus.Instrument(ser, 1, mode=minimalmodbus.MODE_RTU)
        for addr in addresses:
            if should_stop and should_stop():
                break
            instrument.address = addr
            try:
                regs = instrument.read_registers(VogtlinMFC.REG["flow"], 2)
                # A reply that decodes as a float is the confirmation — a bare
                # ACK could come from any Modbus slave on a shared bus.
                struct.unpack(">f", struct.pack(">HH", *regs))
                found.append(addr)
            except Exception:
                pass
            if on_probe:
                on_probe()
    finally:
        try:
            ser.close()
        except Exception:
            pass
    return found
