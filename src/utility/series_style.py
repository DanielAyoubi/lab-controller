"""Visual identity for plotted series — shared by the live plot and the PNG.

The problem this solves: with a dozen traces spread over three panels, telling
which line is which is hard if every series simply takes the next colour. So
colour is assigned **per group** (a device) rather than per series:

* every channel of one device shares that device's colour, in every panel it
  appears in — the wet MFC is the same colour in the flow panel as its
  temperature would be in the temperature panel;
* within a device, a setpoint is a pale, wider halo of its measurement's colour
  drawn behind it, which reads as "the commanded version of that line" instead
  of as an unrelated quantity;
* each device also gets a distinct marker shape, so traces stay separable when
  there are more devices than palette colours, and the legend sample shows that
  shape next to the label.

Both renderers import this module so the saved figure matches the screen.
"""

from typing import Any, Dict, List

# Colour-blind-friendly ordering: blue / orange / green / red first, since a
# typical rig has few devices and those four are the most distinguishable pairs.
PALETTE = [
    (31, 119, 180),   # blue
    (255, 127, 14),   # orange
    (44, 160, 44),    # green
    (214, 39, 40),    # red
    (148, 103, 189),  # purple
    (23, 190, 207),   # cyan
    (227, 119, 194),  # pink
    (140, 86, 75),    # brown
    (188, 189, 34),   # olive
    (127, 127, 127),  # grey
]

# pyqtgraph symbol codes, chosen to stay legible at ~7 px.
SYMBOLS = ["o", "s", "t", "d", "p", "h", "star", "t1"]

# Line styles for a device's *measurement* channels that land in the same panel
# — a probe contributes both Temp and Dewpoint to the temperature panel, and
# sharing the device colour would otherwise make them one indistinguishable
# pair. "dashed" is reserved: it always and only means a setpoint.
LINE_STYLES = ["solid", "dashdot", "dot"]
MPL_LINESTYLES = {"solid": "-", "dashdot": "-.", "dot": ":", "dashed": "--"}

# The same shapes for Matplotlib, so the saved PNG matches the live plot.
MPL_MARKERS = {
    "o": "o", "s": "s", "t": "v", "d": "D",
    "p": "p", "h": "h", "star": "*", "t1": "^",
}

# A setpoint is usually *equal* to its measurement — an MFC sits on its
# commanded flow — so drawing it in the same colour at the same width simply
# hides it under the measurement and the trace silently disappears. Instead it
# is drawn as a pale, wider halo *behind* the measurement: where the two agree
# you see a soft band hugging the line, and where they diverge the halo pulls
# away and is obvious.
WIDTH_MEASURED = 2.2
WIDTH_SETPOINT = 5.0
SETPOINT_TINT = 0.6      # how far to blend the device colour toward white
Z_MEASURED = 1
Z_SETPOINT = -1          # behind, so the measurement stays crisp on top

# Roughly how many markers to draw along a trace. Enough to identify the shape,
# few enough that they never merge into a band and hide the line's colour.
MARKERS_PER_TRACE = 22
SYMBOL_SIZE = 7.0


def _lighten(rgb, amount: float):
    """Blend a colour toward white. 0 = unchanged, 1 = white."""
    return tuple(int(round(c + (255 - c) * amount)) for c in rgb)


def _groups_in_order(manifest: List[Dict[str, Any]]) -> List[str]:
    """Distinct groups, in the order they first appear (i.e. config order)."""
    groups: List[str] = []
    for entry in manifest:
        group = entry.get("group") or entry["column"]
        if group not in groups:
            groups.append(group)
    return groups


def assign_styles(manifest: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Map each manifest column to its drawing style.

    Colour comes from the group (the device) and is shared by all its channels
    in every panel. Where one device puts several *measurements* in the same
    panel, those are separated by line style and marker shape, so the shared
    colour still reads as "these belong to the same instrument" without the
    traces becoming interchangeable.
    """
    groups = _groups_in_order(manifest)
    # How many measurement traces this group already has in this panel.
    seen_in_panel: Dict[Any, int] = {}

    styles: Dict[str, Dict[str, Any]] = {}
    for entry in manifest:
        group = entry.get("group") or entry["column"]
        group_idx = groups.index(group)
        rgb = PALETTE[group_idx % len(PALETTE)]
        dashed = bool(entry.get("dashed"))

        if dashed:
            # A setpoint mirrors its measurement rather than being a channel
            # in its own right, so it does not consume a line style.
            channel_idx = 0
            line_style = "dashed"
        else:
            key = (group, entry["panel"])
            channel_idx = seen_in_panel.get(key, 0)
            seen_in_panel[key] = channel_idx + 1
            line_style = LINE_STYLES[channel_idx % len(LINE_STYLES)]

        symbol = SYMBOLS[(group_idx + channel_idx) % len(SYMBOLS)]
        draw_rgb = _lighten(rgb, SETPOINT_TINT) if dashed else rgb
        styles[entry["column"]] = {
            "rgb": draw_rgb,                       # colour actually drawn
            "hex": "#{:02x}{:02x}{:02x}".format(*draw_rgb),
            "device_rgb": rgb,                     # the group's identity colour
            "symbol": symbol,
            "mpl_marker": MPL_MARKERS[symbol],
            "dashed": dashed,
            "line_style": line_style,
            "mpl_linestyle": MPL_LINESTYLES[line_style],
            "width": WIDTH_SETPOINT if dashed else WIDTH_MEASURED,
            "z": Z_SETPOINT if dashed else Z_MEASURED,
        }
    return styles


def marker_stride(n_points: int) -> int:
    """Draw a marker every Nth point so they never merge into a solid band."""
    return max(1, n_points // MARKERS_PER_TRACE)
