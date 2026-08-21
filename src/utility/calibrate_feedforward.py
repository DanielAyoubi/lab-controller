"""Derive the RH feedforward calibration (``rh_ff_gain`` / ``rh_ff_offset``)
from a flow-mode ramp log.

The RH controller's feedforward assumes a static inverse plant map::

    wet_ratio = rh_ff_gain · (target_RH / 100) + rh_ff_offset

A **flow-mode** experiment steps the wet flow open-loop and holds at each step,
so the settled RH at each step is a clean ``(RH, wet_ratio)`` sample of that map.
This tool reads such a log, takes the settled tail of every step, and least-
squares fits the line — giving the two numbers to put in ``config.json``.

Usage::

    # latest RH_ramp_*.csv under data/, using the chiller-probe RH
    python -m src.utility.calibrate_feedforward

    # a specific log, hygrometer RH, and write the result back into config.json
    python -m src.utility.calibrate_feedforward data/.../RH_ramp_2026....csv --rh hygrometer --apply

Run this on a *flow-mode* ramp, not an rh-mode one: rh mode is already closed-loop
so its steady states reflect the old calibration, not the raw plant.
"""

import argparse
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# RH columns in priority order, matching what the controller tracks
# (Controller.current_rh prefers rh_chiller, then rh_hygrometer, then rh_probe).
# rh_probe is written when the RH source reports RH directly (a Vaisala); in
# that case rh_hygrometer is not logged at all, since it would be the same
# quantity derived a second time.
_RH_KEYS = {
    "chiller": "rh_chiller",
    "hygrometer": "rh_hygrometer",
    "probe": "rh_probe",
    "calibrated": "rh_chiller_calibrated",
}


