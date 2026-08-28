"""Find instruments on serial ports so the user does not have to type them in.

Two jobs, both driven entirely by the ``Discovery`` descriptors in
:mod:`src.devices.registry` — adding a new instrument still means a driver plus
one registry entry, with nothing to change here:

* :func:`list_serial_ports` — what the port dropdowns in Settings offer.
* :func:`plan` / :func:`run` — probe a set of ports and report what answered.

**Every probe is read-only.** They are the same handshakes each driver's
``connect()`` already performs to verify a device is powered on (a Modbus
register read, ``P``, ``version``, ``#LOGO``), just with shorter timeouts and,
for the two Modbus types, without reopening the port for every address.

The scan is a **cheapest-probe-first sweep with early exit**: a serial port
carries one instrument (or one RS-485 bus of identical instruments), so the
moment something answers on a port the remaining probes for that port are
skipped. That ordering falls straight out of sorting steps by their estimated
cost — the sub-second default-address checks run first, the multi-second ASCII
handshakes next, and the 247-address Modbus sweep last, where it is usually
never reached at all.
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from serial.tools import list_ports

from src.devices import registry as reg


# ── Ports ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SerialPort:
    """One COM port as the OS reports it."""
    device: str
    description: str

    @property
    def label(self) -> str:
        """What the dropdown shows: the port plus enough to recognise the cable."""
        if not self.description or self.description.lower() == "n/a":
            return self.device
        return f"{self.device} — {self.description}"


def list_serial_ports() -> List[SerialPort]:
    """Serial ports currently present, in natural COM order.

    Sorted numerically so COM9 precedes COM10; pyserial's own sort is
    lexicographic and would not.
    """
    ports = []
    for info in list_ports.comports():
        ports.append(SerialPort(info.device, (info.description or "").strip()))

    def key(p: SerialPort):
        digits = "".join(c for c in p.device if c.isdigit())
        return (int(digits) if digits else 0, p.device)

    return sorted(ports, key=key)


def port_names() -> List[str]:
    return [p.device for p in list_serial_ports()]


# ── What a scan finds ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Found:
    """One instrument that answered, ready to become a device spec."""
    type_key: str
    port: str
    baudrate: int
    address: Optional[int] = None

    @property
    def label(self) -> str:
        dtype = reg.DEVICE_TYPES[self.type_key]
        detail = f"{self.baudrate} baud"
        if self.address is not None:
            detail = f"address {self.address}, {detail}"
        return f"{self.port} — {dtype.label} ({detail})"

    def spec_updates(self) -> Dict:
        """Connection fields this discovery can fill in on a device spec."""
        updates = {"port": self.port, "baudrate": self.baudrate}
        key = reg.DEVICE_TYPES[self.type_key].discovery.address_key
        if key and self.address is not None:
            updates[key] = self.address
        return updates

    def matches(self, spec: Dict) -> bool:
        """True when ``spec`` already describes this exact instrument."""
        if spec.get("type") != self.type_key or spec.get("port") != self.port:
            return False
        key = reg.DEVICE_TYPES[self.type_key].discovery.address_key
        if key is None:
            return True
        return int(spec.get(key, -1)) == self.address


# ── Planning ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Step:
    """One probe call: one type, on one port, over one list of addresses."""
    port: str
    type_key: str
    addresses: Tuple[Optional[int], ...]

    @property
    def cost(self) -> float:
        spp = reg.DEVICE_TYPES[self.type_key].discovery.seconds_per_probe
        return len(self.addresses) * spp

    @property
    def units(self) -> int:
        return len(self.addresses)


@dataclass
class Plan:
    """An ordered scan, grouped by port so a hit can skip the rest of that port."""
    by_port: Dict[str, List[Step]] = field(default_factory=dict)

    @property
    def total_units(self) -> int:
        return sum(s.units for steps in self.by_port.values() for s in steps)

    @property
    def estimated_seconds(self) -> float:
        """Worst case — every port silent, so no step is ever skipped."""
        return sum(s.cost for steps in self.by_port.values() for s in steps)


def known_addresses(specs: Sequence[Dict], type_key: str) -> Tuple[int, ...]:
    """Addresses this type already uses in the user's config.

    Tried before the factory default: a rig that has been renumbered once tends
    to stay renumbered, so the addresses already on file are the best guess
    available and cost nothing to check first.
    """
    key = reg.DEVICE_TYPES[type_key].discovery.address_key
    if key is None:
        return ()
    out = []
    for spec in specs or []:
        if spec.get("type") == type_key and spec.get(key) is not None:
            try:
                value = int(spec[key])
            except (TypeError, ValueError):
                continue
            if value not in out:
                out.append(value)
    return tuple(out)


def plan(ports: Sequence[str], deep: bool = False,
         specs: Optional[Sequence[Dict]] = None,
         type_keys: Optional[Sequence[str]] = None) -> Plan:
    """Build the ordered probe list for ``ports``.

    An addressed type contributes up to two steps: its likely addresses, and —
    in a deep scan — everything else. They are separate steps so the sort below
    puts the cheap check near the front and the exhaustive sweep at the very
    back, behind every other type's handshake.
    """
    keys = list(type_keys) if type_keys is not None else list(reg.DEVICE_TYPES)
    result = Plan()

    for port in ports:
        steps: List[Step] = []
        for type_key in keys:
            disc = reg.DEVICE_TYPES[type_key].discovery
            if disc is None:
                continue
            likely = disc.addresses(False, known_addresses(specs or [], type_key))
            steps.append(Step(port, type_key, likely))
            if deep and disc.address_key is not None:
                rest = tuple(a for a in disc.addresses(True) if a not in likely)
                if rest:
                    steps.append(Step(port, type_key, rest))
        result.by_port[port] = sorted(steps, key=lambda s: s.cost)

    return result


# ── Running ───────────────────────────────────────────────────────────────────

def run(scan_plan: Plan,
        on_found: Optional[Callable[[Found], None]] = None,
        on_progress: Optional[Callable[[int, str], None]] = None,
        should_stop: Optional[Callable[[], bool]] = None,
        skip_ports: Sequence[str] = ()) -> List[Found]:
    """Execute ``scan_plan`` and return everything that answered.

    ``on_progress`` receives (units completed, status line) and is called often
    enough to drive a determinate progress bar: skipped work is reported too,
    so the bar always reaches its maximum even when early exit does most of the
    job. Ports in ``skip_ports`` are not touched at all — that is how a port
    held open by a live driver is kept out of the scan.
    """
    done = 0
    results: List[Found] = []
    skip = set(skip_ports)

    def report(message: str):
        if on_progress:
            on_progress(done, message)

    for port, steps in scan_plan.by_port.items():
        port_units = sum(s.units for s in steps)

        if port in skip:
            done += port_units
            report(f"{port}: in use, skipped")
            continue

        hit = False
        for step in steps:
            stopped = bool(should_stop and should_stop())
            if hit or stopped:
                # Nothing more to learn from this port (or the user cancelled),
                # but the bar still has to account for the work not done.
                done += step.units
                report(f"{port}: skipped" if hit else "Cancelling…")
                continue

            dtype = reg.DEVICE_TYPES[step.type_key]
            report(f"{port}: looking for {dtype.label}…")

            def tick():
                nonlocal done
                done += 1
                if done % 8 == 0:
                    report(f"{port}: looking for {dtype.label}…")

            try:
                answered = dtype.discovery.scan(
                    port, dtype.discovery.baudrate, step.addresses,
                    should_stop=should_stop, on_probe=tick,
                )
            except Exception as e:
                print(f"Scan error on {port} for {dtype.label}: {e}")
                answered = []

            # A probe that bailed out early (cancel) leaves units unaccounted.
            done = min(done, scan_plan.total_units)

            for address in answered:
                found = Found(step.type_key, port, dtype.discovery.baudrate, address)
                results.append(found)
                hit = True
                report(f"Found {found.label}")
                if on_found:
                    on_found(found)

        if not hit and not (should_stop and should_stop()):
            report(f"{port}: nothing found")

    report("Scan complete.")
    return results
