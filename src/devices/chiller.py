import serial
import time

class JulaboChiller:
    def __init__(self, port, baudrate=9600, timeout=1):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None
        self.connected = False

    def __enter__(self):
        self.connect()
        return self

    def connect(self):
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS, # 8 data bits (standard with Parity None) [cite: 22]
                parity=serial.PARITY_NONE, # Default parity often None [cite: 22]
                stopbits=serial.STOPBITS_ONE,
                timeout=self.timeout
            )
            print(f"Connected to Chiller on {self.port} at {self.baudrate} baud.")
            self.connected = True
            return True
        except serial.SerialException as e:
            print(f"Error connecting to Chiller serial port: {e}")
            self.ser = None
            return False

    def disconnect(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("Chiller connection closed.")
            self.ser = None

    def is_connected(self) -> bool:
        return self.connected

    def _reconnect(self):
        """Close and reopen the serial port after a write failure."""
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

    def get_internal_temperature(self):
        self.send_command("in_pv_00")
        resp = self.read_response()
        try:
            return float(resp) if resp else None
        except ValueError:
            return None

    def get_external_temperature(self):
        self.send_command("in_pv_02")
        resp = self.read_response()
        try:
            return float(resp) if resp else None
        except ValueError:
            return None

    def get_setpoint_temperature(self):
        self.send_command("in_sp_00")
        resp = self.read_response()
        try:
            return float(resp) if resp else None
        except ValueError:
            return None

    def set_setpoint_temperature(self, temperature):
        # Ensure format matches "OUT_SP_00_55.5" structure
        command = f"out_sp_00 {temperature}"
        self.send_command(command)
        print(f"Set temperature to {temperature}")

    def start_control(self):
        self.send_command("out_mode_05 1")
        print("Sent START command.")

    def stop_control(self):
        self.send_command("out_mode_05 0")
        print("Sent STOP command.")

    def close(self):
        self.disconnect()
