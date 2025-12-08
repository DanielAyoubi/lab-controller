import pytest
from unittest.mock import MagicMock, patch
from src.devices.controller import Controller

@pytest.fixture
def mock_config():
    return {
        'dry_mfc_enabled': True,
        'dry_mfc_port': 'COM1',
        'wet_mfc_enabled': True,
        'wet_mfc_port': 'COM2',
        'hygrometer_enabled': True,
        'hygrometer_port': 'COM3',
        't_probe_enabled': True,
        'log_dir': 'test_data',
        'log_prefix': 'test_log'
    }

@pytest.fixture
def mock_devices():
    with patch("src.devices.controller.VogtlinMFC") as mock_mfc, \
         patch("src.devices.controller.DewMaster") as mock_dew, \
         patch("src.devices.controller.Thermocouple") as mock_tc, \
         patch("src.devices.controller.DataLogger") as mock_logger:
        
        # Set default values on the mock class to avoid format errors
        mock_tc.DEFAULT_VENDOR_ID = 0x2177
        mock_tc.DEFAULT_PRODUCT_ID = 0x0004
        
        yield {
            'mfc': mock_mfc,
            'dew': mock_dew,
            'tc': mock_tc,
            'logger': mock_logger
        }

def test_controller_init(mock_config, mock_devices):
    ctrl = Controller(mock_config)
    assert ctrl.config == mock_config
    assert ctrl.running is False
    # Logger should be initialized
    mock_devices['logger'].assert_called_once()

def test_controller_connect_devices_success(mock_config, mock_devices):
    ctrl = Controller(mock_config)
    
    # Setup mocks to return success on connect
    mock_devices['mfc'].return_value.connect.return_value = True
    mock_devices['dew'].return_value.connect.return_value = True
    mock_devices['tc'].return_value.connect.return_value = True
    
    assert ctrl.connect_devices() is True
    
    # Verify all devices were initialized and connected
    assert mock_devices['mfc'].call_count == 2 # Dry and Wet
    assert mock_devices['dew'].call_count == 1
    assert mock_devices['tc'].call_count == 1
    
    assert ctrl.dry_mfc is not None
    assert ctrl.wet_mfc is not None
    assert ctrl.hygrometer is not None
    assert ctrl.t_probe is not None

def test_controller_connect_devices_partial_failure(mock_config, mock_devices):
    ctrl = Controller(mock_config)
    
    # Fail one device
    mock_devices['mfc'].return_value.connect.return_value = True
    mock_devices['dew'].return_value.connect.return_value = False # Fail hygrometer
    mock_devices['tc'].return_value.connect.return_value = True
    
    assert ctrl.connect_devices() is False
    
    # Check that hygrometer was attempted
    mock_devices['dew'].assert_called()

def test_controller_disconnect_devices(mock_config, mock_devices):
    ctrl = Controller(mock_config)
    
    # Mock the device instances on the controller
    ctrl.dry_mfc = MagicMock()
    ctrl.wet_mfc = MagicMock()
    ctrl.hygrometer = MagicMock()
    ctrl.t_probe = MagicMock()
    
    ctrl.disconnect_devices()
    
    ctrl.dry_mfc.disconnect.assert_called_once()
    ctrl.wet_mfc.disconnect.assert_called_once()
    ctrl.hygrometer.disconnect.assert_called_once()
    ctrl.t_probe.disconnect.assert_called_once()
