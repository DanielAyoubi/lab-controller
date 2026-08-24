from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from src.devices.registry import PANELS

# ── Series styling ───────────────────────────────────────────────────────────
# Mirrors plot_widget.py in Matplotlib's vocabulary so the saved PNG matches the
# live plot: colour identifies the *device*, and every series it contributes
# shares that colour in every panel. Keep the palette in step with plot_widget.

# Colour-blind-friendly ordering: blue / orange / green / red first.
_PALETTE = [
    "#1f77b4",  # blue
    "#ff7f0e",  # orange
    "#2ca02c",  # green
    "#d62728",  # red
    "#9467bd",  # purple
    "#17becf",  # cyan
    "#e377c2",  # pink
    "#8c564b",  # brown
    "#bcbd22",  # olive
    "#7f7f7f",  # grey
]

# Same shapes as the live plot's pyqtgraph symbols, in Matplotlib's codes.
_MARKERS = ["o", "s", "v", "D", "p", "h", "*", "^"]

# Line styles for a device's *measurement* channels landing in the same panel.
# "--" is reserved: it always and only means a setpoint.
_LINE_STYLES = ["-", "-.", ":"]

_WIDTH_MEASURED = 2.2
_WIDTH_SETPOINT = 5.0
_SETPOINT_TINT = 0.6     # how far to blend the device colour toward white
_Z_MEASURED = 1
_Z_SETPOINT = -1         # behind, so the measurement stays crisp on top

_MARKERS_PER_TRACE = 22


def _marker_stride(n_points: int) -> int:
    """Draw a marker every Nth point so they never merge into a solid band."""
    return max(1, n_points // _MARKERS_PER_TRACE)


def _lighten(hex_colour: str, amount: float) -> str:
    """Blend a #rrggbb colour toward white. 0 = unchanged, 1 = white."""
    rgb = (int(hex_colour[1:3], 16), int(hex_colour[3:5], 16), int(hex_colour[5:7], 16))
    return "#{:02x}{:02x}{:02x}".format(
        *(int(round(c + (255 - c) * amount)) for c in rgb)
    )


def _assign_styles(manifest):
    """Map each manifest column to its Matplotlib drawing style."""
    groups = []
    for entry in manifest:
        group = entry.get("group") or entry["column"]
        if group not in groups:
            groups.append(group)

    seen_in_panel = {}   # (group, panel) -> measurement traces so far
    styles = {}
    for entry in manifest:
        group = entry.get("group") or entry["column"]
        group_idx = groups.index(group)
        colour = _PALETTE[group_idx % len(_PALETTE)]
        dashed = bool(entry.get("dashed"))

        if dashed:
            # A setpoint mirrors its measurement rather than being a channel in
            # its own right, so it does not consume a line style.
            channel_idx = 0
            line_style = "--"
            colour = _lighten(colour, _SETPOINT_TINT)
        else:
            key = (group, entry["panel"])
            channel_idx = seen_in_panel.get(key, 0)
            seen_in_panel[key] = channel_idx + 1
            line_style = _LINE_STYLES[channel_idx % len(_LINE_STYLES)]

        styles[entry["column"]] = {
            "hex": colour,
            "marker": _MARKERS[(group_idx + channel_idx) % len(_MARKERS)],
            "dashed": dashed,
            "line_style": line_style,
            "width": _WIDTH_SETPOINT if dashed else _WIDTH_MEASURED,
            "z": _Z_SETPOINT if dashed else _Z_MEASURED,
        }
    return styles


def save_experiment_plot(
    csv_path: Optional[str],
    step_times: list,
    logger,
    manifest: Optional[List[Dict]] = None,
) -> Optional[str]:
    """Render the experiment log to a PNG beside its CSV.

    ``manifest`` is the same series manifest the live plot uses
    (``Controller.build_series_manifest()``), so the saved figure mirrors the
    on-screen panels and legend labels for whatever devices were configured.
    """
    import matplotlib.dates as mdates
    import numpy as np
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
    # Same colour/marker assignment the live plot uses.
    styles = _assign_styles(manifest)

    def _to_float(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

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

    def _plot_series_with_smooth(ax, vals, label, style):
        """Raw (faint) + smoothed (bold) trace, matching the live plot's solids.

        The smoothed line carries the device's marker shape, thinned out the
        same way the live plot thins it, so the two read identically.
        """
        pairs = [(t, v) for t, v in zip(timestamps, vals) if v is not None]
        if not pairs:
            return
        ts, vs = zip(*pairs)
        vs_arr = list(vs)
        ax.plot(ts, vs_arr, color=style["hex"], linewidth=0.8, alpha=0.25)
        smoothed = _smooth(vs_arr)
        ax.plot(ts, smoothed, label=label, color=style["hex"],
                linewidth=style["width"], alpha=1.0,
                linestyle=style["line_style"],
                marker=style["marker"], markersize=5,
                markevery=_marker_stride(len(ts)),
                markeredgecolor="white", markeredgewidth=0.5,
                zorder=style["z"] + 2)

    def _plot_dashed(ax, vals, label, style):
        """Setpoint: same colour as its measurement, dashed and thinner."""
        pairs = [(t, v) for t, v in zip(timestamps, vals) if v is not None]
        if not pairs:
            return
        ts, vs = zip(*pairs)
        ax.plot(ts, list(vs), label=label, color=style["hex"],
                linewidth=style["width"], linestyle=style["line_style"],
                alpha=1.0, zorder=style["z"], solid_capstyle="butt")

    # One panel per registry panel that actually has series in this run.
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
            style = styles[entry["column"]]
            vals = columns[entry["column"]]
            if style["dashed"]:
                _plot_dashed(ax, vals, entry["label"], style)
            else:
                _plot_series_with_smooth(ax, vals, entry["label"], style)

        for st in step_times:
            ax.axvline(st, color="gray", linestyle="--", linewidth=0.7, alpha=0.6)

        ax.set_ylabel(y_label)
        ax.grid(True, alpha=0.3)
        if ax.get_legend_handles_labels()[0]:
            ax.legend(loc="upper right", fontsize=9, framealpha=0.85)

    axes[-1].set_xlabel("Time")
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    fig.autofmt_xdate()
    fig.tight_layout()

    plot_path = Path(csv_path).with_suffix(".png")
    fig.savefig(str(plot_path), dpi=150, bbox_inches="tight")
    print(f"Experiment plot saved: {plot_path}")
    return str(plot_path)
