from typing import Optional
import minimalmodbus
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
        try:
            self.instrument = minimalmodbus.Instrument(
                self.port, self.address, mode=minimalmodbus.MODE_RTU
            )
            self.instrument.serial.baudrate = self.baudrate
            self.instrument.serial.timeout = 0.5
            time.sleep(0.5)  # wait for bus to stabilize
            print(f"Connected to {self.name} at {self.port} (addr={self.address})")
            self.connected = True
            return True
        except Exception as e:
            print(f"Error connecting to {self.name} on {self.port}: {e}")
            return False

    def disconnect(self):
        if self.instrument and self.instrument.serial.is_open:
            try:
                self.set_flow(0.0)
            except Exception:
                pass
            self.instrument.serial.close()
            print(f"Disconnected {self.name}.")

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

    def get_status(self) -> dict:
        return {
            "flow": self.get_flow(),
            "setpoint": self.get_setpoint(),
            "temperature": self.get_temperature(),
            "valve_signal": self.get_valve_signal(),
        }
