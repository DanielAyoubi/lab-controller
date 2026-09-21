import math
import struct

from pymodbus.client import ModbusSerialClient


class VaisalaRH:
    label = "Vaisala HMP110"
    settings = {"port": "", "baudrate": 19200, "address": 240}
    readings = {"RH": "%", "temperature": "°C", "dewpoint": "°C"}
    controls = {}

    def __init__(self, port, baudrate=19200, address=240, timeout=1.0):
        self.port = port
        self.baudrate = baudrate
        self.address = address
        self.timeout = timeout
        self.client = None

    def connect(self):
        self.disconnect()
        self.client = ModbusSerialClient(port=self.port, baudrate=self.baudrate, bytesize=8, parity="N",
                                         stopbits=2, timeout=self.timeout, retries=1)
        if not self.client.connect():
            self.client = None
            raise IOError(f"Cannot open {self.port}")
        try:
            self.read()
        except Exception:
            self.disconnect()
            raise

    def disconnect(self):
        if self.client is not None:
            self.client.close()
            self.client = None

    def read(self):
        response = self.client.read_holding_registers(0, count=10, device_id=self.address)
        if response.isError():
            raise IOError(str(response))
        registers = response.registers
        values = {}
        # Each value is a 32-bit float in two registers, low word first.
        for key, high in (("RH", 1), ("temperature", 3), ("dewpoint", 9)):
            raw = registers[high].to_bytes(2, "big") + registers[high - 1].to_bytes(2, "big")
            value = struct.unpack(">f", raw)[0]
            # The probe reports NaN for a quantity it cannot currently produce.
            if math.isnan(value):
                value = None
            values[key] = value
        return values
