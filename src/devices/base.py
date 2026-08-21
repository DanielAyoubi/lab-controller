"""Uniform device interface.

Every driver in this package exposes the same four methods so the controller can
drive an arbitrary, user-declared set of devices without knowing any concrete
class. Anything device-specific (register maps, ASCII command sets, nudging
loops) stays inside the driver.

Optional abilities are probed by *capability*, not by class — see
``registry.DeviceType.caps``:

    "flow_setpoint"  -> driver has ``set_flow(value) -> bool``
    "temp_setpoint"  -> driver has ``set_temperature(value)`` and
                        ``start_control()`` / ``stop_control()``
"""

from typing import Dict, Optional, Protocol, runtime_checkable


@runtime_checkable
class Device(Protocol):
    """Structural interface implemented by every driver."""

    name: str

    def connect(self) -> bool:
        """Open the port and verify the device actually answers.

        Returns True only when a real reading/echo was obtained — opening a
        USB-serial adapter succeeds even with the instrument powered off.
        """
        ...

    def disconnect(self) -> None:
        ...

    def is_connected(self) -> bool:
        ...

    def read(self) -> Optional[Dict[str, float]]:
        """One poll, returned as ``{channel_key: value}``.

        Channel keys must match the ``Channel.key`` values declared for this
        device type in :mod:`src.devices.registry`. Returns ``None`` (or an
        empty dict) when the device is reachable but produced no reading — the
        controller treats that as unhealthy, same as an exception.
        """
        ...
