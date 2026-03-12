CONFIG = {
    # Data logging settings
    "log_dir": "data",
    "log_prefix": "nsim_log",
    # Plotting settings
    "max_plot_points": 500,  # Maximum number of points to display
    # Device settings (ports, baudrates, addresses, enable flags) are machine-specific
    # and must be set in local_config.py (gitignored). See local_config.example.py.
    # Automated experiment settings
    "experiment_direction": "up",  # "up" or "down"
    "experiment_step_size": 5.0,  # Wet-flow increment per step (% of total flow, 0–100)
    "experiment_hold_time": 180.0,  # Seconds to wait at each flow step before advancing
    "max_flow": 2.0,  # Maximum/target total flow rate (dry + wet) in L/min
    "control_interval": 5000,  # Update interval in milliseconds
    # RH interval / pre-conditioning
    # rh_lower: lower bound of the RH interval. For "up" experiments this is the
    # pre-conditioning target; 0.0 = set dry-only flow and wait for equilibration.
    "experiment_rh_lower": 0.0,
    # rh_upper: upper bound of the RH interval. For "down" experiments this is the
    # pre-conditioning target. Set below 100 if the cell cannot reach 100% RH
    # (typically requires chiller ≤ 15 °C).
    "experiment_rh_upper": 90.0,
    # stability_readings: consecutive readings within ±deadband to declare stable.
    "experiment_stability_readings": 5,
    # stability_timeout: max seconds to wait for stability before proceeding anyway.
    "experiment_stability_timeout": 600.0,
    # RH PI controller tuning
    # settling_time: maximum seconds to wait after a full-scale flow change (e.g. 0 → max_flow).
    # The actual wait scales linearly with the size of each step; the lower bound is
    # rh_settling_time_min.  3 min for a 2 L/min step is a reasonable starting point.
    "rh_settling_time": 180.0,
    # settling_time_min: minimum wait regardless of how small the flow change is (seconds).
    "rh_settling_time_min": 5.0,
    # deadband: ignore errors smaller than this (±%) — avoids chasing sensor noise.
    "rh_deadband": 1.0,
    # max_step: wet-ratio change ceiling when |error| = 100 %.
    # The actual step scales linearly with |error|, so at 10 % error the
    # permitted change is max_step * 0.10 — much smaller near the setpoint.
    "rh_max_step": 0.05,
    # PID gains — lower Kp/Ki than a fast system; settling_time enforces patience.
    "rh_kp": 0.02,
    "rh_ki": 0.001,
    # Kd = 0 disables the D term (safe default). Set to ~0.05 to activate damping.
    # The D term brakes the approach to the setpoint, reducing overshoot on the
    # first correction after each settling period.
    "rh_kd": 0.05,
    # Low-pass filter time constant for the derivative (seconds).
    # Filters high-frequency noise from the dew-point mirror before differentiation.
    # Should be comparable to the hygrometer's own response time (~10–60 s).
    "rh_derivative_filter_tau": 30.0,
    "rh_integral_limit": 0.5,
}
