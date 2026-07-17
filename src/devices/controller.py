import time
from datetime import datetime
from typing import Callable, Dict, Optional

from src.devices.chiller import JulaboChiller
from src.devices.firesting import FireStingO2
from src.devices.hygrometer import Hygrometer
from src.devices.pid_controller import RhPidController
from src.devices.vogtlin_mfc import VogtlinMFC
from src.utility.data_logger import DataLogger
from src.utility.plot_saver import save_experiment_plot
from src.utility.compute_RH import compute_relative_humidity, calibrated_RH


class Controller:
    def __init__(self, config: Dict):
        self.config = config
        self.running = False
        self.connected = False

        self.dry_mfc: Optional[VogtlinMFC] = None
        self.wet_mfc: Optional[VogtlinMFC] = None
        self.hygrometer: Optional[Hygrometer] = None
        self.chiller: Optional[JulaboChiller] = None
        self.firesting: Optional[FireStingO2] = None

        self.logger = DataLogger(
            output_dir=self.config.get("log_dir", "data"),
            filename_prefix=self.config.get("log_prefix", "nsim_log"),
        )

        self.log_fields = [
            "timestamp",
            "dry_flow",
            "wet_flow",
            "dry_flow_setpoint",
            "wet_flow_setpoint",
            "hygrometer_temp",
            "dewpoint_temp",
            "rh_hygrometer",
            "rh_chiller",
            "rh_chiller_calibrated",
            "chiller_temp",
            "chiller_setpoint",
            "oxygen",
        ]

        self.rh_control_active = False
        self.rh_setpoint = 50.0
        self.rh_control_total_flow = 2.0
        self.pid = RhPidController(config)

        # Live per-device health, updated every poll. True = last read succeeded.
        # A device that drops mid-run is flagged False and retried (throttled) so
        # it recovers automatically when powered back on / re-cabled.
        self.device_health: Dict[str, bool] = {}
        self._last_reconnect: Dict[str, float] = {}
        self.reconnect_interval = float(config.get("reconnect_interval", 5.0))

    # ── Connection ───────────────────────────────────────────────────────────

    def connect_devices(self) -> Dict[str, bool]:
        cfg = self.config
        results: Dict[str, bool] = {}

        # Start from a clean slate so a device that previously connected (or was
        # since disabled) never lingers as a stale reference across sessions.
        self.dry_mfc = self.wet_mfc = self.hygrometer = self.chiller = None
        self.firesting = None
        self.device_health = {}
        self._last_reconnect = {}

        # (attr key, log label, port config key, factory). Only the device class
        # and its constructor args vary between devices; everything else (the
        # enabled+port gate, connect, store, health) is identical, so drive it
        # from one loop.
        specs = [
            ("dry_mfc", "dry MFC", "dry_mfc_port", lambda: VogtlinMFC(
                port=cfg["dry_mfc_port"], address=cfg.get("dry_mfc_address", 1),
                baudrate=cfg.get("mfc_baudrate", 9600), name="Dry Air MFC")),
            ("wet_mfc", "wet MFC", "wet_mfc_port", lambda: VogtlinMFC(
                port=cfg["wet_mfc_port"], address=cfg.get("wet_mfc_address", 247),
                baudrate=cfg.get("mfc_baudrate", 9600), name="Wet Air MFC")),
            ("hygrometer", "hygrometer", "hygrometer_port", lambda: Hygrometer(
                port=cfg["hygrometer_port"],
                baudrate=cfg.get("hygrometer_baudrate", 19200))),
            ("chiller", "chiller", "chiller_port", lambda: JulaboChiller(
                port=cfg["chiller_port"],
                baudrate=cfg.get("chiller_baudrate", 9600))),
            ("firesting", "FireSting O2", "firesting_port", lambda: FireStingO2(
                port=cfg["firesting_port"],
                baudrate=cfg.get("firesting_baudrate", 19200))),
        ]
        for key, label, port_key, make in specs:
            if cfg.get(f"{key}_enabled") and port_key in cfg:
                dev = make()
                ok = self._connect_device(dev, label)
                results[key] = ok
                setattr(self, key, dev if ok else None)
                self.device_health[key] = ok

        self.connected = any(results.values()) if results else False
        print(f"Controller connected: {self.connected} (Details: {results})")
        return results

    def disconnect_devices(self):
        print("Disconnecting devices...")
        for device in [self.dry_mfc, self.wet_mfc, self.hygrometer, self.chiller, self.firesting]:
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

    def _should_read(self, key: str, device) -> bool:
        """Decide whether to read a device this tick.

        A healthy device is always read. A device flagged unhealthy (it dropped
        out earlier) is left alone except for a reconnect attempt at most once
        per ``reconnect_interval`` seconds — this is what lets a device recover
        automatically after being powered back on or re-cabled, without stalling
        the poll loop on every tick while it stays down.
        """
        if self.device_health.get(key, True):
            return True
        now = time.time()
        if now - self._last_reconnect.get(key, 0.0) < self.reconnect_interval:
            return False
        self._last_reconnect[key] = now
        try:
            if device.connect():
                self.device_health[key] = True
                print(f"{key} reconnected.")
                return True
        except Exception as e:
            print(f"{key} reconnect attempt failed: {e}")
        return False

    def read_all_sensors(self) -> Dict:
        data: Dict[str, Optional[float | str]] = {f: None for f in self.log_fields}
        data["timestamp"] = datetime.now().isoformat()

        if self.dry_mfc and self._should_read("dry_mfc", self.dry_mfc):
            try:
                data["dry_flow"] = self.dry_mfc.get_flow()
                data["dry_flow_setpoint"] = self.dry_mfc.get_setpoint()
                self.device_health["dry_mfc"] = True
            except Exception as e:
                print(f"Error reading dry MFC: {e}")
                self.device_health["dry_mfc"] = False

        if self.wet_mfc and self._should_read("wet_mfc", self.wet_mfc):
            try:
                data["wet_flow"] = self.wet_mfc.get_flow()
                data["wet_flow_setpoint"] = self.wet_mfc.get_setpoint()
                self.device_health["wet_mfc"] = True
            except Exception as e:
                print(f"Error reading wet MFC: {e}")
                self.device_health["wet_mfc"] = False

        if self.hygrometer and self._should_read("hygrometer", self.hygrometer):
            try:
                readings = self.hygrometer.get_readings()
                if readings:
                    data["hygrometer_temp"] = readings.get("hygrometer_temp")
                    data["dewpoint_temp"] = readings.get("dewpoint_temp")
                    self.device_health["hygrometer"] = True
                else:
                    # Port open but no reading — device powered off / unplugged.
                    self.device_health["hygrometer"] = False
            except Exception as e:
                print(f"Error reading hygrometer: {e}")
                self.device_health["hygrometer"] = False

        if self.chiller and self._should_read("chiller", self.chiller):
            try:
                data["chiller_temp"] = self.chiller.get_external_temperature()
                data["chiller_setpoint"] = self.chiller.get_setpoint_temperature()
                # Setpoint is always available on a live chiller (external probe
                # temp may legitimately be None), so use it as the liveness signal.
                self.device_health["chiller"] = data["chiller_setpoint"] is not None
            except Exception as e:
                print(f"Error reading chiller: {e}")
                self.device_health["chiller"] = False

        if self.firesting and self._should_read("firesting", self.firesting):
            try:
                readings = self.firesting.get_readings()
                if readings:
                    data["oxygen"] = readings.get("oxygen")
                    self.device_health["firesting"] = True
                else:
                    # Port open but no reading — device powered off / unplugged.
                    self.device_health["firesting"] = False
            except Exception as e:
                print(f"Error reading FireSting O2: {e}")
                self.device_health["firesting"] = False

        if data["dewpoint_temp"] is not None:
            dp = data["dewpoint_temp"]
            if data["hygrometer_temp"] is not None:
                data["rh_hygrometer"] = compute_relative_humidity(dp=dp, t=data["hygrometer_temp"])
            if data["chiller_temp"] is not None:
                data["rh_chiller"] = compute_relative_humidity(dp=dp, t=data["chiller_temp"])
                data["rh_chiller_calibrated"] = calibrated_RH(data["rh_chiller"])

        return data

    def read_and_log(self, on_data: Optional[Callable[[Dict], None]] = None) -> Dict:
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
        return data

    # ── Flow Control ─────────────────────────────────────────────────────────

    def set_flow_rates(
        self,
        dry_flow: Optional[float] = None,
        wet_flow: Optional[float] = None,
        max_flow: Optional[float] = None,
        ramp_flow: bool = True,
    ) -> bool:
        if max_flow is not None:
            total = (dry_flow or 0.0) + (wet_flow or 0.0)
            if total > max_flow:
                print(
                    f"Requested total flow {total:.2f} exceeds maximum {max_flow:.2f}. Aborting."
                )
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

    def get_current_flows(self) -> tuple:
        return (
            self.dry_mfc.get_setpoint() if self.dry_mfc else 0.0,
            self.wet_mfc.get_setpoint() if self.wet_mfc else 0.0,
        )

    def _ramp_flows(self, dry_flow: Optional[float], wet_flow: Optional[float]):
        current_dry, current_wet = self.get_current_flows()

        dry_diff = (
            (dry_flow - current_dry) if (dry_flow is not None and self.dry_mfc) else 0.0
        )
        wet_diff = (
            (wet_flow - current_wet) if (wet_flow is not None and self.wet_mfc) else 0.0
        )

        max_delta = max(abs(dry_diff), abs(wet_diff))
        step_size = self.config.get("flow_ramp_step", 0.25)  # L/min (coarse)
        step_delay = self.config.get("flow_ramp_delay", 0.3)  # s between steps
        if max_delta <= step_size:
            return

        # Coarse, fast ramp: a few big steps with a short settle between each,
        # just enough to avoid a hard setpoint jump. Capped so even a large
        # change finishes in a couple of seconds.
        steps = min(max(1, round(max_delta / step_size)), 20)
        print(f"Ramping flows over {steps} steps ({step_delay:.2f}s/step)...")
        for i in range(1, steps + 1):
            frac = i / steps
            try:
                if dry_flow is not None and self.dry_mfc:
                    self.dry_mfc.set_flow(current_dry + dry_diff * frac)
                if wet_flow is not None and self.wet_mfc:
                    self.wet_mfc.set_flow(current_wet + wet_diff * frac)
            except Exception as e:
                print(f"Error during flow ramp step {i}: {e}")
            time.sleep(step_delay)

    # ── RH Control (PID) ──────────────────────────────────────────────────────

    def set_rh_control_active(
        self,
        active: bool,
        target: Optional[float] = None,
        total_flow: Optional[float] = None,
    ):
        if not active:
            self.rh_control_active = False
            print("RH Control Deactivated")
            return

        if target is not None:
            self.rh_setpoint = target
        if total_flow is not None:
            self.rh_control_total_flow = total_flow
        self.pid.update_params(self.config)
        self.pid.reset()
        self.rh_control_active = True
        p = self.pid.params
        print(
            f"RH Control Activated: Target={self.rh_setpoint}%, Flow={self.rh_control_total_flow} L/min, "
            f"settling {p['settling_time_min']:.0f}–{p['settling_time']:.0f}s "
            f"(dynamic), deadband=±{p['deadband']}%"
        )

    def update_rh_control_loop(self, current_rh: Optional[float]):
        if not self.rh_control_active or current_rh is None:
            return

        curr_dry, curr_wet = self.get_current_flows()
        new_wet_ratio = self.pid.compute(
            self.rh_setpoint, current_rh, curr_dry, curr_wet, self.rh_control_total_flow
        )
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
            self.pid.state.last_adjustment_time = time.time()

    def get_rh_control_status(self, current_rh: Optional[float] = None) -> str:
        if not self.rh_control_active:
            return "Inactive"
        return self.pid.get_status(self.rh_setpoint, current_rh)

    # ── Experiment ───────────────────────────────────────────────────────────

    @staticmethod
    def _report(msg: str, on_progress: Optional[Callable[[str], None]] = None):
        print(msg)
        if on_progress:
            try:
                on_progress(msg)
            except Exception:
                pass

    def _hold_and_log(
        self,
        hold_time: float,
        control_interval: float,
        on_data: Optional[Callable[[Dict], None]] = None,
    ):
        """Read/log sensors every control_interval for hold_time seconds (or until stopped)."""
        elapsed = 0.0
        while elapsed < hold_time and self.running:
            cycle_start = time.time()
            self.read_and_log(on_data)
            elapsed += control_interval
            sleep_time = control_interval - (time.time() - cycle_start)
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _stabilize_to_rh(
        self,
        target_rh: float,
        pid: RhPidController,
        max_flow: float,
        stability_readings: int,
        stability_timeout: float,
        control_interval: float,
        dry_only: bool = False,
        on_data: Optional[Callable[[Dict], None]] = None,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """PID-drive flows toward target_rh until stable or timed out.

        Returns True if stability_readings consecutive within-deadband readings
        were achieved; False if stability_timeout elapsed first.
        """
        stable_count = 0
        phase_start = time.time()
        deadband = self.pid.params["deadband"]

        while self.running:
            if time.time() - phase_start > stability_timeout:
                self._report(
                    f"Stabilisation toward {target_rh:.1f}% timed out after "
                    f"{stability_timeout:.0f}s — proceeding anyway.",
                    on_progress,
                )
                return False

            cycle_start = time.time()
            data = self.read_and_log(on_data)
            current_rh: Optional[float] = (
                data.get("rh_chiller")
                if data.get("rh_chiller") is not None
                else data.get("rh_hygrometer")
            )

            if current_rh is not None:
                if not dry_only:
                    curr_dry, curr_wet = self.get_current_flows()
                    new_wet_ratio = pid.compute(
                        target_rh, current_rh, curr_dry, curr_wet, max_flow
                    )
                    if new_wet_ratio is not None:
                        self.set_flow_rates(
                            dry_flow=(1.0 - new_wet_ratio) * max_flow,
                            wet_flow=new_wet_ratio * max_flow,
                            max_flow=max_flow,
                            ramp_flow=False,
                        )
                        pid.state.last_adjustment_time = time.time()

                is_stable = (
                    current_rh < deadband
                    if dry_only
                    else abs(current_rh - target_rh) < deadband
                )
                stable_count = stable_count + 1 if is_stable else 0

                self._report(
                    f"Stabilising → {target_rh:.1f}% | "
                    f"current {current_rh:.1f}% "
                    f"({stable_count}/{stability_readings} stable)",
                    on_progress,
                )

                if stable_count >= stability_readings:
                    print(f"Stable at {current_rh:.1f}% RH.")
                    return True

            time.sleep(max(10.0, control_interval - (time.time() - cycle_start)))

        return False

    def run_automated_experiment(
        self,
        mode: str = "flow",
        # Flow mode params
        flow_start: float = 0.0,
        flow_end: float = 2.0,
        flow_step: float = 0.1,
        # RH mode params
        rh_start: float = 0.0,
        rh_end: float = 90.0,
        rh_step: float = 5.0,
        # Shared params
        max_flow: float = 2.0,
        control_interval: float = 5.0,
        hold_time: float = 180.0,
        stability_readings: int = 5,
        stability_timeout: float = 800.0,
        on_data: Optional[Callable[[Dict], None]] = None,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> Optional[str]:
        self.running = True
        step_times: list = []

        self.logger.start_new_log(self.log_fields, prefix="RH_ramp")
        csv_path = self.logger.get_current_filename()

        try:
            time.sleep(1)

            # ── Phase 1: Pre-conditioning ─────────────────────────────────────
            self._precondition(
                mode=mode,
                flow_start=flow_start,
                rh_start=rh_start,
                rh_end=rh_end,
                max_flow=max_flow,
                control_interval=control_interval,
                stability_readings=stability_readings,
                stability_timeout=stability_timeout,
                on_data=on_data,
                on_progress=on_progress,
            )

            if not self.running:
                return None

            # ── Phase 2: Ramp ─────────────────────────────────────────────────
            if mode == "flow":
                self._run_flow_ramp(
                    flow_start=flow_start,
                    flow_end=flow_end,
                    flow_step=flow_step,
                    max_flow=max_flow,
                    control_interval=control_interval,
                    hold_time=hold_time,
                    step_times=step_times,
                    on_data=on_data,
                    on_progress=on_progress,
                )
            else:  # mode == "rh"
                self._run_rh_ramp(
                    rh_start=rh_start,
                    rh_end=rh_end,
                    rh_step=rh_step,
                    max_flow=max_flow,
                    control_interval=control_interval,
                    hold_time=hold_time,
                    stability_readings=stability_readings,
                    stability_timeout=stability_timeout,
                    step_times=step_times,
                    on_data=on_data,
                    on_progress=on_progress,
                )

        finally:
            self.running = False
            self.logger.close()

            plot_path = None
            try:
                plot_path = save_experiment_plot(csv_path, step_times, self.logger)
            except Exception as e:
                print(f"Failed to save experiment plot: {e}")
            print("Experiment finished.")

        return plot_path

    def _precondition(
        self,
        mode: str,
        flow_start: float,
        rh_start: float,
        rh_end: float,
        max_flow: float,
        control_interval: float,
        stability_readings: int,
        stability_timeout: float,
        on_data: Optional[Callable[[Dict], None]] = None,
        on_progress: Optional[Callable[[str], None]] = None,
    ):
        """Phase 1: drive the chamber to the ramp's starting condition."""
        if mode == "flow":
            # Open-loop: just set the starting wet flow and let it settle.
            if flow_start <= 0.0:
                # Dry-only flush — use PI stability check to confirm low RH
                self.set_flow_rates(
                    dry_flow=max_flow, wet_flow=0.0, max_flow=max_flow, ramp_flow=False
                )
                print(
                    f"\n── Pre-conditioning (flow mode): dry-only flush "
                    f"(timeout {stability_timeout:.0f}s) ──"
                )
                precondpid = RhPidController(self.config)
                self._stabilize_to_rh(
                    target_rh=0.0,
                    pid=precondpid,
                    max_flow=max_flow,
                    stability_readings=stability_readings,
                    stability_timeout=stability_timeout,
                    control_interval=control_interval,
                    dry_only=True,
                    on_data=on_data,
                    on_progress=on_progress,
                )
            else:
                # Non-zero start: set flows directly, brief 60 s soak
                self.set_flow_rates(
                    dry_flow=max(0.0, max_flow - flow_start),
                    wet_flow=flow_start,
                    max_flow=max_flow,
                    ramp_flow=False,
                )
                print(
                    f"\n── Pre-conditioning (flow mode): set wet={flow_start:.3f} L/min, "
                    f"soaking 60 s ──"
                )
                soak_end = time.time() + 60.0
                while self.running and time.time() < soak_end:
                    cycle_start = time.time()
                    self.read_and_log(on_data)
                    time.sleep(max(0.0, control_interval - (time.time() - cycle_start)))
            return

        # mode == "rh"
        going_up = rh_end >= rh_start
        precond_target = rh_start if going_up else rh_end
        dry_only_precond = going_up and precond_target == 0.0

        deadband = self.pid.params["deadband"]
        precondpid = RhPidController(self.config)

        if dry_only_precond:
            self.set_flow_rates(
                dry_flow=max_flow, wet_flow=0.0, max_flow=max_flow, ramp_flow=False
            )
            print(
                f"\n── Pre-conditioning (RH mode): 0% RH (dry-only flush, "
                f"stable when {stability_readings} consecutive readings "
                f"< {deadband:.1f}%, timeout {stability_timeout:.0f}s) ──"
            )
        else:
            print(
                f"\n── Pre-conditioning (RH mode): targeting {precond_target:.1f}% RH "
                f"(stable when {stability_readings} consecutive readings "
                f"within ±{deadband:.1f}%, timeout {stability_timeout:.0f}s) ──"
            )
            initial_wet_ratio = precond_target / 100.0
            curr_dry, curr_wet = self.get_current_flows()
            new_dry = (1.0 - initial_wet_ratio) * max_flow
            new_wet = initial_wet_ratio * max_flow
            self.set_flow_rates(
                dry_flow=new_dry, wet_flow=new_wet, max_flow=max_flow, ramp_flow=False
            )
            # Inflate settling timer to absorb the 120 s initial soak
            delta = abs(new_dry - curr_dry) + abs(new_wet - curr_wet)
            t_min = precondpid.params["settling_time_min"]
            t_max = precondpid.params["settling_time"]
            precondpid.state.dynamic_settling_time = (
                120 + t_min + (t_max - t_min) * min(1.0, delta / max(0.01, max_flow))
            )
            precondpid.state.last_adjustment_time = time.time()

        self._stabilize_to_rh(
            target_rh=precond_target,
            pid=precondpid,
            max_flow=max_flow,
            stability_readings=stability_readings,
            stability_timeout=stability_timeout,
            control_interval=control_interval,
            dry_only=dry_only_precond,
            on_data=on_data,
            on_progress=on_progress,
        )

    @staticmethod
    def _build_ramp_targets(
        start: float, end: float, step: float,
        lower: float, upper: float, tol: float,
    ) -> list:
        """Inclusive list of clamped setpoints stepping start→end.

        Walks from ``start`` toward ``end`` in ``step`` increments (in either
        direction), clamping each value to ``[lower, upper]``. If the last
        generated value misses ``end`` by more than ``tol``, ``end`` is appended
        so the ramp always finishes on its endpoint.
        """
        direction = 1 if end >= start else -1
        n_steps = int(round(abs(end - start) / max(1e-6, step))) + 1
        targets = [
            round(max(lower, min(upper, start + direction * i * step)), 6)
            for i in range(n_steps)
        ]
        if abs(targets[-1] - end) > tol:
            targets.append(round(max(lower, min(upper, end)), 6))
        return targets

    def _run_flow_ramp(
        self,
        flow_start: float,
        flow_end: float,
        flow_step: float,
        max_flow: float,
        control_interval: float,
        hold_time: float,
        step_times: list,
        on_data: Optional[Callable[[Dict], None]] = None,
        on_progress: Optional[Callable[[str], None]] = None,
    ):
        """Phase 2 (flow mode): open-loop step the wet flow and hold at each step."""
        wet_flow_targets = self._build_ramp_targets(
            flow_start, flow_end, flow_step, 0.0, max_flow, 0.001
        )

        print(
            f"Flow ramp: {len(wet_flow_targets)} steps "
            f"({flow_start:.3f} → {flow_end:.3f} L/min, "
            f"step {flow_step:.3f} L/min, hold {hold_time:.0f}s/step)"
        )

        for step_idx, wet_flow in enumerate(wet_flow_targets):
            if not self.running:
                break

            dry_flow = max(0.0, max_flow - wet_flow)
            self._report(
                f"\n── Flow Step {step_idx + 1}/{len(wet_flow_targets)}: "
                f"wet={wet_flow:.3f} L/min, dry={dry_flow:.3f} L/min ──",
                on_progress,
            )

            self.set_flow_rates(
                dry_flow=dry_flow,
                wet_flow=wet_flow,
                max_flow=max_flow,
                ramp_flow=False,
            )
            step_times.append(datetime.now())

            self._hold_and_log(hold_time, control_interval, on_data)

    def _run_rh_ramp(
        self,
        rh_start: float,
        rh_end: float,
        rh_step: float,
        max_flow: float,
        control_interval: float,
        hold_time: float,
        stability_readings: int,
        stability_timeout: float,
        step_times: list,
        on_data: Optional[Callable[[Dict], None]] = None,
        on_progress: Optional[Callable[[str], None]] = None,
    ):
        """Phase 2 (RH mode): PI-stabilise to each RH target, then hold."""
        rh_targets = self._build_ramp_targets(
            rh_start, rh_end, rh_step, 0.0, 100.0, 0.01
        )

        print(
            f"RH ramp: {len(rh_targets)} steps "
            f"({rh_start:.1f}% → {rh_end:.1f}%, "
            f"step {rh_step:.1f}%, hold {hold_time:.0f}s/step)"
        )

        # Single PID carries integral momentum across all steps
        ramp_pid = RhPidController(self.config)

        for step_idx, rh_target in enumerate(rh_targets):
            if not self.running:
                break

            self._report(
                f"\n── RH Step {step_idx + 1}/{len(rh_targets)}: "
                f"target {rh_target:.1f}% ──",
                on_progress,
            )

            # Stabilise using PI, then hold
            self._stabilize_to_rh(
                target_rh=rh_target,
                pid=ramp_pid,
                max_flow=max_flow,
                stability_readings=stability_readings,
                stability_timeout=stability_timeout,
                control_interval=control_interval,
                dry_only=False,
                on_data=on_data,
                on_progress=on_progress,
            )
            if not self.running:
                break

            # Record step timestamp at the start of the hold period
            step_times.append(datetime.now())

            self._report(f"Holding at ~{rh_target:.1f}% for {hold_time:.0f}s…", on_progress)

            self._hold_and_log(hold_time, control_interval, on_data)
