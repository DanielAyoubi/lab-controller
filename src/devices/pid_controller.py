import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PidState:
    integral: float = 0.0
    last_time: float = field(default_factory=time.time)
    last_adjustment_time: float = 0.0
    last_meas_time: float = field(default_factory=time.time)
    prev_rh: float = 0.0
    filtered_d: float = 0.0
    dynamic_settling_time: float = 180.0


class RhPidController:
    """RH PI(D) controller with settling guard, deadband, and dynamic step clamping.

    Three guards are applied in order each time compute() is called:
      1. Settling guard  — waits after each flow change for the system to equilibrate.
      2. Deadband        — ignores errors < ±rh_deadband% (avoids chasing sensor noise).
      3. Dynamic step cap — wet-ratio change scales with |error|/100 so the controller
                           takes large strides far from setpoint and feathers in as it
                           converges.

    The D term acts on the measurement (not the error) to prevent derivative spikes when
    the setpoint changes between experiment steps.  A first-order low-pass filter
    (time constant derivative_filter_tau) attenuates high-frequency mirror noise.
    Set Kd = 0 to disable the D term.
    """

    def __init__(self, config: dict):
        self._params = self._build_params(config)
        self.state = PidState(dynamic_settling_time=self._params["settling_time"])

    # ── Public API ────────────────────────────────────────────────────────────

    def update_params(self, config: dict):
        self._params = self._build_params(config)

    def reset(self):
        self.state = PidState(
            last_time=time.time(),
            last_adjustment_time=0.0,
            dynamic_settling_time=self._params["settling_time"],
        )

    def compute(
        self,
        target_rh: float,
        current_rh: float,
        curr_dry_sp: float,
        curr_wet_sp: float,
        total_flow: float,
    ) -> Optional[float]:
        """Run one PID step given current MFC setpoints.

        Returns the new wet flow ratio (0–1), or None if no adjustment is needed yet.
        On a non-None return, state.dynamic_settling_time is updated; the caller should
        record the adjustment time::

            new_ratio = pid.compute(target, measured, dry_sp, wet_sp, total_flow)
            if new_ratio is not None:
                controller.set_flow_rates(...)
                pid.state.last_adjustment_time = time.time()
        """
        now = time.time()
        s = self.state
        p = self._params

        # --- D on measurement: update every call (even during settling) -------
        kd = p["Kd"]
        dt_meas = now - s.last_meas_time
        if kd > 0.0 and dt_meas > 0.5:
            d_raw = (current_rh - s.prev_rh) / dt_meas
            tau_d = max(p["derivative_filter_tau"], 1.0)
            alpha = dt_meas / (tau_d + dt_meas)
            s.filtered_d = (1.0 - alpha) * s.filtered_d + alpha * d_raw
        s.prev_rh = current_rh
        s.last_meas_time = now

        # --- Settling guard ---------------------------------------------------
        remaining = s.dynamic_settling_time - (now - s.last_adjustment_time)
        if remaining > 0:
            s.last_time = now
            return None

        dt = now - s.last_time
        if dt < 1.0:
            return None

        error = target_rh - current_rh

        # --- Deadband ---------------------------------------------------------
        if abs(error) < p["deadband"]:
            s.last_time = now
            s.integral = 0.0  # bleed integral while on target
            return None

        # --- PID terms --------------------------------------------------------
        p_term = p["Kp"] * error

        ki = p["Ki"]
        s.integral += error * dt
        limit = p["integral_limit"] / ki if ki > 0 else 0.0
        s.integral = max(-limit, min(limit, s.integral))
        i_term = ki * s.integral

        # Negative sign: when measurement rises toward setpoint d_filtered > 0,
        # so d_term < 0 — damps the approach and reduces overshoot.
        d_term = -kd * s.filtered_d if kd > 0.0 else 0.0

        output_change = p_term + i_term + d_term

        # --- Dynamic step clamp -----------------------------------------------
        dynamic_max_step = p["max_step"] * (abs(error) / 100.0)
        output_change = max(-dynamic_max_step, min(dynamic_max_step, output_change))

        s.last_time = now

        if abs(output_change) <= 0.0001:
            return None

        # --- New wet ratio -----------------------------------------------------
        total_sp = curr_dry_sp + curr_wet_sp
        if total_sp <= 0.01:
            new_wet_ratio = max(0.0, min(1.0, target_rh / 100.0))
        else:
            new_wet_ratio = max(0.0, min(1.0, curr_wet_sp / total_sp + output_change))

        # --- Dynamic settling time --------------------------------------------
        new_dry_sp = (1.0 - new_wet_ratio) * total_flow
        new_wet_sp = new_wet_ratio * total_flow
        delta = abs(new_dry_sp - curr_dry_sp) + abs(new_wet_sp - curr_wet_sp)
        ref = max(0.01, p["max_flow"])
        t_min = p["settling_time_min"]
        t_max = p["settling_time"]
        s.dynamic_settling_time = t_min + (t_max - t_min) * min(1.0, delta / ref)

        return new_wet_ratio

    def get_status(self, rh_setpoint: float, current_rh: Optional[float]) -> str:
        """Return a human-readable status string for display in the GUI."""
        now = time.time()
        remaining = self.state.dynamic_settling_time - (
            now - self.state.last_adjustment_time
        )
        rh_str = f"{current_rh:.1f}%" if current_rh is not None else "N/A"
        if remaining > 0:
            return f"Settling ({remaining:.0f}s) | {rh_str}"
        if current_rh is not None:
            error = rh_setpoint - current_rh
            if abs(error) < self._params["deadband"]:
                return f"At target | {rh_str}"
            return f"Adjusting (err={error:+.1f}%) | {rh_str}"
        return f"Active | {rh_str}"

    @property
    def params(self) -> dict:
        return self._params

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _build_params(config: dict) -> dict:
        return {
            "Kp": config.get("rh_kp", 0.02),
            "Ki": config.get("rh_ki", 0.001),
            "Kd": config.get("rh_kd", 0.0),
            "derivative_filter_tau": config.get("rh_derivative_filter_tau", 30.0),
            "integral_limit": config.get("rh_integral_limit", 0.5),
            "settling_time": config.get("rh_settling_time", 180.0),
            "settling_time_min": config.get("rh_settling_time_min", 5.0),
            "max_flow": config.get("max_flow", 2.0),
            "deadband": config.get("rh_deadband", 1.0),
            "max_step": config.get("rh_max_step", 0.05),
        }
