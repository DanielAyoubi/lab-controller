import pytest
from unittest.mock import MagicMock, patch
from src.devices.controller import Controller

@pytest.fixture
def mock_config():
    return {
        'dry_mfc_enabled': True,
        'dry_mfc_port': 'COM1',
        'dry_mfc_address': 1,
        'wet_mfc_enabled': True,
        'wet_mfc_port': 'COM2',
        'wet_mfc_address': 2,
        'hygrometer_enabled': True,
        'hygrometer_port': 'COM3',
        'hygrometer_baudrate': 19200,
        'chiller_enabled': True,
        'chiller_port': 'COM4',
        'chiller_baudrate': 9600,
        'log_dir': 'test_data',
        'log_prefix': 'test_log'
    }

@pytest.fixture
def mock_devices():
    with patch("src.devices.controller.VogtlinMFC") as mock_mfc, \
         patch("src.devices.controller.Hygrometer") as mock_hyg, \
         patch("src.devices.controller.JulaboChiller") as mock_chill, \
         patch("src.devices.controller.DataLogger") as mock_logger:
        
        yield {
            'mfc': mock_mfc,
            'hygrometer': mock_hyg,
            'chiller': mock_chill,
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
    mock_devices['hygrometer'].return_value.connect.return_value = True
    mock_devices['chiller'].return_value.connect.return_value = True
    
    ctrl.connect_devices()
    
    # Verify all devices were initialized and connected
    assert mock_devices['mfc'].call_count == 2  # Dry and Wet
    assert mock_devices['hygrometer'].call_count == 1
    assert mock_devices['chiller'].call_count == 1
    
    assert ctrl.dry_mfc is not None
    assert ctrl.wet_mfc is not None
    assert ctrl.hygrometer is not None
    assert ctrl.chiller is not None

def test_controller_disconnect_devices(mock_config, mock_devices):
    ctrl = Controller(mock_config)
    
    # Mock the device instances on the controller
    ctrl.dry_mfc = MagicMock()
    ctrl.wet_mfc = MagicMock()
    ctrl.hygrometer = MagicMock()
    ctrl.chiller = MagicMock()
    
    ctrl.disconnect_devices()
    
    ctrl.dry_mfc.disconnect.assert_called_once()
    ctrl.wet_mfc.disconnect.assert_called_once()
    ctrl.hygrometer.disconnect.assert_called_once()
    ctrl.chiller.disconnect.assert_called_once()
