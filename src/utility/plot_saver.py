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

    timestamps, dry_flows, wet_flows = [], [], []
    hyg_temps, chill_temps = [], []
    rh_hyg, rh_chill = [], []

    for row in rows:
        try:
            t = datetime.fromisoformat(row["timestamp"])
        except (KeyError, ValueError, TypeError):
            continue
        timestamps.append(t)
        dry_flows.append(_to_float(row.get("dry_flow")))
        wet_flows.append(_to_float(row.get("wet_flow")))
        hyg_temps.append(_to_float(row.get("hygrometer_temp")))
        chill_temps.append(_to_float(row.get("chiller_temp")))
        rh_hyg.append(_to_float(row.get("rh_hygrometer")))
        rh_chill.append(_to_float(row.get("rh_chiller")))

    if not timestamps:
        return None

    # Auto-scale smoothing window: roughly 1/30th of total points, min 5
    window = max(5, len(timestamps) // 30)

    def _smooth(values):
        arr = np.array(values, dtype=float)
        kernel = np.ones(window) / window
        return np.convolve(arr, kernel, mode="same")

    def _plot_series_with_smooth(ax, ts_list, vals, label, color):
        pairs = [(t, v) for t, v in zip(ts_list, vals) if v is not None]
        if not pairs:
            return
        ts, vs = zip(*pairs)
        vs_arr = list(vs)
        ax.plot(ts, vs_arr, color=color, linewidth=0.8, alpha=0.25)
        smoothed = _smooth(vs_arr)
        ax.plot(ts, smoothed, label=label, color=color, linewidth=1.8, alpha=1.0)

    fig = Figure(figsize=(12, 8))
    FigureCanvasAgg(fig)
    ax0 = fig.add_subplot(3, 1, 1)
    ax1 = fig.add_subplot(3, 1, 2, sharex=ax0)
    ax2 = fig.add_subplot(3, 1, 3, sharex=ax0)

    fig.suptitle(f"RH Ramp Experiment — {timestamps[0].strftime('%Y-%m-%d %H:%M')}")

    for ax in (ax0, ax1, ax2):
        for st in step_times:
            ax.axvline(st, color="gray", linestyle="--", linewidth=0.7, alpha=0.6)

    _plot_series_with_smooth(ax0, timestamps, dry_flows, "Dry flow", "steelblue")
    _plot_series_with_smooth(ax0, timestamps, wet_flows, "Wet flow", "darkorange")
    ax0.set_ylabel("Flow rate (L/min)")
    ax0.legend(loc="upper right", fontsize=8)
    ax0.grid(True, alpha=0.3)

    _plot_series_with_smooth(ax1, timestamps, hyg_temps, "Hygrometer temp", "darkorange")
    _plot_series_with_smooth(ax1, timestamps, chill_temps, "Chiller temp", "firebrick")
    ax1.set_ylabel("Temperature (°C)")
    ax1.legend(loc="upper right", fontsize=8)
    ax1.grid(True, alpha=0.3)

    _plot_series_with_smooth(ax2, timestamps, rh_hyg, "RH (hygrometer)", "mediumpurple")
    _plot_series_with_smooth(ax2, timestamps, rh_chill, "RH (chiller)", "royalblue")
    ax2.set_ylabel("Relative humidity (%)")
    ax2.set_xlabel("Time")
    ax2.legend(loc="upper right", fontsize=8)
    ax2.grid(True, alpha=0.3)

    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    fig.autofmt_xdate()
    fig.tight_layout()

    plot_path = Path(csv_path).with_suffix(".png")
    fig.savefig(str(plot_path), dpi=150, bbox_inches="tight")
    print(f"Experiment plot saved: {plot_path}")
    return str(plot_path)
