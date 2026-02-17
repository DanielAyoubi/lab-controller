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
            # We need to modify the controller's run_automated_experiment to be interruptible 
            # or we just run it and hope for the best. 
            # Ideally, the controller should have a 'stop' flag we can set.
            # The controller has a 'running' flag but run_automated_experiment seems to have its own loop.
            
            # For now, we will call the blocking function. 
            # Note: This will block this thread, which is fine.
            # But we can't easily stop it unless we modify the controller.

            # Use `control_interval` (seconds) from config as the control interval
            try:
                control_interval_sec = float(self.config.get('control_interval', 1.0))
            except Exception:
                control_interval_sec = 1.0

            self.controller.run_automated_experiment(
                min_rh=self.config.get('experiment_min_rh', 0.0),
                max_rh=self.config.get('experiment_max_rh', 100.0),
                direction=self.config.get('experiment_direction', 'up'),
                ramp_rate=self.config.get('experiment_ramp_rate', 0.5),
                max_flow=self.config.get('max_flow', 2.0),
                control_interval=control_interval_sec,
                on_data=self.data_ready.emit
            )
            self.progress.emit("Experiment completed successfully.")
            self.finished.emit()
            
        except Exception as e:
            self.error.emit(str(e))
            self.finished.emit()

    def stop(self):
        self._is_running = False
        # We should also signal the controller to stop if possible
        self.controller.running = False
