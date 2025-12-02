import struct
import time
from datetime import datetime, timezone
from typing import Optional, Tuple

import usb.core
import usb.util


class Thermocouple:
    DEFAULT_VENDOR_ID = 0x2177
    DEFAULT_PRODUCT_ID = 0x0004
    DEFAULT_INTERFACE = 1
    DEFAULT_EP_IN = 0x84
    DEFAULT_EP_OUT = 0x03
    DEFAULT_READ_TIMEOUT_MS = 2000
    DEFAULT_CLEAR_READS = 10
    DEFAULT_CLEAR_READ_LENGTH = 1048
    TEMPERATURE_COMMAND = bytes.fromhex(
        "3a303131343037303630303130303038303030313433410d0a000000000000000000000000000000000000000000000000000000000000000000000000000000"
    )

    def __init__(
        self,
        port: Optional[str] = None,  # Unused but kept for API symmetry with other drivers
        *,
        vendor_id: int = DEFAULT_VENDOR_ID,
        product_id: int = DEFAULT_PRODUCT_ID,
        interface: int = DEFAULT_INTERFACE,
        read_endpoint: int = DEFAULT_EP_IN,
        write_endpoint: int = DEFAULT_EP_OUT,
        read_timeout_ms: int = DEFAULT_READ_TIMEOUT_MS,
        clear_buffer_reads: int = DEFAULT_CLEAR_READS,
        buffer_read_length: int = DEFAULT_CLEAR_READ_LENGTH,
        cache_duration_ms: int = 100,  # Cache readings for 100ms to reduce USB polling
    ):
        self.port = port
        self.vendor_id = vendor_id
        self.product_id = product_id
        self.interface = interface
        self.read_endpoint = read_endpoint
        self.write_endpoint = write_endpoint
        self.read_timeout_ms = read_timeout_ms
        self.clear_buffer_reads = clear_buffer_reads
        self.buffer_read_length = buffer_read_length
        self.cache_duration_ms = cache_duration_ms

        self.device: Optional[usb.core.Device] = None
        self._connected = False
        self._claimed_interface: Optional[int] = None
        self._last_sample_time: Optional[datetime] = None
        self._cached_temperature: Optional[float] = None
        self._cache_timestamp: float = 0.0  # Use time.time() for better performance

    def connect(self) -> bool:
        try:
            self.device = usb.core.find(idVendor=self.vendor_id, idProduct=self.product_id)
            if self.device is None:
                raise ValueError("Thermocouple device not found")

            self.device.set_configuration()

            # Some hosts require detaching existing kernel drivers. Not all backends implement this.
            if hasattr(self.device, "is_kernel_driver_active"):
                try:
                    if self.device.is_kernel_driver_active(self.interface):
                        self.device.detach_kernel_driver(self.interface)
                except (NotImplementedError, usb.core.USBError):
                    # Windows / libusb-win32 backend may raise here; safe to continue.
                    pass

            usb.util.claim_interface(self.device, self.interface)
            self._claimed_interface = self.interface

            self._connected = True
            print("Thermocouple connected")

            self._clear_initial_buffer()
            return True
        except Exception as exc:
            print(f"Failed to connect Thermocouple: {exc}")
            self.device = None
            self._connected = False
            return False

    def disconnect(self):
        if not self.device:
            return

        try:
            if self._claimed_interface is not None:
                usb.util.release_interface(self.device, self._claimed_interface)
                if hasattr(self.device, "attach_kernel_driver"):
                    try:
                        self.device.attach_kernel_driver(self._claimed_interface)
                    except (NotImplementedError, usb.core.USBError):
                        # Backend might not support re-attaching; ignore.
                        pass
            usb.util.dispose_resources(self.device)
        finally:
            self.device = None
            self._connected = False
            self._claimed_interface = None
            print("Thermocouple disconnected")

    def get_temperature(self) -> Optional[float]:
        if not self._connected and not self.connect():
            return None

        if self.device is None:
            return None

        # Check if cached value is still valid (using time.time() for performance)
        current_time = time.time()
        cache_age_ms = (current_time - self._cache_timestamp) * 1000
        if self._cached_temperature is not None and cache_age_ms < self.cache_duration_ms:
            return self._cached_temperature

        try:
            self.device.write(self.write_endpoint, self.TEMPERATURE_COMMAND)
            raw = self.device.read(self.read_endpoint, 128, timeout=self.read_timeout_ms)
        except usb.core.USBError as exc:  # pragma: no cover - hardware specific
            print(f"USB error while reading thermocouple: {exc}")
            return None

        temperature, timestamp = self._parse_frame(bytes(raw))
        if timestamp:
            self._last_sample_time = timestamp
        
        # Update cache (using time.time() for performance)
        if temperature is not None:
            self._cached_temperature = temperature
            self._cache_timestamp = current_time
        
        return temperature

    def get_last_sample_time(self) -> Optional[datetime]:
        return self._last_sample_time

    # ----------------------------
    # Internal helpers
    # ----------------------------
    def _clear_initial_buffer(self):
        if not self.device:
            return

        for _ in range(self.clear_buffer_reads):
            try:
                self.device.read(self.read_endpoint, self.buffer_read_length, timeout=200)
            except usb.core.USBError:
                break

    @staticmethod
    def _parse_frame(payload: bytes) -> Tuple[Optional[float], Optional[datetime]]:
        try:
            text = payload.decode("ascii", errors="ignore")
            hex_temp = text[33:41]
            hex_time = text[17:25]

            temperature = struct.unpack(">f", bytes.fromhex(hex_temp))[0]
            timestamp = datetime.fromtimestamp(int(hex_time, 16), tz=timezone.utc)
            return temperature, timestamp
        except (ValueError, struct.error):
            return None, None
