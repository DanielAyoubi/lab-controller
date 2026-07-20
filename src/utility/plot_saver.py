from datetime import datetime
from pathlib import Path
from typing import Optional


def save_experiment_plot(csv_path: Optional[str], step_times: list, logger) -> Optional[str]:
    import matplotlib.dates as mdates
    import numpy as np
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    if not csv_path:
        return None

    rows = logger.read_log(csv_path)
    if not rows:
        return None

    def _to_float(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    # Buffers for every series the two dual-axis panels draw.
    timestamps = []
    dry_flows, wet_flows = [], []
    dry_flow_sps, wet_flow_sps = [], []
    rh_hyg, rh_chill, rh_chill_cal = [], [], []
    dewpoints, hyg_temps, chill_temps, chill_sps = [], [], [], []
    oxygen = []

    for row in rows:
        try:
            t = datetime.fromisoformat(row["timestamp"])
        except (KeyError, ValueError, TypeError):
            continue
        timestamps.append(t)
        dry_flows.append(_to_float(row.get("dry_flow")))
        wet_flows.append(_to_float(row.get("wet_flow")))
        dry_flow_sps.append(_to_float(row.get("dry_flow_setpoint")))
        wet_flow_sps.append(_to_float(row.get("wet_flow_setpoint")))
        rh_hyg.append(_to_float(row.get("rh_hygrometer")))
        rh_chill.append(_to_float(row.get("rh_chiller")))
        rh_chill_cal.append(_to_float(row.get("rh_chiller_calibrated")))
        dewpoints.append(_to_float(row.get("dewpoint_temp")))
        hyg_temps.append(_to_float(row.get("hygrometer_temp")))
        chill_temps.append(_to_float(row.get("chiller_temp")))
        chill_sps.append(_to_float(row.get("chiller_setpoint")))
        oxygen.append(_to_float(row.get("oxygen")))

    if not timestamps:
        return None

    # Auto-scale smoothing window: roughly 1/30th of total points, min 5
    window = max(5, len(timestamps) // 30)

    def _smooth(values):
        arr = np.array(values, dtype=float)
        # Clamp the kernel to the series length so np.convolve(mode="same")
        # returns an array the same length as the x-values (avoids a shape
        # mismatch in ax.plot when a series has fewer points than `window`).
        w = min(window, len(arr))
        if w < 1:
            return arr
        kernel = np.ones(w) / w
        return np.convolve(arr, kernel, mode="same")

    def _plot_series_with_smooth(ax, vals, label, color):
        """Raw (faint) + smoothed (bold) trace, matching the live plot's solids."""
        pairs = [(t, v) for t, v in zip(timestamps, vals) if v is not None]
        if not pairs:
            return
        ts, vs = zip(*pairs)
        vs_arr = list(vs)
        ax.plot(ts, vs_arr, color=color, linewidth=0.8, alpha=0.25)
        smoothed = _smooth(vs_arr)
        ax.plot(ts, smoothed, label=label, color=color, linewidth=1.8, alpha=1.0)

    def _plot_dashed(ax, vals, label, color):
        """Setpoint trace: dashed, semi-transparent, no smoothing/markers."""
        pairs = [(t, v) for t, v in zip(timestamps, vals) if v is not None]
        if not pairs:
            return
        ts, vs = zip(*pairs)
        ax.plot(ts, list(vs), label=label, color=color, linewidth=1.2,
                linestyle="--", alpha=0.5)

    def _merge_legends(ax_left, ax_right):
        h1, l1 = ax_left.get_legend_handles_labels()
        h2, l2 = ax_right.get_legend_handles_labels()
        if h1 or h2:
            ax_left.legend(h1 + h2, l1 + l2, loc="upper right", fontsize=8)

    fig = Figure(figsize=(12, 8))
    FigureCanvasAgg(fig)
    ax0 = fig.add_subplot(2, 1, 1)
    ax1 = fig.add_subplot(2, 1, 2, sharex=ax0)

    fig.suptitle(f"RH Ramp Experiment — {timestamps[0].strftime('%Y-%m-%d %H:%M')}")

    for ax in (ax0, ax1):
        for st in step_times:
            ax.axvline(st, color="gray", linestyle="--", linewidth=0.7, alpha=0.6)

    # Panel 1 — Flow & RH: RH on the left axis, flows on a twin right axis.
    _plot_series_with_smooth(ax0, rh_chill, "RH (chiller)", "royalblue")
    _plot_series_with_smooth(ax0, rh_chill_cal, "RH (chiller, calibrated)", "firebrick")
    _plot_series_with_smooth(ax0, rh_hyg, "RH (hygrometer)", "mediumvioletred")
    ax0.set_ylabel("RH (%)")
    ax0.grid(True, alpha=0.3)
    ax0f = ax0.twinx()
    _plot_series_with_smooth(ax0f, dry_flows, "Dry flow", "green")
    _plot_series_with_smooth(ax0f, wet_flows, "Wet flow", "darkorange")
    _plot_dashed(ax0f, dry_flow_sps, "Dry flow set", "green")
    _plot_dashed(ax0f, wet_flow_sps, "Wet flow set", "darkorange")
    ax0f.set_ylabel("Flow rate (L/min)")
    _merge_legends(ax0, ax0f)

    # Panel 2 — Temperature & O₂: temps on the left axis, O₂ on a twin right axis.
    _plot_series_with_smooth(ax1, dewpoints, "Dewpoint", "darkcyan")
    _plot_series_with_smooth(ax1, chill_temps, "Chiller temp", "royalblue")
    _plot_dashed(ax1, chill_sps, "Chiller set", "royalblue")
    _plot_series_with_smooth(ax1, hyg_temps, "Hygrometer temp", "darkorange")
    ax1.set_ylabel("Temperature (°C)")
    ax1.set_xlabel("Time")
    ax1.grid(True, alpha=0.3)
    ax1f = ax1.twinx()
    _plot_series_with_smooth(ax1f, oxygen, "O₂ (FireSting)", "green")
    ax1f.set_ylabel("O₂ (%)")
    _merge_legends(ax1, ax1f)

    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    fig.autofmt_xdate()
    fig.tight_layout()

    plot_path = Path(csv_path).with_suffix(".png")
    fig.savefig(str(plot_path), dpi=150, bbox_inches="tight")
    print(f"Experiment plot saved: {plot_path}")
    return str(plot_path)
