import pytest
from unittest.mock import MagicMock, patch
import serial
import minimalmodbus
import usb.core
from src.devices.hygrometer import DewMaster
from src.devices.vogtlin_mfc import VogtlinMFC
from src.devices.thermocouple import Thermocouple

# --- DewMaster Tests ---

@pytest.fixture
def mock_serial():
    with patch("serial.Serial") as mock:
        yield mock

def test_dewmaster_connect(mock_serial):
    dm = DewMaster(port="COM1", baudrate=9600)
    assert dm.connect() is True
    mock_serial.assert_called_with("COM1", 9600, timeout=2.0)

def test_dewmaster_connect_fail(mock_serial):
    mock_serial.side_effect = serial.SerialException("Connection failed")
    dm = DewMaster(port="COM1", baudrate=9600)
    with pytest.raises(RuntimeError):
        dm.connect()

def test_dewmaster_get_readings(mock_serial):
    dm = DewMaster(port="COM1", baudrate=9600)
    dm.connect()
    
    # Mock the serial instance returned by serial.Serial()
    mock_ser_instance = mock_serial.return_value
    mock_ser_instance.is_open = True
    mock_ser_instance.in_waiting = 50
    # Simulate response: "DP = 10.5 C  AT = 25.0 C  RH = 45.0"
    mock_ser_instance.read.return_value = b"DP = 10.5 C  AT = 25.0 C  RH = 45.0"
    
    readings = dm.get_readings()
    assert readings is not None
    assert readings["dewpoint_temp"] == 10.5
    assert readings["ambient_temp"] == 25.0
    assert readings["relative_humidity_device"] == 45.0
    # Check calculated RH is present (value depends on formula, just check existence)
    assert "relative_humidity_calculated" in readings

# --- VogtlinMFC Tests ---

@pytest.fixture
def mock_minimalmodbus():
    with patch("minimalmodbus.Instrument") as mock:
        yield mock

def test_mfc_connect(mock_minimalmodbus):
    mfc = VogtlinMFC(port="COM2", address=1)
    assert mfc.connect() is True
    mock_minimalmodbus.assert_called_with("COM2", 1, mode=minimalmodbus.MODE_RTU)

def test_mfc_get_flow(mock_minimalmodbus):
    mfc = VogtlinMFC(port="COM2", address=1)
    mfc.connect()
    
    mock_inst = mock_minimalmodbus.return_value
    # Mock read_registers to return bytes for float 10.0
    # 10.0 float is 0x41200000. 
    # struct.unpack(">HH", struct.pack(">f", 10.0)) -> (16672, 0)
    mock_inst.read_registers.return_value = [16672, 0]
    
    flow = mfc.get_flow()
    assert flow == 10.0
    mock_inst.read_registers.assert_called_with(0x0000, 2)

def test_mfc_set_flow(mock_minimalmodbus):
    mfc = VogtlinMFC(port="COM2", address=1)
    mfc.connect()
    
    assert mfc.set_flow(5.0) is True
    # Verify write_registers called with correct values for 5.0
    # 5.0 float is 0x40a00000 -> (16544, 0)
    mock_inst = mock_minimalmodbus.return_value
    mock_inst.write_registers.assert_called_with(0x0006, [16544, 0])

# --- Thermocouple Tests ---

@pytest.fixture
def mock_usb():
    with patch("usb.core.find") as mock_find, \
         patch("usb.util.claim_interface") as mock_claim, \
         patch("libusb_package.find_library") as mock_lib:
        yield mock_find

def test_thermocouple_connect(mock_usb):
    mock_device = MagicMock()
    mock_usb.return_value = mock_device
    
    tc = Thermocouple()
    # Mock _clear_initial_buffer to avoid actual USB calls during connect
    with patch.object(tc, '_clear_initial_buffer'):
        assert tc.connect() is True
    
    mock_usb.assert_called()
    assert tc._connected is True

def test_thermocouple_connect_fail(mock_usb):
    mock_usb.return_value = None
    tc = Thermocouple()
    assert tc.connect() is False
