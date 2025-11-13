import minimalmodbus
import struct
import time


class VogtlinMFC:
    """
    Wrapper class for Vögtlin Mass Flow Controllers using Modbus RTU via RS-485.
    """
    # Register map (base addresses) https://www.voegtlin.com/data/329-3042_en_manualsmart_digicom.pdf
    REG = {
        "flow": 0x0000,
        "temperature": 0x0002,
        "total_flow": 0x0004,
        "setpoint": 0x0006,
        "analog_input": 0x0008,
        "valve_signal": 0x000A,
        "alarm": 0x000C,
        "error": 0x000D,
        "control_function": 0x000E,
        "ramp": 0x000F,
    }

    def __init__(self, port: str, address: int, baudrate: int = 9600, name: str = "MFC"):
        self.port = port
        self.baudrate = baudrate
        self.address = address
        self.name = name
        self.instrument = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def connect(self) -> bool:
        try:
            self.instrument = minimalmodbus.Instrument(self.port, self.address, mode=minimalmodbus.MODE_RTU)
            self.instrument.serial.baudrate = self.baudrate
            self.instrument.serial.bytesize = 8
            self.instrument.serial.parity = minimalmodbus.serial.PARITY_NONE
            self.instrument.serial.stopbits = 1
            self.instrument.serial.timeout = 0.5
            time.sleep(0.5)  # wait for bus to stabilize
            print(f"Connected to {self.name} at {self.port} (addr={self.address})")
            return True
        except Exception as e:
            print(f"Error connecting to {self.name} on {self.port}: {e}")
            return False

    def disconnect(self):
        if self.instrument and self.instrument.serial.is_open:
            self.instrument.serial.close()
            print(f"Disconnected {self.name}.")

    # ----------------------------
    # Low-level helpers
    # ----------------------------
    def _read_float(self, address: int, swap: bool = False) -> float:
        """Reads 2 consecutive Modbus registers as a float."""
        regs = self.instrument.read_registers(address, 2)
        if swap:
            regs = regs[::-1]
        raw_bytes = struct.pack('>HH', *regs)
        return struct.unpack('>f', raw_bytes)[0]

    def _write_float(self, address: int, value: float, swap: bool = False):
        """Writes a float into 2 consecutive Modbus registers."""
        raw_bytes = struct.pack('>f', value)
        regs = list(struct.unpack('>HH', raw_bytes))
        if swap:
            regs = regs[::-1]
        self.instrument.write_registers(address, regs)

    # ----------------------------
    # High-level MFC functions
    # ----------------------------
    def get_flow(self) -> float:
        """Reads the measured gas flow."""
        return self._read_float(self.REG["flow"])

    def get_temperature(self) -> float:
        """Reads gas temperature."""
        return self._read_float(self.REG["temperature"])

    def get_total_flow(self) -> float:
        """Reads totalized gas flow."""
        return self._read_float(self.REG["total_flow"])

    def get_valve_signal(self) -> float:
        """Reads valve control signal."""
        return self._read_float(self.REG["valve_signal"])

    def get_setpoint(self) -> float:
        """Reads current flow setpoint."""
        return self._read_float(self.REG["setpoint"])

    def set_flow_setpoint(self, value: float):
        """Writes new gas flow setpoint."""
        self._write_float(self.REG["setpoint"], value)
        print(f"Setpoint updated to {value:.3f}")

    def get_status(self) -> dict:
        """Convenient snapshot of key values."""
        return {
            "flow": self.get_flow(),
            "setpoint": self.get_setpoint(),
            "temperature": self.get_temperature(),
            "valve_signal": self.get_valve_signal(),
        }
