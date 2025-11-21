import usb.core
import time
import struct
from datetime import datetime, timezone

# Find Device
dev = usb.core.find(idVendor=0x2177, idProduct=0x0004)
if dev is None:
    raise ValueError("CA 1821 not found")

# Set the active configuration. With no arguments, the first configuration will be the active one
dev.set_configuration()

# Define endpoints
ep_in = 0x84 # Instrument -> PC
ep_out = 0x03 # PC -> Instrument

# Send SET_REPORT (Feature Report, Report ID 0)
dev.ctrl_transfer(
    bmRequestType=0x21,  # Host to device | Class | Interface
    bRequest=0x09,       # SET_REPORT
    wValue=0x0300,       # Feature Report (0x03), Report ID 0
    wIndex=1,            # Interface 1
    data_or_wLength=[0x25, 0x00, 0x00]  # The 3 bytes
)

print("-----")
# Read data to clear initial buffer (probably not needed after debugging)
for ii in range(10):
    try:
        dev.read(ep_in, 1048, timeout=200)
        print("Clearing initial buffer read")
    except usb.core.USBError:
        print("No more data to clear")
        # Ignore USB timeout/read errors here and continue with empty bytes
        break

# Read temperature data in a loop
for ii in range(0,20): #range(len(results)):

    # Send command to read temperature (hex string, 64 bytes) "3a303131343037303630303130303038303030313433410d0a3130303030323030303139380d0a34303030323230303034303630303430303033303030303133"
    dev.write(ep_out, bytes.fromhex("3a303131343037303630303130303038303030313433410d0a000000000000000000000000000000000000000000000000000000000000000000000000000000"))
    # Read response (128 bytes with 2 second timeout)
    readdata = dev.read(ep_in, 128, timeout=2000)
    
    # Convert read data to ASCII string for parsing
    databytes = bytes(readdata)
    textascii = databytes.decode('ascii',errors='ignore').replace('\r', '\\r').replace('\n', '\\n')
    # print(f"Received: {textascii}")

    # Extract the relevant hex string for temperature
    hex_string = textascii[33:41] 
    # print(f"Hex string to convert: {hex_string}")
    hex_date = textascii[17:25]
    # print(f"Date: {hex_date}")

    # Konverter hex til decimal (Unix-tid)
    unix_timestamp = int(hex_date, 16)
    # print(f"Unix Timestamp: {unix_timestamp}")

    # Konverter til datetime-objekt
    dt = datetime.fromtimestamp(unix_timestamp, tz=timezone.utc)
    # print(f"Timestamp: {dt}")

    # First, convert the hex string to bytes
    byte_data = bytes.fromhex(hex_string)
    
    # Then, unpack the bytes as a big-endian float
    big_endian = struct.unpack('>f', byte_data)[0]
    # print(f"Big-endian float: {big_endian_int} at {ii}")
    
    print(f"Temperature: {big_endian:.2f} °C")
    # time.sleep(1.01)
