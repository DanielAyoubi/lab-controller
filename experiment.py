import csv
from datetime import datetime

from matplotlib.figure import Figure


def humidity_cycle(humid_mfc, dry_mfc, total_flow, low, high, step, hold_minutes, cycles,
                   start_high=False):
    rising = []
    i = 0
    while round(low + i * step, 6) < high:
        rising.append(round(low + i * step, 6))
        i += 1
    rising.append(high)
    # A reverse ramp runs the same levels from the top down.
    ramp = rising[::-1] if start_high else rising
    # Out, then back without repeating the two end levels.
    one_cycle = ramp + ramp[-2:0:-1]
    levels = one_cycle * cycles + [ramp[0]]

    steps = []
    for level in levels:
        humid_flow = round(total_flow * level / 100, 4)
        dry_flow = round(total_flow - humid_flow, 4)
        steps.append({
            "minutes": hold_minutes,
            "setpoints": {(humid_mfc, "flow"): humid_flow, (dry_mfc, "flow"): dry_flow},
        })
    return steps


def save_summary_plot(csv_path, units):
    with open(csv_path, newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    if not rows:
        return None

    columns_by_unit = {}
    for column, unit in units.items():
        columns_by_unit.setdefault(unit, []).append(column)

    times = [datetime.fromisoformat(row["time"]) for row in rows]
    figure = Figure(figsize=(10, 3 * len(columns_by_unit)), layout="constrained")
    axes = figure.subplots(len(columns_by_unit), 1, sharex=True, squeeze=False)[:, 0]
    for ax, (unit, columns) in zip(axes, columns_by_unit.items()):
        for column in columns:
            values = [float(row[column]) if row[column] else float("nan") for row in rows]
            style = "--" if column.endswith("setpoint") else "-"
            ax.plot(times, values, style, label=column)
        ax.set_ylabel(unit)
        ax.legend(fontsize="small")

    png_path = csv_path[:-4] + ".png"
    figure.savefig(png_path, dpi=120)
    return png_path
