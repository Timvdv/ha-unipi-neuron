EVOK_INPUT_DEVICE_TYPES = ("input", "di")
# EVOK v2 reports digital inputs as "input"; EVOK v3 uses "di".


def detect_input_device_types(cache):
    """Detect EVOK input device types from cached /rest/all data."""
    first_key = next(iter(cache), None)
    if first_key:
        first_device = first_key[0]
        if first_device in EVOK_INPUT_DEVICE_TYPES:
            return (first_device,)
    for (device, _), _ in cache.items():
        if device in EVOK_INPUT_DEVICE_TYPES:
            return (device,)
    return EVOK_INPUT_DEVICE_TYPES
