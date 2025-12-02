import csv
import os
from datetime import datetime
from typing import Dict, List, Optional
from pathlib import Path


class DataLogger:
    def __init__(self, output_dir: str = "data", filename_prefix: str = "nsim_log"):
        """
        Args:
            output_dir: Directory to store log files
            filename_prefix: Prefix for log filenames
        """
        self.output_dir = Path(output_dir)
        self.filename_prefix = filename_prefix
        self.current_file: Optional[str] = None
        self.fieldnames: Optional[List[str]] = None
        self._file_handle = None
        self._csv_writer = None
        
        # Create output directory if it doesn't exist
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def _generate_filename(self) -> str:
        """
        Generate a filename with timestamp.
        
        Returns:
            Full path to log file
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{self.filename_prefix}_{timestamp}.csv"
        return str(self.output_dir / filename)
    
    def start_new_log(self, fieldnames: List[str]):
        """
        Start a new log file with specified fields.
        
        Args:
            fieldnames: List of column names for the CSV
        """
        # Close existing file handle if open
        self.close()
        
        self.fieldnames = fieldnames
        self.current_file = self._generate_filename()
        
        # Open file handle and keep it open for efficient writing
        # Use larger buffer for better performance with high-frequency logging
        self._file_handle = open(self.current_file, 'w', newline='', buffering=8192)
        self._csv_writer = csv.DictWriter(self._file_handle, fieldnames=self.fieldnames)
        self._csv_writer.writeheader()
        self._file_handle.flush()  # Ensure header is written immediately
        
        print(f"Started new log file: {self.current_file}")
    
    def log_data(self, data: Dict[str, any]):
        """
        Log a data point to the current log file.
        
        Args:
            data: Dictionary of data to log (keys must match fieldnames)
        """
        if not self._csv_writer or not self.fieldnames:
            raise ValueError("No log file started. Call start_new_log() first.")
        
        # Add timestamp if not present
        if 'timestamp' not in data:
            data['timestamp'] = datetime.now().isoformat()
        
        # Write data using cached writer (much faster than opening/closing file)
        self._csv_writer.writerow(data)
    
    def read_log(self, filename: Optional[str] = None) -> List[Dict[str, str]]:
        """
        Read data from a log file.
        
        Args:
            filename: Path to log file (uses current file if None)
            
        Returns:
            List of dictionaries containing log data
        """
        file_to_read = filename or self.current_file
        
        if not file_to_read or not os.path.exists(file_to_read):
            print(f"Log file not found: {file_to_read}")
            return []
        
        data = []
        with open(file_to_read, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                data.append(row)
        
        return data
    
    def get_current_filename(self) -> Optional[str]:
        """
        Get the path to the current log file.
        
        Returns:
            Path to current log file or None
        """
        return self.current_file
    
    def list_log_files(self) -> List[str]:
        """
        List all log files in the output directory.
        
        Returns:
            List of log file paths
        """
        pattern = f"{self.filename_prefix}_*.csv"
        return sorted([str(f) for f in self.output_dir.glob(pattern)])
    
    def close(self):
        """
        Close the current log file handle if open.
        """
        if self._file_handle:
            try:
                self._file_handle.flush()
                self._file_handle.close()
            except Exception:
                pass  # Ignore errors during cleanup
            finally:
                self._file_handle = None
                self._csv_writer = None
    
    def __del__(self):
        """
        Ensure file handle is closed on deletion.
        """
        try:
            self.close()
        except Exception:
            pass  # Prevent exceptions during garbage collection
