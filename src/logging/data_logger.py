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
        self.fieldnames = fieldnames
        self.current_file = self._generate_filename()
        
        # Write header
        with open(self.current_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=self.fieldnames)
            writer.writeheader()
        
        print(f"Started new log file: {self.current_file}")
    
    def log_data(self, data: Dict[str, any]):
        """
        Log a data point to the current log file.
        
        Args:
            data: Dictionary of data to log (keys must match fieldnames)
        """
        if not self.current_file or not self.fieldnames:
            raise ValueError("No log file started. Call start_new_log() first.")
        
        # Add timestamp if not present
        if 'timestamp' not in data:
            data['timestamp'] = datetime.now().isoformat()
        
        # Write data
        with open(self.current_file, 'a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=self.fieldnames)
            writer.writerow(data)
    
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
