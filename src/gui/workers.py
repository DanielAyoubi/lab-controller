import time

from PyQt6.QtCore import QThread, pyqtSignal
from typing import Dict, Any


class PollWorker(QThread):
    """Polls sensors on a background thread so the GUI stays responsive."""
    data_ready = pyqtSignal(dict)

    def __init__(self, controller, interval_ms: int):
        super().__init__()
        self.controller = controller
        self.interval_ms = interval_ms
        self._running = False

    def run(self):
        self._running = True
        while self._running:
            t0 = time.monotonic()
            try:
                data = self.controller.read_and_log()
                self.data_ready.emit(data)
            except Exception as e:
                print(f"PollWorker error: {e}")
            # Sleep in small chunks so stop() is responsive
            deadline = t0 + self.interval_ms / 1000.0
            while self._running and time.monotonic() < deadline:
                time.sleep(0.05)

    def stop(self):
        self._running = False


class FlowRampWorker(QThread):
    """Runs a flow ramp on a background thread so the GUI stays responsive."""
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, controller, dry_flow, wet_flow):
        super().__init__()
        self.controller = controller
        self.dry_flow = dry_flow
        self.wet_flow = wet_flow

    def run(self):
        try:
            self.controller.set_flow_rates(
                dry_flow=self.dry_flow,
                wet_flow=self.wet_flow,
                ramp_flow=True,
            )
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()


class ExperimentWorker(QThread):
    finished = pyqtSignal()
    error = pyqtSignal(str)
    progress = pyqtSignal(str)  # For status updates
    data_ready = pyqtSignal(dict)

    def __init__(self, controller, config: Dict[str, Any]):
        super().__init__()
        self.controller = controller
        self.config = config
        self._is_running = True

    def run(self):
        try:
            self.progress.emit("Starting experiment...")

            try:
                control_interval_sec = float(self.config.get('control_interval', 5000)) / 1000.0
            except Exception:
                control_interval_sec = 5.0

            plot_path = self.controller.run_automated_experiment(
                direction=self.config.get('experiment_direction', 'up'),
                step_size=self.config.get('experiment_step_size', 5.0),
                max_flow=self.config.get('max_flow', 2.0),
                control_interval=control_interval_sec,
                hold_time=self.config.get('experiment_hold_time', 180.0),
                rh_lower=float(self.config.get('experiment_rh_lower', 0.0)),
                rh_upper=float(self.config.get('experiment_rh_upper', 90.0)),
                stability_readings=int(self.config.get('experiment_stability_readings', 5)),
                stability_timeout=float(self.config.get('experiment_stability_timeout', 600.0)),
                on_data=self.data_ready.emit,
                on_progress=self.progress.emit,
            )
            if plot_path:
                self.progress.emit(f"PLOT_PATH:{plot_path}")
            self.progress.emit("Experiment completed successfully.")
            self.finished.emit()

        except Exception as e:
            self.error.emit(str(e))
            self.finished.emit()

    def stop(self):
        self._is_running = False
        # We should also signal the controller to stop if possible
        self.controller.running = False
