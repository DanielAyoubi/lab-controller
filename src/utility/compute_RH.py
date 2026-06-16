import math
from typing import Literal

Method = Literal["magnus", "buck", "lawrence"]


def calibrated_RH(RH: float):
    """
    Correction of the RH values (obtained using the external temperature sensor) to the real RH inside the cell. 
    Calibration performed on deliquescence of pure salts. Version of fit parameters: 09 June 2026
    ----- Input
    RH (%): float
    ----- Output
    RH (%): float
    """
    a = 0.9641
    b = 1.2871
    return a*RH + b
    

def compute_relative_humidity(
    dp: float,
    t: float,
    method: Method = "magnus",
) -> float:
    """Compute relative humidity from dew point and ambient temperature.

    Args:
        dp:     Dew point temperature (°C).
        t:      Ambient temperature (°C).
        method: Computation method. One of:

                - ``"magnus"`` (default) — Magnus (1883) equation.  Valid −40 to 60 °C.
                - ``"buck"`` — Buck (1981) equation. Temperature range (−40 to 50 °C).
                - ``"lawrence"`` — Lawrence (2005) linear approximation.
                  RH ≈ 100 − 5·(T − Td).  Fast and simple; error ≈ ±1.5 %
                  for T ∈ [20, 50] °C.  Good as a sanity check.

    Returns:
        RH in percent [0, 100], or ``float('nan')`` on error.
    """
    if method == "magnus":
        return _magnus(dp, t)
    if method == "buck":
        return _buck(dp, t)
    if method == "lawrence":
        return _lawrence(dp, t)
    raise ValueError(f"Unknown RH method: {method!r}")


# ── Implementations ───────────────────────────────────────────────────────────

def _magnus(dp: float, t: float) -> float:
    """Magnus formula: RH = 100 · exp(a·dp/(b+dp)) / exp(a·t/(b+t))."""
    a = 17.625
    b = 243.04
    try:
        if dp >= t:
            return 100.0
        num = math.exp(a * dp / (b + dp))
        den = math.exp(a * t / (b + t))
        val = 100.0 * num / den
        return max(0.0, min(100.0, val)) if math.isfinite(val) else float("nan")
    except Exception:
        return float("nan")


def _buck(dp: float, t: float) -> float:
    """Buck (1981) enhanced Magnus equation over liquid water.
    Uses Buck's enhanced coefficients which account for the variation of
    the enthalpy of vaporisation with temperature, giving better accuracy
    than plain Magnus variants across a wide range.
    """
    a = 18.678
    b = 234.5
    c = 257.14
    try:
        if dp >= t:
            return 100.0
        e_s = math.exp((a - t / b) * (t / (c + t)))
        e_d = math.exp((a - dp / b) * (dp / (c + dp)))
        val = 100.0 * e_d / e_s
        return max(0.0, min(100.0, val)) if math.isfinite(val) else float("nan")
    except Exception:
        return float("nan")


def _lawrence(dp: float, t: float) -> float:
    """Lawrence (2005) linear approximation: RH ≈ 100 − 5·(T − Td).
    Simple rule-of-thumb valid for T ∈ [20, 50] °C with ≈ ±1.5 % error.
    """
    try:
        val = 100.0 - 5.0 * (t - dp)
        return max(0.0, min(100.0, val))
    except Exception:
        return float("nan")
