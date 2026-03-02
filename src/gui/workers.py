from PyQt6.QtCore import QThread, pyqtSignal
from typing import Dict, Any

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
                on_data=self.data_ready.emit,
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
