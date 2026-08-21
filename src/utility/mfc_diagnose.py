"""Talk to a configured MFC directly and report what it actually does.

When a flow reading looks wrong, the question is always the same: is the app
sending the wrong number, or is the device not doing what it was told? This
answers that by bypassing the controller, the GUI and the poll loop entirely —
it opens the MFC from ``config.json`` and reads its registers itself.

Read-only by default::

    .venv\\Scripts\\python -m src.utility.mfc_diagnose

With ``--sweep`` it also *writes* a series of setpoints and reads each one back,
which is what distinguishes "the setpoint never arrived" from "the device
clamped it" from "the device accepted it but the flow does not follow"::

    .venv\\Scripts\\python -m src.utility.mfc_diagnose --device dry_mfc --sweep

``--sweep`` moves real gas. It restores the setpoint it found on entry when it
finishes (including on Ctrl-C).
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from src.devices import registry as reg

_DEFAULT_SWEEP = [0.0, 0.25, 0.5, 1.0, 1.5, 2.0]


def _strip_json_comments(text: str) -> str:
    """Mirror of MainWindow._strip_json_comments, without the Qt dependency."""
    out = []
    i, n = 0, len(text)
    in_string = escape = False
    while i < n:
        c = text[i]
        if in_string:
            out.append(c)
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_string = False
            i += 1
        elif c == '"':
            in_string = True
            out.append(c)
            i += 1
        elif c == "/" and i + 1 < n and text[i + 1] == "/":
            i += 2
            while i < n and text[i] not in "\r\n":
                i += 1
        elif c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def load_config(path: Optional[str] = None) -> dict:
    cfg_path = Path(path) if path else (
        Path(__file__).resolve().parents[1] / "configs" / "config.json"
    )
    return json.loads(_strip_json_comments(cfg_path.read_text(encoding="utf-8")))


def mfc_specs(config: dict, only: Optional[str] = None) -> List[dict]:
    """Enabled MFC specs, optionally narrowed to one id or tag."""
    specs = [
        s for s in reg.enabled_specs(config.get("devices", []))
        if "flow_setpoint" in reg.require_type(s).caps
    ]
    if only:
        needle = only.lower()
        specs = [s for s in specs
                 if needle in (s["id"].lower(), s.get("tag", "").lower())]
    return specs


def _read_all(mfc) -> Dict[str, Optional[float]]:
    """Every register the driver knows, each failing independently."""
    out: Dict[str, Optional[float]] = {}
    for name, getter in (
        ("flow", mfc.get_flow),
        ("setpoint", mfc.get_setpoint),
        ("temperature", mfc.get_temperature),
        ("valve", mfc.get_valve_signal),
    ):
        try:
            out[name] = getter()
        except Exception as e:
            out[name] = None
            print(f"    ! reading {name} failed: {e}")
    return out


def _fmt(v: Optional[float]) -> str:
    return f"{v:8.3f}" if isinstance(v, (int, float)) else "       —"


def inspect(spec: dict, sweep: bool, settle: float,
            points: List[float]) -> None:
    dtype = reg.require_type(spec)
    tag = spec.get("tag", spec["id"])
    print(f"\n=== {tag}  (id={spec['id']}, {spec.get('port')}, "
          f"address {spec.get('address')}) ===")

    mfc = dtype.factory(spec)
    if not mfc.connect():
        print("  Could not connect — is the port right and the device powered?")
        return

    try:
        initial = _read_all(mfc)
        print(f"  as found:  flow={_fmt(initial['flow'])}  "
              f"setpoint={_fmt(initial['setpoint'])}  "
              f"temp={_fmt(initial['temperature'])}  "
              f"valve={_fmt(initial['valve'])}")

        if not sweep:
            print("  (read-only; pass --sweep to write test setpoints)")
            return

        restore = initial["setpoint"] if initial["setpoint"] is not None else 0.0
        print(f"\n  Writing setpoints, {settle:.0f}s settle each. "
              f"Will restore {restore:.3f} at the end.\n")
        print("    commanded   readback      flow     valve")
        try:
            for target in points:
                mfc.set_flow(target)
                time.sleep(settle)
                r = _read_all(mfc)
                flag = ""
                if r["setpoint"] is not None and abs(r["setpoint"] - target) > 0.02:
                    flag = "  <-- readback differs from commanded"
                print(f"    {target:8.3f}  {_fmt(r['setpoint'])}  "
                      f"{_fmt(r['flow'])}  {_fmt(r['valve'])}{flag}")
        finally:
            mfc.set_flow(restore)
            print(f"\n  Restored setpoint to {restore:.3f}.")
    finally:
        mfc.disconnect()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Read (and optionally exercise) the configured MFCs."
    )
    parser.add_argument("--config", help="Path to config.json")
    parser.add_argument("--device", help="Only this device (id or tag)")
    parser.add_argument("--sweep", action="store_true",
                        help="Write test setpoints and read each one back "
                             "(moves real gas)")
    parser.add_argument("--settle", type=float, default=4.0,
                        help="Seconds to wait after each write (default 4)")
    parser.add_argument("--points", default=",".join(str(p) for p in _DEFAULT_SWEEP),
                        help="Comma-separated setpoints for --sweep")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    specs = mfc_specs(config, args.device)
    if not specs:
        print("No enabled MFC matched." if args.device
              else "No enabled MFCs in config.json.")
        return 1

    try:
        points = [float(p) for p in re.split(r"[,\s]+", args.points) if p]
    except ValueError:
        print(f"Could not parse --points {args.points!r}")
        return 1

    for spec in specs:
        inspect(spec, args.sweep, args.settle, points)
    return 0


if __name__ == "__main__":
    sys.exit(main())
