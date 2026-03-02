import time
import math
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Callable

from src.devices.vogtlin_mfc import VogtlinMFC
from src.devices.hygrometer import Hygrometer
from src.devices.chiller import JulaboChiller
from src.logging.data_logger import DataLogger


class Controller:
    def __init__(self, config: Dict):
        self.config = config
        self.running = False
        self.connected = False

        self.dry_mfc: Optional[VogtlinMFC] = None
        self.wet_mfc: Optional[VogtlinMFC] = None
        self.hygrometer: Optional[Hygrometer] = None
        self.chiller: Optional[JulaboChiller] = None

        self.logger = DataLogger(
            output_dir=self.config.get('log_dir', 'data'),
            filename_prefix=self.config.get('log_prefix', 'nsim_log'),
        )

        self.log_fields = [
            'timestamp',
            'dry_flow', 'wet_flow',
            'dry_flow_setpoint', 'wet_flow_setpoint',
            'hygrometer_temp', 'dewpoint_temp',
            'rh_hygrometer', 'rh_chiller',
            'chiller_temp', 'chiller_setpoint',
        ]

        self.rh_control_active = False
        self.rh_setpoint = 50.0
        self.rh_control_total_flow = 2.0
        self.rh_params = self._build_rh_params()
        self.pid_state = {'integral': 0.0, 'last_time': time.time(), 'last_adjustment_time': 0.0}

    def _build_rh_params(self) -> dict:
        return {
            'Kp':                    self.config.get('rh_kp', 0.02),
            'Ki':                    self.config.get('rh_ki', 0.001),
            'Kd':                    self.config.get('rh_kd', 0.0),
            'derivative_filter_tau': self.config.get('rh_derivative_filter_tau', 30.0),
            'integral_limit':        self.config.get('rh_integral_limit', 0.5),
            'settling_time':         self.config.get('rh_settling_time', 180.0),
            'settling_time_min':     self.config.get('rh_settling_time_min', 5.0),
            'max_flow':              self.config.get('max_flow', 2.0),
            'deadband':              self.config.get('rh_deadband', 1.0),
            'max_step':              self.config.get('rh_max_step', 0.05),
        }

    # ── Connection ───────────────────────────────────────────────────────────

    def connect_devices(self) -> Dict[str, bool]:
        cfg = self.config
        results: Dict[str, bool] = {}

        if cfg.get('dry_mfc_enabled') and 'dry_mfc_port' in cfg:
            self.dry_mfc = VogtlinMFC(
                port=cfg['dry_mfc_port'],
                address=cfg.get('dry_mfc_address', 1),
                name="Dry Air MFC",
            )
            results['dry_mfc'] = self._connect_device(self.dry_mfc, "dry MFC")

        if cfg.get('wet_mfc_enabled') and 'wet_mfc_port' in cfg:
            self.wet_mfc = VogtlinMFC(
                port=cfg['wet_mfc_port'],
                address=cfg.get('wet_mfc_address', 2),
                name="Wet Air MFC",
            )
            results['wet_mfc'] = self._connect_device(self.wet_mfc, "wet MFC")

        if cfg.get('hygrometer_enabled') and 'hygrometer_port' in cfg:
            self.hygrometer = Hygrometer(
                port=cfg['hygrometer_port'],
                baudrate=cfg.get('hygrometer_baudrate', 9600),
            )
            results['hygrometer'] = self._connect_device(self.hygrometer, "hygrometer")

        if cfg.get('chiller_enabled') and 'chiller_port' in cfg:
            self.chiller = JulaboChiller(
                port=cfg['chiller_port'],
                baudrate=cfg.get('chiller_baudrate', 9600),
            )
            results['chiller'] = self._connect_device(self.chiller, "chiller")

        self.connected = any(results.values()) if results else False
        print(f"Controller connected: {self.connected} (Details: {results})")
        return results

    def disconnect_devices(self):
        print("Disconnecting devices...")
        for device in [self.dry_mfc, self.wet_mfc, self.hygrometer, self.chiller]:
            if device:
                device.disconnect()
        self.running = False
        self.connected = False

    def is_connected(self) -> bool:
        return self.connected

    def _connect_device(self, device, name: str) -> bool:
        try:
            return bool(device.connect())
        except Exception as e:
            print(f"Error connecting {name}: {e}")
            return device.is_connected()

    # ── Sensor Reading ───────────────────────────────────────────────────────

    def read_all_sensors(self) -> Dict:
        data = {
            'timestamp': datetime.now().isoformat(),
            'dry_flow': None, 'wet_flow': None,
            'dry_flow_setpoint': None, 'wet_flow_setpoint': None,
            'hygrometer_temp': None, 'dewpoint_temp': None,
            'rh_hygrometer': None, 'rh_chiller': None,
            'chiller_temp': None, 'chiller_setpoint': None,
        }

        if self.dry_mfc:
            try:
                data['dry_flow'] = self.dry_mfc.get_flow()
                data['dry_flow_setpoint'] = self.dry_mfc.get_setpoint()
            except Exception as e:
                print(f"Error reading dry MFC: {e}")

        if self.wet_mfc:
            try:
                data['wet_flow'] = self.wet_mfc.get_flow()
                data['wet_flow_setpoint'] = self.wet_mfc.get_setpoint()
            except Exception as e:
                print(f"Error reading wet MFC: {e}")

        if self.hygrometer:
            try:
                readings = self.hygrometer.get_readings()
                if readings:
                    ht = readings.get('hygrometer_temp')
                    data['hygrometer_temp'] = ht if ht is not None else readings.get('ambient_temp')
                    data['dewpoint_temp'] = readings.get('dewpoint_temp')
            except Exception as e:
                print(f"Error reading hygrometer: {e}")

        if self.chiller:
            try:
                data['chiller_temp'] = self.chiller.get_external_temperature()
                data['chiller_setpoint'] = self.chiller.get_setpoint_temperature()
            except Exception as e:
                print(f"Error reading chiller: {e}")

        if self.hygrometer and data['dewpoint_temp'] is not None:
            dp = data['dewpoint_temp']
            if data['hygrometer_temp'] is not None:
                data['rh_hygrometer'] = self._compute_rh(dp, data['hygrometer_temp'])
            if data['chiller_temp'] is not None:
                data['rh_chiller'] = self._compute_rh(dp, data['chiller_temp'])

        return data

    def read_and_log(self, on_data: Optional[Callable[[Dict], None]] = None) -> Dict:
        try:
            data = self.read_all_sensors()
        except Exception as e:
            print(f"Error reading sensors: {e}")
            data = {}

        if self.logger.is_logging():
            try:
                self.logger.log_data(data)
            except Exception as e:
                print(f"Logger error: {e}")

        if on_data:
            try:
                on_data(data)
            except Exception as e:
                print(f"Callback error: {e}")
        return data

    def wait_and_log(self, duration: float, on_data: Optional[Callable[[Dict], None]] = None,
                     interval: float = 1.0):
        start = time.time()
        while (time.time() - start) < duration and self.running:
            cycle_start = time.time()
            self.read_and_log(on_data)
            elapsed = time.time() - cycle_start
            if elapsed < interval:
                time.sleep(interval - elapsed)

    def _compute_rh(self, dewpoint: float, temp: float) -> Optional[float]:
        try:
            val = self.hygrometer.compute_relative_humidity(dp=dewpoint, t=temp)
            return val if (val is not None and math.isfinite(val)) else None
        except Exception as e:
            print(f"Error computing RH (dp={dewpoint:.1f}, t={temp:.1f}): {e}")
            return None

    # ── Flow Control ─────────────────────────────────────────────────────────

    def set_flow_rates(self, dry_flow: Optional[float] = None, wet_flow: Optional[float] = None,
                       max_flow: Optional[float] = None, ramp_flow: bool = True) -> bool:
        if max_flow is not None:
            total = (dry_flow or 0.0) + (wet_flow or 0.0)
            if total > max_flow:
                print(f"Requested total flow {total:.2f} exceeds maximum {max_flow:.2f}. Aborting.")
                return False

        if ramp_flow:
            self._ramp_flows(dry_flow, wet_flow)

        success = True
        for mfc, flow in [(self.dry_mfc, dry_flow), (self.wet_mfc, wet_flow)]:
            if mfc is None or flow is None:
                continue
            try:
                if mfc.set_flow(flow):
                    print(f"{mfc.name} setpoint set to {flow:.3f}")
                else:
                    print(f"Failed to set {mfc.name} flow")
                    success = False
            except Exception as e:
                print(f"Error setting {mfc.name}: {e}")
                success = False
        return success

    def set_chiller_temperature(self, temperature: float):
        if not self.chiller:
            print("Chiller not connected")
            return
        self.chiller.set_setpoint_temperature(temperature)
        self.chiller.start_control()
        print(f"Chiller setpoint set to {temperature:.2f} °C")

    def _ramp_flows(self, dry_flow: Optional[float], wet_flow: Optional[float]):
        current_dry = self.dry_mfc.get_setpoint() if self.dry_mfc else 0.0
        current_wet = self.wet_mfc.get_setpoint() if self.wet_mfc else 0.0

        dry_diff = (dry_flow - current_dry) if (dry_flow is not None and self.dry_mfc) else 0.0
        wet_diff = (wet_flow - current_wet) if (wet_flow is not None and self.wet_mfc) else 0.0

        max_delta = max(abs(dry_diff), abs(wet_diff))
        step_size = 0.05  # L/min
        if max_delta <= step_size:
            return

        steps = min(int(max_delta / step_size), 100)
        print(f"Ramping flows over {steps} steps...")
        for i in range(1, steps + 1):
            frac = i / steps
            try:
                if dry_flow is not None and self.dry_mfc:
                    self.dry_mfc.set_flow(current_dry + dry_diff * frac)
                if wet_flow is not None and self.wet_mfc:
                    self.wet_mfc.set_flow(current_wet + wet_diff * frac)
            except Exception as e:
                print(f"Error during flow ramp step {i}: {e}")
            time.sleep(1)

    # ── RH Control (PI) ──────────────────────────────────────────────────────

    def set_rh_control_active(self, active: bool, target: Optional[float] = None,
                               total_flow: Optional[float] = None):
        if not active:
            self.rh_control_active = False
            print("RH Control Deactivated")
            return

        if target is not None:
            self.rh_setpoint = target
        if total_flow is not None:
            self.rh_control_total_flow = total_flow
        self.rh_params = self._build_rh_params()
        self.rh_control_active = True
        # last_adjustment_time=0.0 so the first correction fires immediately
        self.pid_state = {'integral': 0.0, 'last_time': time.time(), 'last_adjustment_time': 0.0}
        print(f"RH Control Activated: Target={self.rh_setpoint}%, Flow={self.rh_control_total_flow} L/min, "
              f"settling {self.rh_params['settling_time_min']:.0f}–{self.rh_params['settling_time']:.0f}s "
              f"(dynamic), deadband=±{self.rh_params['deadband']}%")

    def update_rh_control_loop(self, current_rh: Optional[float]):
        if not self.rh_control_active or current_rh is None:
            return

        new_wet_ratio = self._compute_wet_ratio_pid(self.rh_setpoint, current_rh, self.pid_state)
        if new_wet_ratio is None:
            return

        total = self.rh_control_total_flow
        success = self.set_flow_rates(
            dry_flow=(1.0 - new_wet_ratio) * total,
            wet_flow=new_wet_ratio * total,
            max_flow=total * 1.1,
            ramp_flow=False,
        )
        if success:
            self.pid_state['last_adjustment_time'] = time.time()

    def get_rh_control_status(self, current_rh: Optional[float] = None) -> str:
        """Return a human-readable status string for the RH control loop.

        Includes the RH value the controller is currently acting on so the user
        can spot a mismatch between the displayed reading and the control reading
        (e.g. rh_chiller vs rh_hygrometer giving different values).
        """
        if not self.rh_control_active:
            return "Inactive"
        now = time.time()
        dyn_settling = self.pid_state.get('dynamic_settling_time', self.rh_params['settling_time'])
        remaining = dyn_settling - (now - self.pid_state.get('last_adjustment_time', 0.0))
        rh_str = f"{current_rh:.1f}%" if current_rh is not None else "N/A"
        if remaining > 0:
            return f"Settling ({remaining:.0f}s) | {rh_str}"
        if current_rh is not None:
            error = self.rh_setpoint - current_rh
            if abs(error) < self.rh_params['deadband']:
                return f"At target | {rh_str}"
            return f"Adjusting (err={error:+.1f}%) | {rh_str}"
        return f"Active | {rh_str}"

    def _compute_wet_ratio_pid(self, target_rh: float, current_rh: float,
                                pid_state: Dict) -> Optional[float]:
        """Run one PID step; returns the new wet flow ratio, or None if no update needed.

        Three guards enforce patience appropriate for this slow physical system:
          - settling_time: minimum seconds between flow adjustments so the gas mixture
            in the tubing and the dew-point mirror have time to equilibrate.
          - deadband: ignore errors smaller than this (±%) to avoid chasing sensor noise.
          - max_step: clamp the wet-ratio change per adjustment to prevent large jumps.

        D term implementation notes:
          - "D on measurement" (not on error): avoids a derivative spike when the
            setpoint changes between experiment steps.
          - Measurement tracking updates every call (including during settling) so the
            filtered derivative is fresh when the PI is finally allowed to fire.
          - First-order low-pass filter with time constant `derivative_filter_tau`
            attenuates high-frequency noise from the dew-point mirror.
          - Set Kd = 0 to disable the D term entirely (backward-compatible default).
        """
        now = time.time()

        # --- D on measurement: update derivative tracking every call ─────────
        # Using a separate measurement-time clock so the derivative reflects the
        # true polling interval rather than the (stretched) PI interval.
        kd = self.rh_params['Kd']
        dt_meas = now - pid_state.get('last_meas_time', now)
        if kd > 0.0 and dt_meas > 0.5:
            d_raw = (current_rh - pid_state.get('prev_rh', current_rh)) / dt_meas
            tau_d = max(self.rh_params['derivative_filter_tau'], 1.0)
            alpha = dt_meas / (tau_d + dt_meas)           # first-order low-pass
            pid_state['filtered_d'] = (
                (1.0 - alpha) * pid_state.get('filtered_d', 0.0) + alpha * d_raw
            )
        pid_state['prev_rh'] = current_rh
        pid_state['last_meas_time'] = now

        # --- Settling guard: wait after each flow change ─────────────────────
        # Use the dynamic settling time stored when the last adjustment was made.
        # On the very first call (last_adjustment_time=0) the guard never fires.
        settling_time = pid_state.get('dynamic_settling_time', self.rh_params['settling_time'])
        remaining = settling_time - (now - pid_state.get('last_adjustment_time', 0.0))
        if remaining > 0:
            pid_state['last_time'] = now   # prevent dt from ballooning
            return None

        dt = now - pid_state['last_time']
        if dt < 1.0:
            return None

        error = target_rh - current_rh

        # --- Deadband: ignore small errors ───────────────────────────────────
        if abs(error) < self.rh_params['deadband']:
            pid_state['last_time'] = now
            pid_state['integral'] = 0.0   # bleed integral while on target
            return None

        # --- P term ──────────────────────────────────────────────────────────
        p_term = self.rh_params['Kp'] * error

        # --- I term ──────────────────────────────────────────────────────────
        ki = self.rh_params['Ki']
        pid_state['integral'] += error * dt
        limit = self.rh_params['integral_limit'] / ki if ki > 0 else 0.0
        pid_state['integral'] = max(-limit, min(limit, pid_state['integral']))
        i_term = ki * pid_state['integral']

        # --- D term (filtered, D on measurement) ─────────────────────────────
        # Negative sign: when measurement rises toward the setpoint, d_filtered > 0,
        # so d_term < 0 — this damps the approach and reduces overshoot.
        d_term = -kd * pid_state.get('filtered_d', 0.0) if kd > 0.0 else 0.0

        output_change = p_term + i_term + d_term

        # --- Dynamic step clamp (Newton-like convergence) ─────────────────────
        # The allowed wet-ratio change scales linearly with |error|, so the
        # controller takes large strides when far from the setpoint and
        # automatically feathers down to very small adjustments as it converges.
        # rh_max_step is the ceiling when |error| = 100 %; it shrinks to near
        # zero as the measurement approaches the target.
        dynamic_max_step = self.rh_params['max_step'] * (abs(error) / 100.0)
        output_change = max(-dynamic_max_step, min(dynamic_max_step, output_change))

        pid_state['last_time'] = now

        if abs(output_change) <= 0.0001:
            return None

        curr_dry_sp = self.dry_mfc.get_setpoint() if self.dry_mfc else 0.0
        curr_wet_sp = self.wet_mfc.get_setpoint() if self.wet_mfc else 0.0
        total_sp = curr_dry_sp + curr_wet_sp

        if total_sp <= 0.01:
            new_wet_ratio = max(0.0, min(1.0, target_rh / 100.0))
        else:
            new_wet_ratio = max(0.0, min(1.0, curr_wet_sp / total_sp + output_change))

        # --- Dynamic settling time ───────────────────────────────────────────
        # Scale the next settling wait proportionally to the size of this flow
        # change: full-scale step (0 → max_flow on each MFC) → settling_time,
        # near-zero step → settling_time_min.
        new_dry_sp = (1.0 - new_wet_ratio) * self.rh_control_total_flow
        new_wet_sp = new_wet_ratio * self.rh_control_total_flow
        delta = abs(new_dry_sp - curr_dry_sp) + abs(new_wet_sp - curr_wet_sp)
        ref = max(0.01, self.rh_params['max_flow'])   # reference = max_flow from config
        t_min = self.rh_params['settling_time_min']
        t_max = self.rh_params['settling_time']
        pid_state['dynamic_settling_time'] = t_min + (t_max - t_min) * min(1.0, delta / ref)

        return new_wet_ratio

    # ── Experiment ───────────────────────────────────────────────────────────

    def run_automated_experiment(self, direction: str, step_size: float, max_flow: float,
                                 control_interval: float, hold_time: float = 180.0,
                                 on_data: Optional[Callable[[Dict], None]] = None) -> Optional[str]:
        """Flow-stepping experiment.

        Steps the wet-to-dry ratio from 0→100 % (up) or 100→0 % (down) in
        increments of *step_size* percent of total flow.  At each step the flows
        are set immediately, then the system is left to equilibrate for
        *hold_time* seconds while sensor data is collected.  No PI control is
        used; the RH reading is informational only.

        Always saves a CSV named "RH_ramp_{timestamp}.csv" in the log directory.
        Returns the path of the saved post-experiment plot, or None on failure.
        """
        self.running = True
        step_times: list = []

        self.logger.start_new_log(self.log_fields, prefix="RH_ramp")
        csv_path = self.logger.get_current_filename()

        try:
            # Build the ordered wet-flow ratio sequence (0.0 … 1.0)
            n_steps = int(round(100.0 / step_size))
            if direction.lower() == "up":
                ratios = [min(1.0, i * step_size / 100.0) for i in range(n_steps + 1)]
                if abs(ratios[-1] - 1.0) > 0.001:
                    ratios.append(1.0)
            else:
                ratios = [max(0.0, 1.0 - i * step_size / 100.0) for i in range(n_steps + 1)]
                if abs(ratios[-1]) > 0.001:
                    ratios.append(0.0)

            print(f"Experiment: direction={direction}, {len(ratios)} steps of "
                  f"{step_size:.1f}% wet flow, hold {hold_time:.0f}s per step, "
                  f"total flow {max_flow:.2f} L/min")

            for step_idx, wet_ratio in enumerate(ratios):
                if not self.running:
                    break

                dry_flow = max_flow * (1.0 - wet_ratio)
                wet_flow = max_flow * wet_ratio
                print(f"\n── Step {step_idx + 1}/{len(ratios)}: "
                      f"wet={wet_ratio * 100:.0f}%  "
                      f"(dry={dry_flow:.3f} L/min, wet={wet_flow:.3f} L/min) ──")

                self.set_flow_rates(dry_flow=dry_flow, wet_flow=wet_flow,
                                    max_flow=max_flow, ramp_flow=False)
                step_times.append(datetime.now())

                # Wait hold_time seconds, polling at control_interval
                elapsed = 0.0
                while elapsed < hold_time and self.running:
                    cycle_start = time.time()
                    data = self.read_all_sensors()
                    if self.logger.is_logging():
                        try:
                            self.logger.log_data(data)
                        except Exception as e:
                            print(f"Logger error: {e}")
                    if on_data:
                        try:
                            on_data(data)
                        except Exception:
                            pass
                    elapsed += control_interval
                    sleep_time = control_interval - (time.time() - cycle_start)
                    if sleep_time > 0:
                        time.sleep(sleep_time)

        finally:
            self.running = False
            self.logger.close()

            plot_path = None
            try:
                plot_path = self._save_experiment_plot(csv_path, step_times)
            except Exception as e:
                print(f"Failed to save experiment plot: {e}")
            print("Experiment finished.")

        return plot_path

    def _save_experiment_plot(self, csv_path: Optional[str], step_times: list) -> Optional[str]:
        """Generate a 3-subplot figure from the experiment CSV and save it as PNG.

        Each channel is drawn twice: raw data at low opacity (alpha=0.25) to
        preserve the underlying noise, and a moving-average smoothed signal at
        full opacity on top to make the trend clearly visible.
        """
        import numpy as np
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        import matplotlib.dates as mdates

        if not csv_path:
            return None

        rows = self.logger.read_log(csv_path)
        if not rows:
            return None

        # Parse CSV rows (all values arrive as strings from DictReader)
        def _to_float(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        timestamps, dry_flows, wet_flows = [], [], []
        hyg_temps, chill_temps = [], []
        rh_hyg, rh_chill = [], []

        for row in rows:
            try:
                t = datetime.fromisoformat(row['timestamp'])
            except (KeyError, ValueError, TypeError):
                continue
            timestamps.append(t)
            dry_flows.append(_to_float(row.get('dry_flow')))
            wet_flows.append(_to_float(row.get('wet_flow')))
            hyg_temps.append(_to_float(row.get('hygrometer_temp')))
            chill_temps.append(_to_float(row.get('chiller_temp')))
            rh_hyg.append(_to_float(row.get('rh_hygrometer')))
            rh_chill.append(_to_float(row.get('rh_chiller')))

        if not timestamps:
            return None

        # Auto-scale smoothing window: roughly 1/30th of total points, min 5
        window = max(5, len(timestamps) // 30)

        def _smooth(values):
            """Moving-average via convolution; 'same' preserves array length."""
            arr = np.array(values, dtype=float)
            kernel = np.ones(window) / window
            return np.convolve(arr, kernel, mode='same')

        def _plot_series_with_smooth(ax, ts_list, vals, label, color):
            """Plot raw (transparent) then smoothed (opaque) for one channel."""
            pairs = [(t, v) for t, v in zip(ts_list, vals) if v is not None]
            if not pairs:
                return
            ts, vs = zip(*pairs)
            vs_arr = list(vs)
            # Raw data — semi-transparent thin line
            ax.plot(ts, vs_arr, color=color, linewidth=0.8, alpha=0.25)
            # Smoothed overlay — full opacity
            smoothed = _smooth(vs_arr)
            ax.plot(ts, smoothed, label=label, color=color, linewidth=1.8, alpha=1.0)

        fig = Figure(figsize=(12, 8))
        FigureCanvasAgg(fig)
        ax0 = fig.add_subplot(3, 1, 1)
        ax1 = fig.add_subplot(3, 1, 2, sharex=ax0)
        ax2 = fig.add_subplot(3, 1, 3, sharex=ax0)

        fig.suptitle(f"RH Ramp Experiment — {timestamps[0].strftime('%Y-%m-%d %H:%M')}")

        # Step-change markers on all axes
        for ax in (ax0, ax1, ax2):
            for st in step_times:
                ax.axvline(st, color='gray', linestyle='--', linewidth=0.7, alpha=0.6)

        _plot_series_with_smooth(ax0, timestamps, dry_flows, 'Dry flow', 'steelblue')
        _plot_series_with_smooth(ax0, timestamps, wet_flows, 'Wet flow', 'darkorange')
        ax0.set_ylabel('Flow rate (L/min)')
        ax0.legend(loc='upper right', fontsize=8)
        ax0.grid(True, alpha=0.3)

        _plot_series_with_smooth(ax1, timestamps, hyg_temps, 'Hygrometer temp', 'darkorange')
        _plot_series_with_smooth(ax1, timestamps, chill_temps, 'Chiller temp', 'firebrick')
        ax1.set_ylabel('Temperature (°C)')
        ax1.legend(loc='upper right', fontsize=8)
        ax1.grid(True, alpha=0.3)

        _plot_series_with_smooth(ax2, timestamps, rh_hyg, 'RH (hygrometer)', 'mediumpurple')
        _plot_series_with_smooth(ax2, timestamps, rh_chill, 'RH (chiller)', 'royalblue')
        ax2.set_ylabel('Relative humidity (%)')
        ax2.set_xlabel('Time')
        ax2.legend(loc='upper right', fontsize=8)
        ax2.grid(True, alpha=0.3)

        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        fig.autofmt_xdate()
        fig.tight_layout()

        # Save PNG alongside the CSV (same stem, different extension)
        plot_path = Path(csv_path).with_suffix('.png')
        fig.savefig(str(plot_path), dpi=150, bbox_inches='tight')
        print(f"Experiment plot saved: {plot_path}")
        return str(plot_path)

    # ── Settings ─────────────────────────────────────────────────────────────

    def update_settings(self, new_config: Dict):
        self.config.update(new_config)
        self.logger.output_dir = Path(self.config.get('log_dir', 'data'))
        self.logger.filename_prefix = self.config.get('log_prefix', 'nsim_log')
        self.logger.output_dir.mkdir(parents=True, exist_ok=True)
        self.rh_params = self._build_rh_params()
