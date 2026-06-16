import time
from datetime import datetime
from typing import Callable, Dict, Optional

from src.devices.chiller import JulaboChiller
from src.devices.hygrometer import Hygrometer
from src.devices.pid_controller import RhPidController
from src.devices.vogtlin_mfc import VogtlinMFC
from src.utility.data_logger import DataLogger
from src.utility.plot_saver import save_experiment_plot
from src.utility.compute_RH import compute_relative_humidity


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
            "chiller_temp",
            "chiller_setpoint",
        ]

        self.rh_control_active = False
        self.rh_setpoint = 50.0
        self.rh_control_total_flow = 2.0
        self.pid = RhPidController(config)

    # ── Connection ───────────────────────────────────────────────────────────

    def connect_devices(self) -> Dict[str, bool]:
        cfg = self.config
        results: Dict[str, bool] = {}

        if cfg.get("dry_mfc_enabled") and "dry_mfc_port" in cfg:
            self.dry_mfc = VogtlinMFC(
                port=cfg["dry_mfc_port"],
                address=cfg.get("dry_mfc_address", 1),
                name="Dry Air MFC",
            )
            results["dry_mfc"] = self._connect_device(self.dry_mfc, "dry MFC")

        if cfg.get("wet_mfc_enabled") and "wet_mfc_port" in cfg:
            self.wet_mfc = VogtlinMFC(
                port=cfg["wet_mfc_port"],
                address=cfg.get("wet_mfc_address", 247),
                name="Wet Air MFC",
            )
            results["wet_mfc"] = self._connect_device(self.wet_mfc, "wet MFC")

        if cfg.get("hygrometer_enabled") and "hygrometer_port" in cfg:
            self.hygrometer = Hygrometer(
                port=cfg["hygrometer_port"],
                baudrate=cfg.get("hygrometer_baudrate", 9600),
            )
            results["hygrometer"] = self._connect_device(self.hygrometer, "hygrometer")

        if cfg.get("chiller_enabled") and "chiller_port" in cfg:
            self.chiller = JulaboChiller(
                port=cfg["chiller_port"],
                baudrate=cfg.get("chiller_baudrate", 9600),
            )
            results["chiller"] = self._connect_device(self.chiller, "chiller")

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
        data: Dict[str, Optional[float | str]] = {
            "timestamp": datetime.now().isoformat(),
            "dry_flow": None,
            "wet_flow": None,
            "dry_flow_setpoint": None,
            "wet_flow_setpoint": None,
            "hygrometer_temp": None,
            "dewpoint_temp": None,
            "rh_hygrometer": None,
            "rh_chiller": None,
            "chiller_temp": None,
            "chiller_setpoint": None,
        }

        if self.dry_mfc:
            try:
                data["dry_flow"] = self.dry_mfc.get_flow()
                data["dry_flow_setpoint"] = self.dry_mfc.get_setpoint()
            except Exception as e:
                print(f"Error reading dry MFC: {e}")

        if self.wet_mfc:
            try:
                data["wet_flow"] = self.wet_mfc.get_flow()
                data["wet_flow_setpoint"] = self.wet_mfc.get_setpoint()
            except Exception as e:
                print(f"Error reading wet MFC: {e}")

        if self.hygrometer:
            try:
                readings = self.hygrometer.get_readings()
                if readings:
                    data["hygrometer_temp"] = readings.get("hygrometer_temp")
                    data["dewpoint_temp"] = readings.get("dewpoint_temp")
            except Exception as e:
                print(f"Error reading hygrometer: {e}")

        if self.chiller:
            try:
                data["chiller_temp"] = self.chiller.get_external_temperature()
                data["chiller_setpoint"] = self.chiller.get_setpoint_temperature()
            except Exception as e:
                print(f"Error reading chiller: {e}")

        if self.hygrometer and data["dewpoint_temp"] is not None:
            dp = data["dewpoint_temp"]
            if data["hygrometer_temp"] is not None:
                data["rh_hygrometer"] = compute_relative_humidity(dp=dp, t=data["hygrometer_temp"])
            if data["chiller_temp"] is not None:
                data["rh_chiller"] = compute_relative_humidity(dp=dp, t=data["chiller_temp"])

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
                msg = (
                    f"Stabilisation toward {target_rh:.1f}% timed out after "
                    f"{stability_timeout:.0f}s — proceeding anyway."
                )
                print(msg)
                if on_progress:
                    try:
                        on_progress(msg)
                    except Exception:
                        pass
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

                msg = (
                    f"Stabilising → {target_rh:.1f}% | "
                    f"current {current_rh:.1f}% "
                    f"({stable_count}/{stability_readings} stable)"
                )
                print(msg)
                if on_progress:
                    try:
                        on_progress(msg)
                    except Exception:
                        pass

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
                    precond_cfg = {
                        **self.config,
                        'rh_max_step': min(0.5, max(self.config.get('rh_max_step', 0.05) * 4, 0.2)),
                    }
                    precondpid = RhPidController(precond_cfg)
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

            else:  # mode == "rh"
                going_up = rh_end >= rh_start
                precond_target = rh_start if going_up else rh_end
                dry_only_precond = going_up and precond_target == 0.0

                deadband = self.pid.params["deadband"]
                precond_cfg = {
                    **self.config,
                    'rh_max_step': min(0.5, max(self.config.get('rh_max_step', 0.05) * 4, 0.2)),
                }
                precondpid = RhPidController(precond_cfg)

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

            if not self.running:
                return None

            # ── Phase 2: Ramp ─────────────────────────────────────────────────
            if mode == "flow":
                # Build wet flow target list in L/min
                direction = 1 if flow_end >= flow_start else -1
                n_steps = int(round(abs(flow_end - flow_start) / max(1e-6, flow_step))) + 1
                wet_flow_targets = [
                    round(max(0.0, min(max_flow, flow_start + direction * i * flow_step)), 6)
                    for i in range(n_steps)
                ]
                if abs(wet_flow_targets[-1] - flow_end) > 0.001:
                    wet_flow_targets.append(round(max(0.0, min(max_flow, flow_end)), 6))

                print(
                    f"Flow ramp: {len(wet_flow_targets)} steps "
                    f"({flow_start:.3f} → {flow_end:.3f} L/min, "
                    f"step {flow_step:.3f} L/min, hold {hold_time:.0f}s/step)"
                )

                for step_idx, wet_flow in enumerate(wet_flow_targets):
                    if not self.running:
                        break

                    dry_flow = max(0.0, max_flow - wet_flow)
                    msg = (
                        f"\n── Flow Step {step_idx + 1}/{len(wet_flow_targets)}: "
                        f"wet={wet_flow:.3f} L/min, dry={dry_flow:.3f} L/min ──"
                    )
                    print(msg)
                    if on_progress:
                        try:
                            on_progress(msg)
                        except Exception:
                            pass

                    self.set_flow_rates(
                        dry_flow=dry_flow,
                        wet_flow=wet_flow,
                        max_flow=max_flow,
                        ramp_flow=False,
                    )
                    step_times.append(datetime.now())

                    elapsed = 0.0
                    while elapsed < hold_time and self.running:
                        cycle_start = time.time()
                        self.read_and_log(on_data)
                        elapsed += control_interval
                        sleep_time = control_interval - (time.time() - cycle_start)
                        if sleep_time > 0:
                            time.sleep(sleep_time)

            else:  # mode == "rh"
                going_up = rh_end >= rh_start
                direction = 1 if going_up else -1
                n_steps = int(round(abs(rh_end - rh_start) / max(1e-6, rh_step))) + 1
                rh_targets = [
                    round(max(0.0, min(100.0, rh_start + direction * i * rh_step)), 6)
                    for i in range(n_steps)
                ]
                if abs(rh_targets[-1] - rh_end) > 0.01:
                    rh_targets.append(round(max(0.0, min(100.0, rh_end)), 6))

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

                    msg = (
                        f"\n── RH Step {step_idx + 1}/{len(rh_targets)}: "
                        f"target {rh_target:.1f}% ──"
                    )
                    print(msg)
                    if on_progress:
                        try:
                            on_progress(msg)
                        except Exception:
                            pass

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

                    hold_msg = f"Holding at ~{rh_target:.1f}% for {hold_time:.0f}s…"
                    print(hold_msg)
                    if on_progress:
                        try:
                            on_progress(hold_msg)
                        except Exception:
                            pass

                    elapsed = 0.0
                    while elapsed < hold_time and self.running:
                        cycle_start = time.time()
                        self.read_and_log(on_data)
                        elapsed += control_interval
                        sleep_time = control_interval - (time.time() - cycle_start)
                        if sleep_time > 0:
                            time.sleep(sleep_time)

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
