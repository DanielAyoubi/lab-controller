import csv
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


class DataLogger:
    def __init__(self, output_dir: str = "data", filename_prefix: str = "nsim_log"):
        self.output_dir = Path(output_dir)
        self.filename_prefix = filename_prefix
        self.current_file: Optional[str] = None
        self.fieldnames: Optional[List[str]] = None
        self._file_handle = None
        self._csv_writer = None

        # Create output directory if it doesn't exist
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _generate_filename(self, prefix: Optional[str] = None) -> str:
        now = datetime.now()
        day_folder = now.strftime("%d_%m_%Y")
        daily_dir = self.output_dir / day_folder
        daily_dir.mkdir(parents=True, exist_ok=True)
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        p = prefix if prefix is not None else self.filename_prefix
        filename = f"{p}_{timestamp}.csv"
        return str(daily_dir / filename)

    def start_new_log(self, fieldnames: List[str], prefix: Optional[str] = None):
        # Close existing file handle if open
        self.close()

        self.fieldnames = fieldnames
        self.current_file = self._generate_filename(prefix=prefix)

        # Open file handle and keep it open for efficient writing
        # Use larger buffer for better performance with high-frequency logging
        self._file_handle = open(self.current_file, "w", newline="", buffering=8192)
        self._csv_writer = csv.DictWriter(self._file_handle, fieldnames=self.fieldnames)
        self._csv_writer.writeheader()
        self._file_handle.flush()  # Ensure header is written immediately

        print(f"Started new log file: {self.current_file}")

    def log_data(self, data: Dict[str, any]):
        if not self._csv_writer or not self.fieldnames:
            raise ValueError("No log file started. Call start_new_log() first.")

        # Add timestamp if not present
        if "timestamp" not in data:
            data["timestamp"] = datetime.now().isoformat()

        # Write data using cached writer (much faster than opening/closing file)
        self._csv_writer.writerow(data)

    def read_log(self, filename: Optional[str] = None) -> List[Dict[str, str]]:
        file_to_read = filename or self.current_file

        if not file_to_read or not os.path.exists(file_to_read):
            print(f"Log file not found: {file_to_read}")
            return []

        data = []
        with open(file_to_read, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                data.append(row)

        return data

    def is_logging(self) -> bool:
        return self._csv_writer is not None

    def get_current_filename(self) -> Optional[str]:
        return self.current_file

    def list_log_files(self) -> List[str]:
        pattern = f"{self.filename_prefix}_*.csv"
        return sorted([str(f) for f in self.output_dir.glob(pattern)])

    def close(self):
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
        try:
            self.close()
        except Exception:
            pass 
