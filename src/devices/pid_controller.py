import time
from dataclasses import dataclass, field
from typing import Optional


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


@dataclass
class PidState:
    integral: float = 0.0
    last_time: float = field(default_factory=time.time)
    last_adjustment_time: float = 0.0
    last_meas_time: float = field(default_factory=time.time)
    prev_rh: float = 0.0
    filtered_d: float = 0.0
    dynamic_settling_time: float = 180.0
    prev_target: Optional[float] = None  # None until the first compute() call
    extra_settling: float = 0.0  # one-shot soak added to the next armed settle


class RhPidController:
    """RH controller: static feedforward operating point + PI(D) trim.

    The wet/dry mixing plant has an (approximately) known static inverse: with a
    saturating bubble bath on the wet line, steady-state RH ≈ 100 · wet_ratio.
    So instead of crawling the ratio up from its current value with rate-limited
    feedback (which is what made the old loop slow to settle from a cold start),
    we jump straight to the model estimate and let feedback trim only the small
    residual:

        wet_ratio = target/100                             ← feedforward (instant)
                  + Kp·error + Ki·∫error + D-on-measurement  ← PI(D) trim

    The feedforward is the plant physics, computed from the target each step —
    there is no stored calibration. Any departure from it (bubbler under-
    saturation, probe offset) is learned at runtime by the integral term below.

    The integral term holds the *calibration bias* (bubbler under-saturation,
    temperature/probe offset). That bias is ~constant across targets, so it is
    preserved across setpoint changes — only the feedforward jumps. This is what
    makes the loop fast: one model-based jump lands within a few % RH, then the
    PI trim closes the rest in a correction or two.

    Guards retained from the original design:
      1. Settling guard  — waits ≥ the transport dead time after each flow change
                           so every correction is evaluated *after* its effect has
                           propagated through the tubing (avoids dead-time-driven
                           over-correction and oscillation).
      2. Deadband        — ignores errors < ±rh_deadband% (avoids chasing noise);
                           the integral is held, not decayed, so the learned bias
                           survives.
      3. Trim clamp      — bounds the feedback contribution so a noisy reading can
                           never fling the ratio far from the feedforward estimate.

    The D term acts on the measurement (not the error) so it does not spike when
    the setpoint changes between experiment steps. Set Kd = 0 to disable it.
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
        """Run one control step given current MFC setpoints.

        Returns the new wet flow ratio (0–1), or None if no adjustment is needed
        yet. On a non-None return, state.dynamic_settling_time is updated; the
        caller should record the adjustment time::

            new_ratio = pid.compute(target, measured, dry_sp, wet_sp, total_flow)
            if new_ratio is not None:
                controller.set_flow_rates(...)
                pid.state.last_adjustment_time = time.time()
        """
        now = time.time()
        s = self.state
        p = self._params

        # ── Feedforward operating point ───────────────────────────────────────
        # The wet ratio the static plant model says will yield target_rh. With a
        # saturating bubbler on the wet line, steady-state RH ≈ 100 · wet_ratio,
        # so this is derived fresh each step rather than from a stored fit.
        ratio_ff = _clamp(target_rh / 100.0, 0.0, 1.0)

        # ── D on measurement: update every call (even during settling) ─────────
        kd = p["Kd"]
        dt_meas = now - s.last_meas_time
        if kd > 0.0 and dt_meas > 0.5:
            d_raw = (current_rh - s.prev_rh) / dt_meas
            tau_d = max(p["derivative_filter_tau"], 1.0)
            alpha = dt_meas / (tau_d + dt_meas)
            s.filtered_d = (1.0 - alpha) * s.filtered_d + alpha * d_raw
        s.prev_rh = current_rh
        s.last_meas_time = now

        # ── Setpoint change → jump to the feedforward operating point ─────────
        # Command pure feedforward plus the carried calibration bias (Ki·∫). We
        # deliberately exclude the P and D terms here: the hygrometer still reads
        # the *pre-jump* RH (it is behind the dead time), so a P term would see
        # the full error and double-count the move the feedforward just made,
        # overshooting badly. Trim is deferred until the jump has settled and the
        # measurement reflects it.
        setpoint_changed = (
            s.prev_target is None or abs(target_rh - s.prev_target) > 1e-6
        )
        if setpoint_changed:
            s.prev_target = target_rh
            new_wet_ratio = _clamp(ratio_ff + p["Ki"] * s.integral, 0.0, 1.0)
            s.last_time = now
            s.last_adjustment_time = now
            self._arm_settling(curr_dry_sp, curr_wet_sp, new_wet_ratio, total_flow)
            return new_wet_ratio

        # ── Settling guard (≥ transport dead time) ────────────────────────────
        remaining = s.dynamic_settling_time - (now - s.last_adjustment_time)
        if remaining > 0:
            s.last_time = now
            return None

        dt = now - s.last_time
        if dt < 1.0:
            return None

        error = target_rh - current_rh

        # ── Deadband ──────────────────────────────────────────────────────────
        # Hold (do not decay) the integral: it encodes the calibration bias.
        if abs(error) < p["deadband"]:
            s.last_time = now
            return None

        # ── PI(D) trim around the feedforward operating point ─────────────────
        # The measurement has now settled, so error is the *residual* the
        # feedforward could not account for — exactly what P, I and D should act on.
        ki = p["Ki"]
        s.integral += error * dt
        if ki > 0.0:
            ilim = p["integral_limit"] / ki  # so |Ki·integral| ≤ integral_limit
            s.integral = _clamp(s.integral, -ilim, ilim)
        i_term = ki * s.integral

        p_term = p["Kp"] * error
        # Negative sign: as the measurement rises toward setpoint filtered_d > 0,
        # so d_term < 0 — damps the approach and reduces overshoot.
        d_term = -kd * s.filtered_d if kd > 0.0 else 0.0

        trim = _clamp(p_term + i_term + d_term, -p["trim_limit"], p["trim_limit"])

        new_wet_ratio = _clamp(ratio_ff + trim, 0.0, 1.0)
        s.last_time = now
        self._arm_settling(curr_dry_sp, curr_wet_sp, new_wet_ratio, total_flow)

        return new_wet_ratio

    def _arm_settling(
        self, curr_dry_sp: float, curr_wet_sp: float,
        new_wet_ratio: float, total_flow: float,
    ):
        """Set the dynamic settling time from the size of the commanded move.

        Big repositioning moves wait longer (up to settling_time); but never less
        than the transport dead time, so a correction is always judged after its
        effect has propagated to the hygrometer.

        ``state.extra_settling`` adds a one-shot soak on top (consumed here), for
        callers that repositioned the flows themselves before the first compute()
        — e.g. experiment pre-conditioning.
        """
        p = self._params
        new_dry_sp = (1.0 - new_wet_ratio) * total_flow
        new_wet_sp = new_wet_ratio * total_flow
        delta = abs(new_dry_sp - curr_dry_sp) + abs(new_wet_sp - curr_wet_sp)
        ref = max(0.01, p["max_flow"])
        t_min = max(p["settling_time_min"], p["dead_time"])
        t_max = max(p["settling_time"], t_min)
        self.state.dynamic_settling_time = (
            t_min + (t_max - t_min) * min(1.0, delta / ref) + self.state.extra_settling
        )
        self.state.extra_settling = 0.0

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
            "Kp": config.get("rh_kp", 0.01),
            "Ki": config.get("rh_ki", 0.002),
            "Kd": config.get("rh_kd", 0.0),
            "derivative_filter_tau": config.get("rh_derivative_filter_tau", 30.0),
            "integral_limit": config.get("rh_integral_limit", 0.5),
            "settling_time": config.get("rh_settling_time", 180.0),
            "settling_time_min": config.get("rh_settling_time_min", 5.0),
            "max_flow": config.get("max_flow", 2.0),
            "deadband": config.get("rh_deadband", 1.0),
            "dead_time": config.get("rh_dead_time", 25.0),
            "trim_limit": config.get("rh_trim_limit", 0.6),
        }
