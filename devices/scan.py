from devices import DEVICE_TYPES

# A Modbus reply arrives within milliseconds, so silent addresses can be skipped quickly.
# The ASCII instruments keep their own timeouts, because some only answer after a measurement.
MODBUS_TIMEOUT = 0.15


def scan(ports, deep, known_addresses, on_progress):
    """Look for known devices on each of `ports`.
    A quick scan tries each type's default address plus `known_addresses`. A deep scan also
    sweeps Modbus addresses 1-247. `on_progress(port_number, text)` returns False to cancel.
    Returns a list of device dicts without names.
    """
    found = []
    for port_number, port in enumerate(ports):
        port_has_device = False
        for type_key, device_class in DEVICE_TYPES.items():
            if port_has_device:
                break

            if "address" in device_class.settings:
                addresses = [device_class.settings["address"]] + known_addresses
                if deep:
                    addresses += list(range(1, 248))
                addresses = list(dict.fromkeys(addresses))  # drop duplicates, keep order
            else:
                addresses = [None]

            for address in addresses:
                text = f"{port}: looking for {device_class.label}"
                if address is not None:
                    text += f" at address {address}"
                if not on_progress(port_number, text):
                    return found

                settings = dict(device_class.settings)
                settings["port"] = port
                if address is None:
                    device = device_class(**settings)
                else:
                    settings["address"] = address
                    device = device_class(**settings, timeout=MODBUS_TIMEOUT)
                try:
                    device.connect()
                    device.disconnect()
                except Exception:
                    continue
                found.append({"type": type_key, **settings})
                port_has_device = True
                if not deep:
                    break
    return found
