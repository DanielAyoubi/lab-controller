import pytest
import os
import csv
from src.logging.data_logger import DataLogger

def test_logger_init(tmp_path):
    log_dir = tmp_path / "logs"
    logger = DataLogger(output_dir=str(log_dir), filename_prefix="test")
    
    assert logger.output_dir == log_dir
    assert logger.filename_prefix == "test"
    assert log_dir.exists()

def test_logger_start_new_log(tmp_path):
    logger = DataLogger(output_dir=str(tmp_path))
    fields = ['timestamp', 'value']
    
    logger.start_new_log(fields)
    
    assert logger.current_file is not None
    assert os.path.exists(logger.current_file)
    assert logger.fieldnames == fields
    
    # Check header
    with open(logger.current_file, 'r') as f:
        header = f.readline().strip()
        assert header == "timestamp,value"
    
    logger.close()

def test_logger_log_data(tmp_path):
    logger = DataLogger(output_dir=str(tmp_path))
    fields = ['timestamp', 'value']
    logger.start_new_log(fields)
    
    data = {'timestamp': '2023-01-01T12:00:00', 'value': 42}
    logger.log_data(data)
    logger.close() # Ensure flush
    
    # Verify data
    with open(logger.current_file, 'r') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]['timestamp'] == '2023-01-01T12:00:00'
        assert rows[0]['value'] == '42'

def test_logger_log_data_no_start(tmp_path):
    logger = DataLogger(output_dir=str(tmp_path))
    with pytest.raises(ValueError):
        logger.log_data({'value': 1})

def test_logger_read_log(tmp_path):
    logger = DataLogger(output_dir=str(tmp_path))
    fields = ['timestamp', 'value']
    logger.start_new_log(fields)
    
    logger.log_data({'timestamp': 't1', 'value': 1})
    logger.log_data({'timestamp': 't2', 'value': 2})
    logger.close()
    
    data = logger.read_log()
    assert len(data) == 2
    assert data[0]['value'] == '1'
    assert data[1]['value'] == '2'
