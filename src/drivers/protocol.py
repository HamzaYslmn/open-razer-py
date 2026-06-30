"""Razer USB-HID protocol: build reports that set a color or run an on-device effect.

Platform independent -- the transport lives in `transport`. `build(method, action,
rgb, txn, led, store)` returns the report sequence for one action; `store=True`
(VARSTORE) asks the device to keep the setting in its onboard memory, `store=False`
(NOSTORE) is volatile.
"""

# LED ids
ZERO_LED, SCROLL_WHEEL_LED, LOGO_LED, BACKLIGHT_LED = 0x00, 0x01, 0x04, 0x05
VARSTORE, NOSTORE, ON, OFF = 0x01, 0x00, 0x01, 0x00

ACTIONS = ("static", "off", "spectrum", "breathing", "wave")
METHODS = ("ext_static", "std_static", "custom", "logo")


def razer_report(command_class, command_id, data_size, arguments, txn):
    """One 90-byte Razer report. `arguments` start at byte 8 (= arguments[0])."""
    r = bytearray(90)
    r[1] = txn
    r[5] = data_size
    r[6] = command_class
    r[7] = command_id
    r[8:8 + len(arguments)] = arguments
    crc = 0
    for i in range(2, 88):          # CRC = XOR of bytes 2..87, stored at byte 88
        crc ^= r[i]
    r[88] = crc
    return bytes(r)


# --- extended matrix (cmd 0x0F/0x02; args[0]=store, [1]=led, [2]=effect) -----
def _ext_static(rgb, txn, led, sv):
    a = bytearray(9)
    a[0], a[1], a[2], a[5] = sv, led, 0x01, 0x01
    a[6], a[7], a[8] = rgb
    return [razer_report(0x0F, 0x02, 0x09, a, txn)]


def _ext_simple(effect, txn, led, sv):
    a = bytearray(3)
    a[0], a[1], a[2] = sv, led, effect
    return [razer_report(0x0F, 0x02, 0x06, a, txn)]


def _ext_breathing(rgb, txn, led, sv):
    if rgb and any(rgb):                          # breathe one chosen color
        a = bytearray(9)
        a[0], a[1], a[2], a[3], a[5] = sv, led, 0x02, 0x01, 0x01
        a[6], a[7], a[8] = rgb
        return [razer_report(0x0F, 0x02, 0x09, a, txn)]
    return _ext_simple(0x02, txn, led, sv)        # random


def _ext_wave(rgb, txn, led, sv):
    a = bytearray(4)
    a[0], a[1], a[2], a[3] = sv, led, 0x04, 0x01  # direction 0x01
    return [razer_report(0x0F, 0x02, 0x06, a, txn)]


# --- custom frame (the Viper Mini static path) -------------------------------
def _custom_static(rgb, txn, led, sv):
    frame = bytearray(8)
    frame[5], frame[6], frame[7] = rgb            # row/start/stop cols stay 0
    show = bytearray(3)
    show[2] = 0x08
    return [razer_report(0x0F, 0x03, 0x47, frame, txn),
            razer_report(0x0F, 0x02, 0x0C, show, txn)]


# --- standard matrix (cmd 0x03/0x0A; args[0]=effect id) ----------------------
def _std_static(rgb, txn, led, sv):
    a = bytearray(4)
    a[0] = 0x06                                    # MATRIX_EFFECT_STATIC
    a[1], a[2], a[3] = rgb
    return [razer_report(0x03, 0x0A, 0x04, a, txn)]


def _std_simple(effect, txn):
    return [razer_report(0x03, 0x0A, 0x01, bytes([effect]), txn)]


def _std_wave(rgb, txn, led, sv):
    return [razer_report(0x03, 0x0A, 0x02, bytes([0x01, 0x01]), txn)]  # WAVE, dir 1


# --- standard LED / logo (CLASSIC effects via set_led_effect) ----------------
def _logo_static(rgb, txn, led, sv):
    led = led or LOGO_LED
    rgb_a = bytearray([sv, led, rgb[0], rgb[1], rgb[2]])
    return [razer_report(0x03, 0x01, 0x05, rgb_a, txn),
            razer_report(0x03, 0x02, 0x03, bytes([sv, led, 0x00]), txn),   # CLASSIC static
            razer_report(0x03, 0x00, 0x03, bytes([sv, led, ON]), txn)]


def _logo_effect(effect, txn, led, sv):
    led = led or LOGO_LED
    return [razer_report(0x03, 0x02, 0x03, bytes([sv, led, effect]), txn),
            razer_report(0x03, 0x00, 0x03, bytes([sv, led, ON]), txn)]


def _logo_off(txn, led, sv):
    led = led or LOGO_LED
    return [razer_report(0x03, 0x00, 0x03, bytes([sv, led, OFF]), txn)]


# 'custom' static uses the VARSTORE extended-matrix static so the color is stored
# on-device -- the old custom-frame (_custom_static) was volatile.
_STATIC = {"ext_static": _ext_static, "std_static": _std_static,
           "custom": _ext_static, "logo": _logo_static}

# animation family per method. custom mice (e.g. Viper Mini) animate through the
# extended-matrix effects on their logo LED -- NOT the standard 0x03 LED commands.
_FAMILY = {"ext_static": "ext", "std_static": "std", "custom": "ext", "logo": "logo"}

_ANIM = {
    "ext": {"off": lambda r, t, l, s: _ext_simple(0x00, t, l, s),
            "spectrum": lambda r, t, l, s: _ext_simple(0x03, t, l, s),
            "breathing": _ext_breathing, "wave": _ext_wave},
    "std": {"off": lambda r, t, l, s: _std_simple(0x00, t),
            "spectrum": lambda r, t, l, s: _std_simple(0x04, t),
            "breathing": lambda r, t, l, s: _std_simple(0x03, t), "wave": _std_wave},
    "logo": {"off": lambda r, t, l, s: _logo_off(t, l, s),
             "spectrum": lambda r, t, l, s: _logo_effect(0x04, t, l, s),
             "breathing": lambda r, t, l, s: _logo_effect(0x02, t, l, s),
             "wave": None},                        # single LED can't wave
}


def build(method, action, rgb, txn, led, store=True):
    """Reports for one action. action in ACTIONS; rgb is a 3-tuple (or None).

    Raises NotImplementedError for unsupported (method, action) combos, e.g.
    'kraken' devices (different protocol) or 'wave' on a single-LED logo zone.
    """
    if method not in METHODS:
        raise NotImplementedError(f"lighting method {method!r} not implemented")
    sv = VARSTORE if store else NOSTORE
    if action == "static":
        return _STATIC[method](rgb or (0, 0, 0), txn, led, sv)
    if action == "breathing" and method == "custom":
        txn = 0xFF                      # Viper-Mini-class breathing uses txn 0xff
    if action == "wave" and method in ("custom", "logo"):
        raise NotImplementedError("wave needs a multi-zone device; this one has a single LED")
    fn = _ANIM[_FAMILY[method]].get(action)
    if fn is None:
        raise NotImplementedError(f"{action!r} not available for {method!r} devices")
    return fn(rgb, txn, led, sv)
