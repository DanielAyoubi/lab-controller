import math


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


def compute_relative_humidity(dp: float, t: float) -> float:
    """Compute relative humidity from dew point and ambient temperature.

    Uses the Magnus (1883) equation, valid from −40 to 60 °C::

        RH = 100 · exp(a·dp/(b+dp)) / exp(a·t/(b+t))

    Args:
        dp: Dew point temperature (°C).
        t:  Ambient temperature (°C).

    Returns:
        RH in percent [0, 100], or ``float('nan')`` on error.
    """
    a = 17.625
    b = 243.04
    try:
        if dp >= t:
            return 100.0
        val = 100.0 * math.exp(a * dp / (b + dp)) / math.exp(a * t / (b + t))
        return max(0.0, min(100.0, val)) if math.isfinite(val) else float("nan")
    except Exception:
        return float("nan")