def _to_float(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # reject NaN


def _wet_ratio(row: Dict[str, str]) -> Optional[float]:
    """Commanded wet ratio for a row, from setpoints (fall back to measured flow)."""
    for dry_key, wet_key in (
        ("dry_flow_setpoint", "wet_flow_setpoint"),
        ("dry_flow", "wet_flow"),
    ):
        dry, wet = _to_float(row.get(dry_key)), _to_float(row.get(wet_key))
        if dry is None or wet is None:
            continue
        total = dry + wet
        if total > 1e-6:
            return max(0.0, min(1.0, wet / total))
    return None


def _pick_rh_key(rows: List[Dict[str, str]], requested: str) -> str:
    """Resolve the RH column to use; 'auto' picks the best-populated one."""
    if requested != "auto":
        return _RH_KEYS[requested]
    best, best_n = _RH_KEYS["chiller"], -1
    for key in (_RH_KEYS["chiller"], _RH_KEYS["hygrometer"], _RH_KEYS["probe"]):
        n = sum(1 for r in rows if _to_float(r.get(key)) is not None)
        if n > best_n:
            best, best_n = key, n
    return best


def extract_settled_points(
    rows: List[Dict[str, str]],
    rh_key: str,
    settle_frac: float = 0.5,
    min_step_rows: int = 3,
    ratio_eps: float = 0.005,
) -> List[Tuple[float, float, int]]:
    """Average the settled tail of each open-loop flow step.

    Rows are grouped into steps by changes in the commanded wet ratio; for each
    step the last ``settle_frac`` of its rows (the equilibrated tail) are averaged.

    Returns a list of ``(rh, wet_ratio, n_rows_averaged)`` tuples.
    """
    # Annotate every row with its ratio + RH, dropping unusable rows.
    annotated = []
    for r in rows:
        ratio = _wet_ratio(r)
        rh = _to_float(r.get(rh_key))
        if ratio is not None and rh is not None:
            annotated.append((ratio, rh))
    if not annotated:
        return []

    # Split into contiguous steps wherever the commanded ratio changes.
    steps: List[List[Tuple[float, float]]] = []
    current = [annotated[0]]
    for ratio, rh in annotated[1:]:
        if abs(ratio - current[-1][0]) > ratio_eps:
            steps.append(current)
            current = []
        current.append((ratio, rh))
    steps.append(current)

    points: List[Tuple[float, float, int]] = []
    for step in steps:
        if len(step) < min_step_rows:
            continue
        tail = step[max(1, int(len(step) * (1.0 - settle_frac))):]
        if not tail:
            continue
        mean_ratio = sum(p[0] for p in tail) / len(tail)
        mean_rh = sum(p[1] for p in tail) / len(tail)
        points.append((mean_rh, mean_ratio, len(tail)))
    return points


def fit_feedforward(
    points: List[Tuple[float, float, int]]
) -> Optional[Dict[str, float]]:
    """Least-squares fit wet_ratio = gain·(RH/100) + offset.

    Returns a dict with ``gain``, ``offset``, ``r2`` and ``n`` — or None if the
    points do not span enough distinct RH values to define a line.
    """
    xs = [rh / 100.0 for rh, _, _ in points]
    ys = [ratio for _, ratio, _ in points]
    n = len(xs)
    if n < 2:
        return None

    sx, sy = sum(xs), sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    denom = n * sxx - sx * sx
    if abs(denom) < 1e-12:  # all RH roughly equal → no slope information
        return None

    gain = (n * sxy - sx * sy) / denom
    offset = (sy - gain * sx) / n

    mean_y = sy / n
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    ss_res = sum((y - (gain * x + offset)) ** 2 for x, y in zip(xs, ys))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 1.0

    return {"gain": gain, "offset": offset, "r2": r2, "n": n}


def calibrate_from_csv(
    csv_path: str,
    rh_source: str = "auto",
    settle_frac: float = 0.5,
) -> Optional[Dict]:
    """Read a flow-ramp CSV and return the feedforward fit + the points used."""
    import csv as _csv

    path = Path(csv_path)
    if not path.exists():
        print(f"Log file not found: {path}")
        return None

    with open(path, "r", newline="") as f:
        rows = list(_csv.DictReader(f))
    if not rows:
        print(f"Log file is empty: {path}")
        return None

    rh_key = _pick_rh_key(rows, rh_source)
    points = extract_settled_points(rows, rh_key, settle_frac=settle_frac)
    if len(points) < 2:
        print(
            f"Only {len(points)} settled step(s) found using '{rh_key}'. "
            "Need at least 2 distinct flow steps to fit — is this a flow-mode log?"
        )
        return None

    fit = fit_feedforward(points)
    if fit is None:
        print("Could not fit a line (RH values do not span a range).")
        return None

    fit.update(rh_key=rh_key, points=points, csv_path=str(path))
    return fit


def _latest_ramp_log(data_dir: str = "data") -> Optional[str]:
    """Most recently modified RH_ramp_*.csv anywhere under ``data_dir``."""
    candidates = sorted(
        Path(data_dir).rglob("RH_ramp_*.csv"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return str(candidates[0]) if candidates else None


def apply_to_config(config_path: str, gain: float, offset: float) -> bool:
    """In-place update the two feedforward keys in config.json, preserving the
    file's comments and formatting (only the numeric values are rewritten)."""
    path = Path(config_path)
    text = path.read_text(encoding="utf-8")
    updated = text
    for key, value in (("rh_ff_gain", gain), ("rh_ff_offset", offset)):
        pattern = rf'("{key}"\s*:\s*)(-?\d+(?:\.\d+)?)'
        repl = rf"\g<1>{value:.4f}"
        updated, n = re.subn(pattern, repl, updated, count=1)
        if n == 0:
            print(f"  ! '{key}' not found in {path} — left unchanged.")
            return False
    if updated != text:
        path.write_text(updated, encoding="utf-8")
    return True


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "csv", nargs="?", help="Flow-ramp CSV (default: latest RH_ramp_*.csv under data/)"
    )
    parser.add_argument(
        "--rh", choices=["auto", "chiller", "hygrometer", "probe", "calibrated"],
        default="auto",
        help="Which RH column to calibrate against (default: auto)",
    )
    parser.add_argument(
        "--settle-frac", type=float, default=0.5,
        help="Fraction of each step's tail to average as 'settled' (default: 0.5)",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Write the result back into src/configs/config.json",
    )
    args = parser.parse_args(argv)

    csv_path = args.csv or _latest_ramp_log()
    if not csv_path:
        print("No CSV given and no RH_ramp_*.csv found under data/.")
        return 1

    result = calibrate_from_csv(csv_path, rh_source=args.rh, settle_frac=args.settle_frac)
    if result is None:
        return 1

    print(f"\nFeedforward calibration from: {result['csv_path']}")
    print(f"RH source: {result['rh_key']}   |   {result['n']} settled steps\n")
    print(f"  {'RH (%)':>8}  {'wet_ratio':>9}  {'rows':>5}")
    for rh, ratio, n in result["points"]:
        print(f"  {rh:8.2f}  {ratio:9.4f}  {n:5d}")

    gain, offset, r2 = result["gain"], result["offset"], result["r2"]
    print(f"\n  Fit:  wet_ratio = {gain:.4f}·(RH/100) + {offset:+.4f}     R² = {r2:.4f}")
    print("\n  Suggested config.json values:")
    print(f'    "rh_ff_gain": {gain:.4f},')
    print(f'    "rh_ff_offset": {offset:.4f},')

    if r2 < 0.95:
        print(f"\n  ! R² = {r2:.3f} is low — data may be noisy or not fully settled.")
    if not (0.5 <= gain <= 1.6):
        print(f"\n  ! gain {gain:.3f} is far from the ~1.0 the physics predicts — sanity-check the log.")

    if args.apply:
        cfg = Path(__file__).resolve().parents[1] / "configs" / "config.json"
        if apply_to_config(str(cfg), gain, offset):
            print(f"\n  Wrote rh_ff_gain / rh_ff_offset to {cfg}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
