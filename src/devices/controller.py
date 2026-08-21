import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.devices import registry as reg
from src.devices.pid_controller import RhPidController
from src.utility.data_logger import DataLogger
from src.utility.plot_saver import save_experiment_plot
from src.utility.compute_RH import compute_relative_humidity, calibrated_RH


@dataclass
class DeviceInstance:
    """A configured device: its spec from config.json plus the live driver."""
    spec: Dict[str, Any]
    driver: Any

    @property
    def id(self) -> str:
        return self.spec["id"]

    @property
    def tag(self) -> str:
        return self.spec.get("tag", self.spec["id"])

    def has_cap(self, cap: str) -> bool:
        dtype = reg.get_type(self.spec)
        return bool(dtype and cap in dtype.caps)


class Controller:
    """Orchestrates an arbitrary, user-declared set of devices.

    Devices come from ``config["devices"]`` (see :mod:`src.devices.registry`).
    Control logic never names a concrete device — it looks devices up by
    *role*, so the RH loop and the ramp experiment work unchanged whether the
    rig has two MFCs or eight.
    """

    def __init__(self, config: Dict):
        self.config = config
        self.running = False
        self.connected = False

        self.devices: Dict[str, DeviceInstance] = {}
        self.by_role: Dict[str, DeviceInstance] = {}
        self._log_fields: Optional[List[str]] = None
        self._column_prefixes: Optional[Dict[str, str]] = None

        self.logger = DataLogger(
            output_dir=self.config.get("log_dir", "data"),
            filename_prefix=self.config.get("log_prefix", "nsim_log"),
        )

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

    # ── Device set ───────────────────────────────────────────────────────────

    @property
    def device_specs(self) -> List[Dict[str, Any]]:
        return self.config.get("devices", []) or []

    @property
    def log_fields(self) -> List[str]:
        """CSV columns for the current device set (cached; see refresh_devices)."""
        if self._log_fields is None:
            self._log_fields = reg.build_log_fields(self.device_specs)
        return self._log_fields

    def build_series_manifest(self) -> List[Dict[str, Any]]:
        """Plottable series for the current device set (live plot + saved PNG)."""
        return reg.build_manifest(self.device_specs)

    @property
    def column_prefixes(self) -> Dict[str, str]:
        """Device id -> CSV column prefix, derived from the tags."""
        if self._column_prefixes is None:
            self._column_prefixes = reg.column_prefixes(self.device_specs)
        return self._column_prefixes

    def column_prefix(self, device_id: str) -> str:
        return self.column_prefixes.get(device_id, device_id)

    def refresh_devices(self) -> None:
        """Drop cached views of the device list after a settings change."""
        self._log_fields = None
        self._column_prefixes = None

    def device_by_role(self, role: str) -> Optional[DeviceInstance]:
        return self.by_role.get(role)

    def _driver_for_role(self, role: str):
        inst = self.by_role.get(role)
        return inst.driver if inst else None

    # Convenience views used by the RH loop and the ramp experiment, which care
    # about a device's function rather than its identity.
    @property
    def dry_mfc(self):
        return self._driver_for_role(reg.ROLE_DRY_FLOW)

    @property
    def wet_mfc(self):
        return self._driver_for_role(reg.ROLE_WET_FLOW)

    @property
    def chiller(self):
        return self._driver_for_role(reg.ROLE_TEMP_SOURCE)

    def mfc_instances(self) -> List[DeviceInstance]:
        """Every connected device that can take a flow setpoint, in config order."""
        return [i for i in self.devices.values() if i.has_cap("flow_setpoint")]

    def has_rh_control_roles(self) -> bool:
        """True when the RH loop has everything it needs: wet + dry + a probe."""
        specs = self.device_specs
        return all(
            reg.role_holder(specs, r) is not None
            for r in (reg.ROLE_WET_FLOW, reg.ROLE_DRY_FLOW, reg.ROLE_RH_SOURCE)
        )

    # ── Connection ───────────────────────────────────────────────────────────

    def connect_devices(self) -> Dict[str, bool]:
        results: Dict[str, bool] = {}

        # Start from a clean slate so a device that previously connected (or was
        # since removed/disabled) never lingers as a stale reference.
        self.devices = {}
        self.by_role = {}
        self.device_health = {}
        self._last_reconnect = {}
        self.refresh_devices()

        for spec in reg.enabled_specs(self.device_specs):
            dtype = reg.get_type(spec)
            dev_id = spec["id"]
            try:
                driver = dtype.factory(spec)
            except Exception as e:
                print(f"Error creating {spec.get('tag', dev_id)}: {e}")
                results[dev_id] = False
                continue

            ok = self._connect_device(driver, spec.get("tag", dev_id))
            results[dev_id] = ok
            self.device_health[dev_id] = ok
            if ok:
                inst = DeviceInstance(spec=spec, driver=driver)
                self.devices[dev_id] = inst
                role = spec.get("role", reg.ROLE_NONE)
                if role != reg.ROLE_NONE:
                    self.by_role[role] = inst

        self.connected = any(results.values()) if results else False
        print(f"Controller connected: {self.connected} (Details: {results})")
        return results

    def disconnect_devices(self):
        print("Disconnecting devices...")
        for inst in self.devices.values():
            try:
                inst.driver.disconnect()
            except Exception as e:
                print(f"Error disconnecting {inst.tag}: {e}")
        self.devices = {}
        self.by_role = {}
        self.running = False
        self.connected = False

    def is_connected(self) -> bool:
        return self.connected

    def _connect_device(self, device, name: str) -> bool:
        try:
            return bool(device.connect())
        except Exception as e:
            print(f"Error connecting {name}: {e}")
            try:
                return device.is_connected()
            except Exception:
                return False

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

        # One loop over whatever is configured. Each driver returns its readings
        # keyed by the channel keys its type declares in the registry; those land
        # in a "<device id>_<channel>" column, plus the legacy canonical column
        # when this device holds the matching role.
        prefixes = self.column_prefixes
        for dev_id, inst in self.devices.items():
            if not self._should_read(dev_id, inst.driver):
                continue
            try:
                readings = inst.driver.read()
            except Exception as e:
                print(f"Error reading {inst.tag}: {e}")
                self.device_health[dev_id] = False
                continue

            # Port open but nothing came back — device powered off / unplugged.
            if not readings or all(v is None for v in readings.values()):
                self.device_health[dev_id] = False
                continue

            self.device_health[dev_id] = True
            for ch_key, value in readings.items():
                data[reg.column_name(inst.spec, ch_key, prefixes)] = value
                alias = reg.alias_for(inst.spec, ch_key)
                if alias:
                    data[alias] = value

        self._compute_derived(data)
        return data

    @staticmethod
    def current_rh(data: Dict) -> Optional[float]:
        """The RH reading the control loop should act on.

        Preference order: computed from the external temperature probe (it
        reflects the sample environment), then from the RH source's own
        temperature, then a probe that reports RH directly (e.g. a Vaisala).
        """
        for key in ("rh_chiller", "rh_hygrometer", "rh_probe"):
            value = data.get(key)
            if value is not None:
                return value
        return None

    @staticmethod
    def _compute_derived(data: Dict) -> None:
        """Fill the computed RH columns from the role-holders' readings.

        Works off the legacy alias columns, so it is indifferent to which
        physical probe is assigned the RH / temperature source roles.
        """
        dp = data.get("dewpoint_temp")
        if dp is None:
            return
        # Skipped when the probe reports RH directly (rh_probe): deriving it
        # again from that probe's own dew point and temperature would duplicate
        # the reading. Kept in step with registry.DERIVED_SERIES, which drops
        # the column and its trace in the same case.
        if data.get("hygrometer_temp") is not None and data.get("rh_probe") is None:
            data["rh_hygrometer"] = compute_relative_humidity(dp=dp, t=data["hygrometer_temp"])
        if data.get("chiller_temp") is not None:
            data["rh_chiller"] = compute_relative_humidity(dp=dp, t=data["chiller_temp"])
            data["rh_chiller_calibrated"] = calibrated_RH(data["rh_chiller"])

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
        extra: Optional[Dict[str, float]] = None,
    ) -> bool:
        """Set flows on the dry/wet role-holders, plus any role-less MFC in ``extra``.

        ``max_flow`` bounds the *chamber* flow, so only the dry+wet pair counts
        toward it — an auxiliary MFC on its own line is not part of that budget.
        """
        if max_flow is not None:
            total = (dry_flow or 0.0) + (wet_flow or 0.0)
            if total > max_flow:
                print(
                    f"Requested total flow {total:.2f} exceeds maximum {max_flow:.2f}. Aborting."
                )
                return False

        targets = self._flow_targets(dry_flow, wet_flow, extra)
        if not targets:
            return True

        if ramp_flow:
            self._ramp_flows(targets)

        success = True
        for inst, flow in targets:
            mfc = inst.driver
            try:
                if mfc.set_flow(flow):
                    print(f"{inst.tag} setpoint set to {flow:.3f}")
                else:
                    print(f"Failed to set {inst.tag} flow")
                    success = False
            except Exception as e:
                print(f"Error setting {inst.tag}: {e}")
                success = False

        return success

    def _flow_targets(
        self,
        dry_flow: Optional[float],
        wet_flow: Optional[float],
        extra: Optional[Dict[str, float]] = None,
    ) -> List[Tuple[DeviceInstance, float]]:
        """Resolve (device, setpoint) pairs from role kwargs + explicit ids.

        The dry/wet kwargs address whichever devices hold those roles, so every
        existing caller (RH loop, experiment ramps) keeps working untouched.
        ``extra`` addresses role-less MFCs by device id.
        """
        targets: List[Tuple[DeviceInstance, float]] = []
        seen = set()
        for role, value in ((reg.ROLE_DRY_FLOW, dry_flow), (reg.ROLE_WET_FLOW, wet_flow)):
            inst = self.by_role.get(role)
            if inst is not None and value is not None and inst.has_cap("flow_setpoint"):
                targets.append((inst, float(value)))
                seen.add(inst.id)
        for dev_id, value in (extra or {}).items():
            inst = self.devices.get(dev_id)
            if (inst is not None and value is not None
                    and dev_id not in seen and inst.has_cap("flow_setpoint")):
                targets.append((inst, float(value)))
                seen.add(dev_id)
        return targets

    def get_current_flows(self) -> tuple:
        """(dry, wet) setpoints of the role-holding MFCs — used by the RH loop."""
        return (
            self.dry_mfc.get_setpoint() if self.dry_mfc else 0.0,
            self.wet_mfc.get_setpoint() if self.wet_mfc else 0.0,
        )

    def get_flow_setpoints(self) -> Dict[str, float]:
        """Current setpoint of every connected MFC, keyed by device id."""
        setpoints = {}
        for inst in self.mfc_instances():
            try:
                setpoints[inst.id] = inst.driver.get_setpoint()
            except Exception:
                setpoints[inst.id] = 0.0
        return setpoints

    def _ramp_flows(self, targets: List[Tuple[DeviceInstance, float]]):
        """Walk every target from its current setpoint to the new one together."""
        moves = []
        max_delta = 0.0
        for inst, target in targets:
            try:
                current = inst.driver.get_setpoint()
            except Exception:
                current = 0.0
            moves.append((inst, current, target - current))
            max_delta = max(max_delta, abs(target - current))

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
            for inst, current, diff in moves:
                try:
                    inst.driver.set_flow(current + diff * frac)
                except Exception as e:
                    print(f"Error during {inst.tag} ramp step {i}: {e}")
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
            current_rh: Optional[float] = self.current_rh(data)

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
                plot_path = save_experiment_plot(
                    csv_path, step_times, self.logger, self.build_series_manifest()
                )
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
