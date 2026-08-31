import csv
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


# Filename prefix for automated-experiment logs. Shared so the calibration
# tool looks for the same files run_automated_experiment() writes.
RAMP_LOG_PREFIX = "RH_ramp"


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

        # The timestamp only resolves to the second, so two logs started in the
        # same second would land on the same path and the first would be
        # silently overwritten (start_new_log opens with "w"). That is reachable
        # whenever a log is rotated promptly — e.g. after a device rename
        # changes the column set.
        candidate = daily_dir / f"{p}_{timestamp}.csv"
        n = 2
        while candidate.exists():
            candidate = daily_dir / f"{p}_{timestamp}_{n}.csv"
            n += 1
        return str(candidate)

    def start_new_log(self, fieldnames: List[str], prefix: Optional[str] = None):
        # Close existing file handle if open
        self.close()

        self.fieldnames = fieldnames
        self.current_file = self._generate_filename(prefix=prefix)

        # Held open for the life of the log: reopening per row would cost a
        # directory lookup and an open() every poll, and on the network share
        # `log_dir` usually points at that is far more expensive than the write
        # itself. Each row is flushed instead — see log_data().
        self._file_handle = open(self.current_file, "w", newline="")
        # extrasaction="ignore": the field list is derived from the configured
        # device set, so a reading arriving from a device that was removed
        # mid-session is dropped rather than raising in the poll loop.
        self._csv_writer = csv.DictWriter(
            self._file_handle, fieldnames=self.fieldnames, extrasaction="ignore"
        )
        self._csv_writer.writeheader()
        self._file_handle.flush()  # Ensure header is written immediately

        print(f"Started new log file: {self.current_file}")

    def log_data(self, data: Dict[str, any]):
        """Append one row and push it to disk immediately.

        The flush is what makes the log a *stream*: without it the row sits in
        Python's buffer until it fills or the file is closed, so a run in
        progress reads as minutes behind (or as an empty file), and a crash or a
        killed process loses everything buffered since the last boundary. An
        experiment can run for hours and is exactly when someone wants to open
        the CSV and watch it, so the row has to be there as soon as it is taken.

        The cost is one small write per poll — a couple of hundred bytes every
        ``control_interval`` — which is nothing next to the serial round-trips
        that produced the row, and it happens on the poll/experiment thread, not
        the GUI thread. ``flush()`` hands the bytes to the OS, which is what
        makes them visible to other readers; ``os.fsync()`` would additionally
        force them onto the physical device and is deliberately not called, as
        it costs orders of magnitude more and only buys anything against a power
        cut rather than against the process dying.
        """
        if not self._csv_writer or not self.fieldnames:
            raise ValueError("No log file started. Call start_new_log() first.")

        # Add timestamp if not present
        if "timestamp" not in data:
            data["timestamp"] = datetime.now().isoformat()

        self._csv_writer.writerow(data)
        self._file_handle.flush()

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
