import serial
import time

# --- Serial port configuration ---
PORT = "/dev/ttyS3"          # e.g., /dev/ttyUSB0 on Linux
BAUDRATE = 9600
TIMEOUT = 1

# --- Open the serial connection ---
ser = serial.Serial(PORT, BAUDRATE, bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE, timeout=TIMEOUT)
time.sleep(1)

# --- Optional: set output interval to 1 second ---
# DewMaster expects "O<CR>1<CR>"
ser.reset_input_buffer()
# ser.write(b"O\r1\r")

print("Reading data from DewMaster (Ctrl+C to stop)...\n")

try:
    while True:
        # Ask for one reading explicitly (poll)
        ser.write(b"P\r\n")   # “Poll” command requests a data line
        time.sleep(0.2)
        line = ser.readline().decode(errors='ignore').strip()
        if line:
            print(f"{line}")
        time.sleep(1)
except KeyboardInterrupt:
    print("\nStopped by user.")
finally:
    ser.close()

