from datetime import datetime
from math import isfinite
from pathlib import Path
from typing import Dict, List, Optional

from src.devices.registry import PANELS


def save_experiment_plot(
    csv_path: Optional[str],
    step_times: list,
    logger,
    manifest: Optional[List[Dict]] = None,
) -> Optional[str]:
    import matplotlib.dates as mdates
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    if not csv_path:
        return None

    rows = logger.read_log(csv_path)
    if not rows:
        return None

    manifest = list(manifest or [])
    if not manifest:
        return None

    def _to_float(v):
        """A real number, or None for anything unplottable.

        A NaN in the log (a probe reporting a quantity it cannot produce) has to
        collapse to None like a blank cell does: kept as a float it counts as a
        value, so the column earns a legend entry with no line behind it.
        """
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return f if isfinite(f) else None

    timestamps = []
    columns: Dict[str, list] = {e["column"]: [] for e in manifest}
    for row in rows:
        try:
            t = datetime.fromisoformat(row["timestamp"])
        except (KeyError, ValueError, TypeError):
            continue
        timestamps.append(t)
        for column, values in columns.items():
            values.append(_to_float(row.get(column)))

    if not timestamps:
        return None

    # One subplot per registry panel that actually has series in this run.
    panels = [(key, title, y_label) for key, title, y_label in PANELS
              if any(e["panel"] == key for e in manifest)]
    if not panels:
        return None

    fig = Figure(figsize=(12, 4 * len(panels)))
    FigureCanvasAgg(fig)
    fig.suptitle(f"RH Ramp Experiment — {timestamps[0].strftime('%Y-%m-%d %H:%M')}")

    axes = []
    for i, (key, title, y_label) in enumerate(panels):
        ax = fig.add_subplot(len(panels), 1, i + 1,
                             sharex=axes[0] if axes else None)
        axes.append(ax)

        for entry in (e for e in manifest if e["panel"] == key):
            pairs = [(t, v) for t, v in zip(timestamps, columns[entry["column"]])
                     if v is not None]
            if not pairs:
                continue
            ts, vs = zip(*pairs)
            # Setpoints dashed so they read as commanded rather than measured;
            # everything else takes the next default colour.
            ax.plot(ts, vs, label=entry["label"], linewidth=1.2,
                    linestyle="--" if entry.get("dashed") else "-")

        for st in step_times:
            ax.axvline(st, color="gray", linestyle="--", linewidth=0.7, alpha=0.6)

        ax.set_ylabel(y_label)
        ax.grid(True, alpha=0.3)
        if ax.get_legend_handles_labels()[0]:
            ax.legend(loc="upper right", fontsize=8, framealpha=0.85)

    axes[-1].set_xlabel("Time")
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    fig.autofmt_xdate()
    fig.tight_layout()

    plot_path = Path(csv_path).with_suffix(".png")
    fig.savefig(str(plot_path), dpi=120, bbox_inches="tight")
    print(f"Experiment plot saved: {plot_path}")
    return str(plot_path)
