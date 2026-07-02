"""Razer USB-HID protocol: build reports that set a color, run an on-device effect,
set brightness, or query device state (battery / firmware / serial / DPI / polling).

Platform independent -- the transport lives in `transport`. `build(method, action,
rgb, txn, led, store)` returns the report sequence for one lighting action; `store=True`
(VARSTORE) asks the device to keep the setting in its onboard memory, `store=False`
(NOSTORE) is volatile. Opcodes verified against openrazer master (razerchromacommon.c).
"""

# LED ids / flags
ZERO_LED, SCROLL_WHEEL_LED, LOGO_LED, BACKLIGHT_LED = 0x00, 0x01, 0x04, 0x05
VARSTORE, NOSTORE, ON, OFF = 0x01, 0x00, 0x01, 0x00

ACTIONS = ("static", "off", "spectrum", "breathing", "wave", "reactive", "starlight")
METHODS = ("ext_static", "std_static", "custom", "logo")

WAVE_SPEED = 0x28          # ponytail: openrazer's default wave speed; lower = faster
POLL_CODES = {1000: 0x01, 500: 0x02, 125: 0x08}   # standard polling-rate map (0x00/0x05)


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


def _ext_breathing(rgb, rgb2, txn, led, sv):
    if rgb and any(rgb) and rgb2 and any(rgb2):       # breathe between two colors
        a = bytearray(12)
        a[0], a[1], a[2], a[3], a[5] = sv, led, 0x02, 0x02, 0x02
        a[6], a[7], a[8] = rgb
        a[9], a[10], a[11] = rgb2
        return [razer_report(0x0F, 0x02, 0x0C, a, txn)]
    if rgb and any(rgb):                              # breathe one chosen color
        a = bytearray(9)
        a[0], a[1], a[2], a[3], a[5] = sv, led, 0x02, 0x01, 0x01
        a[6], a[7], a[8] = rgb
        return [razer_report(0x0F, 0x02, 0x09, a, txn)]
    return _ext_simple(0x02, txn, led, sv)            # random


def _ext_wave(txn, led, sv, direction):
    a = bytearray(5)
    a[0], a[1], a[2], a[3], a[4] = sv, led, 0x04, direction, WAVE_SPEED
    return [razer_report(0x0F, 0x02, 0x06, a, txn)]


def _ext_reactive(rgb, txn, led, sv, speed):
    a = bytearray(9)
    a[0], a[1], a[2], a[4], a[5] = sv, led, 0x05, speed, 0x01
    a[6], a[7], a[8] = rgb
    return [razer_report(0x0F, 0x02, 0x09, a, txn)]


def _ext_starlight(rgb, txn, led, sv, speed):
    if rgb and any(rgb):
        a = bytearray(9)
        a[0], a[1], a[2], a[4], a[5] = sv, led, 0x07, speed, 0x01
        a[6], a[7], a[8] = rgb
        return [razer_report(0x0F, 0x02, 0x09, a, txn)]
    a = bytearray(6)
    a[0], a[1], a[2], a[4] = sv, led, 0x07, speed          # random starlight
    return [razer_report(0x0F, 0x02, 0x06, a, txn)]


# --- custom frame (the old Viper Mini static path; kept, unused) --------------
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


def _std_breathing(rgb, rgb2, txn):
    a = bytearray(8)
    a[0] = 0x03                                    # MATRIX_EFFECT_BREATHING
    if rgb and any(rgb) and rgb2 and any(rgb2):
        a[1] = 0x02                                # dual
        a[2], a[3], a[4] = rgb
        a[5], a[6], a[7] = rgb2
    elif rgb and any(rgb):
        a[1] = 0x01                                # single
        a[2], a[3], a[4] = rgb
    else:
        a[1] = 0x03                                # random
    return [razer_report(0x03, 0x0A, 0x08, a, txn)]


def _std_wave(txn, direction):
    return [razer_report(0x03, 0x0A, 0x02, bytes([0x01, direction]), txn)]


def _std_reactive(rgb, txn, speed):
    a = bytearray(5)
    a[0], a[1] = 0x02, speed                       # MATRIX_EFFECT_REACTIVE
    a[2], a[3], a[4] = rgb
    return [razer_report(0x03, 0x0A, 0x05, a, txn)]


def _std_starlight(rgb, txn, speed):
    a = bytearray(9)
    a[0], a[2] = 0x19, speed                        # MATRIX_EFFECT_STARLIGHT
    if rgb and any(rgb):
        a[1] = 0x01
        a[3], a[4], a[5] = rgb
    else:
        a[1] = 0x03                                 # random
    return [razer_report(0x03, 0x0A, 0x09, a, txn)]


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
# on-device. custom/logo are single-LED -> animate via their family below.
_STATIC = {"ext_static": _ext_static, "std_static": _std_static,
           "custom": _ext_static, "logo": _logo_static}
_FAMILY = {"ext_static": "ext", "std_static": "std", "custom": "ext", "logo": "logo"}
_SINGLE_LED = ("custom", "logo")   # can't wave / react -- one zone


def build(method, action, rgb, txn, led, store=True, *, rgb2=None, speed=0x02, direction=0x01):
    """Reports for one lighting action. action in ACTIONS; rgb is a 3-tuple (or None).

    rgb2 = second color (dual breathing). speed = reactive/effect speed (1-4).
    direction = wave direction (0/1 or 1/2 depending on firmware). Raises
    NotImplementedError for unsupported (method, action) combos.
    """
    if method not in METHODS:
        raise NotImplementedError(f"lighting method {method!r} not implemented")
    sv = VARSTORE if store else NOSTORE
    fam = _FAMILY[method]
    if action == "static":
        return _STATIC[method](rgb or (0, 0, 0), txn, led, sv)
    if action == "off":
        return (_ext_simple(0x00, txn, led, sv) if fam == "ext"
                else _std_simple(0x00, txn) if fam == "std" else _logo_off(txn, led, sv))
    if action == "spectrum":
        return (_ext_simple(0x03, txn, led, sv) if fam == "ext"
                else _std_simple(0x04, txn) if fam == "std" else _logo_effect(0x04, txn, led, sv))
    if action == "breathing":
        if method == "custom":
            txn = 0xFF                              # Viper-Mini-class breathing uses txn 0xff
        return (_ext_breathing(rgb, rgb2, txn, led, sv) if fam == "ext"
                else _std_breathing(rgb, rgb2, txn) if fam == "std" else _logo_effect(0x02, txn, led, sv))
    if action == "wave":
        if method in _SINGLE_LED:
            raise NotImplementedError("wave needs a multi-zone device; this one has a single LED")
        return _ext_wave(txn, led, sv, direction) if fam == "ext" else _std_wave(txn, direction)
    if action == "reactive":
        if method in _SINGLE_LED:
            raise NotImplementedError("reactive needs a multi-zone device; this one has a single LED")
        return (_ext_reactive(rgb or (0, 0, 0), txn, led, sv, speed) if fam == "ext"
                else _std_reactive(rgb or (0, 0, 0), txn, speed))
    if action == "starlight":
        if method in _SINGLE_LED:
            raise NotImplementedError("starlight needs a multi-zone device; this one has a single LED")
        speed = max(1, min(3, speed))
        return (_ext_starlight(rgb, txn, led, sv, speed) if fam == "ext"
                else _std_starlight(rgb, txn, speed))
    raise NotImplementedError(f"{action!r} not available for {method!r} devices")


# --- custom per-key frame (extended 0x0F/0x03 or standard 0x03/0x0B) ----------
def _ext_set_row(row, colors, txn):
    a = bytearray(5 + len(colors) * 3)
    a[2], a[3], a[4] = row, 0, len(colors) - 1
    for i, (r, g, b) in enumerate(colors):
        a[5 + i * 3], a[6 + i * 3], a[7 + i * 3] = r, g, b
    return razer_report(0x0F, 0x03, 0x47, a, txn)


def _std_set_row(row, colors, txn):
    a = bytearray(4 + len(colors) * 3)
    a[0], a[1], a[2], a[3] = 0xFF, row, 0, len(colors) - 1
    for i, (r, g, b) in enumerate(colors):
        a[4 + i * 3], a[5 + i * 3], a[6 + i * 3] = r, g, b
    return razer_report(0x03, 0x0B, 0x46, a, txn)


def build_custom_frame(method, rows, txn, led, store=True):
    """Per-key image: one set-row report per row, then a 'custom' effect report.

    rows = [(row_index, [(r, g, b), ...]), ...] with colors starting at column 0.
    Raises NotImplementedError for single-LED (logo) devices.
    """
    if method not in METHODS:
        raise NotImplementedError(f"lighting method {method!r} not implemented")
    fam = _FAMILY[method]
    sv = VARSTORE if store else NOSTORE
    if fam == "logo":
        raise NotImplementedError("custom frame needs a matrix device; this one has a single LED")
    reports = []
    if fam == "std":
        for row, colors in rows:
            reports.append(_std_set_row(row, colors, txn))
        reports.append(razer_report(0x03, 0x0A, 0x02, bytes([0x05, sv]), txn))   # arm CUSTOMFRAME
    else:
        for row, colors in rows:
            reports.append(_ext_set_row(row, colors, txn))
        reports.append(razer_report(0x0F, 0x02, 0x06, bytes([sv, led, 0x08]), txn))  # arm custom 0x08
    return reports


# --- brightness --------------------------------------------------------------
def brightness(method, level, txn, led, store=True):
    """Set brightness 0-255. ext/custom -> 0x0F/0x04; std/logo -> 0x03/0x03."""
    level = max(0, min(255, int(level)))
    sv = VARSTORE if store else NOSTORE
    if method in ("ext_static", "custom"):
        return [razer_report(0x0F, 0x04, 0x03, bytes([sv, led, level]), txn)]
    bled = led or (BACKLIGHT_LED if method == "std_static" else LOGO_LED)
    return [razer_report(0x03, 0x03, 0x03, bytes([sv, bled, level]), txn)]


# --- device-state queries (send these; transport reads the 90-byte reply) ----
def q_firmware(txn): return razer_report(0x00, 0x81, 0x02, b"", txn)   # resp arg0.arg1
def q_serial(txn):   return razer_report(0x00, 0x82, 0x16, b"", txn)   # resp arg0..21 ASCII
def q_battery(txn):  return razer_report(0x07, 0x80, 0x02, b"", txn)   # resp arg1 (0-255)
def q_charging(txn): return razer_report(0x07, 0x84, 0x02, b"", txn)   # resp arg1 (0/1)
def q_dpi(txn):      return razer_report(0x04, 0x85, 0x07, bytes([NOSTORE]), txn)  # resp arg1..4
def q_poll(txn):     return razer_report(0x00, 0x85, 0x01, b"", txn)   # resp arg0 code


# --- device-state writes -----------------------------------------------------
def set_dpi(x, y, txn):
    """Set DPI (big-endian, VARSTORE). x/y clamped 100-30000."""
    x = max(100, min(30000, int(x)))
    y = max(100, min(30000, int(y)))
    a = bytes([VARSTORE, x >> 8, x & 0xFF, y >> 8, y & 0xFF, 0x00, 0x00])
    return [razer_report(0x04, 0x05, 0x07, a, txn)]


def set_poll(hz, txn):
    """Set polling rate. hz in {1000, 500, 125}."""
    code = POLL_CODES.get(int(hz))
    if code is None:
        raise ValueError("polling rate must be 1000, 500, or 125")
    return [razer_report(0x00, 0x05, 0x01, bytes([code]), txn)]


POLL_CODES2 = {8000: 0x01, 4000: 0x02, 2000: 0x04, 1000: 0x08, 500: 0x10, 250: 0x20, 125: 0x40}


def set_poll2(hz, txn):
    """HyperPolling set (up to 8000 Hz) via 0x00/0x40."""
    code = POLL_CODES2.get(int(hz))
    if code is None:
        raise ValueError("polling rate must be 8000/4000/2000/1000/500/250/125")
    return [razer_report(0x00, 0x40, 0x02, bytes([0x00, code]), txn)]


def set_dpi_stages(stages, active, txn):
    """DPI stages via 0x04/0x06. stages = [(x, y), ...] (<=5); active is 1-based."""
    a = bytearray(3 + len(stages) * 7)
    a[0], a[1], a[2] = VARSTORE, active, len(stages)
    for i, (x, y) in enumerate(stages):
        x = max(100, min(30000, int(x)))
        y = max(100, min(30000, int(y)))
        o = 3 + i * 7
        a[o], a[o + 1], a[o + 2], a[o + 3], a[o + 4] = i + 1, x >> 8, x & 0xFF, y >> 8, y & 0xFF
    return [razer_report(0x04, 0x06, 0x26, a, txn)]


# --- scroll-wheel modes (mice) -----------------------------------------------
def set_scroll_mode(mode, txn):  return [razer_report(0x02, 0x14, 0x02, bytes([VARSTORE, mode & 0xFF]), txn)]
def set_scroll_accel(on, txn):   return [razer_report(0x02, 0x16, 0x02, bytes([VARSTORE, 0x01 if on else 0x00]), txn)]
def set_smart_reel(on, txn):     return [razer_report(0x02, 0x17, 0x02, bytes([VARSTORE, 0x01 if on else 0x00]), txn)]


# --- game / macro mode LED toggle (keyboards; driver forces txn 0xFF) --------
GAME_LED, MACRO_LED = 0x08, 0x07


def _set_led_state(led, on):
    return [razer_report(0x03, 0x00, 0x03, bytes([VARSTORE, led, ON if on else OFF]), 0xFF)]


def set_game_mode(on):  return _set_led_state(GAME_LED, on)
def set_macro_mode(on): return _set_led_state(MACRO_LED, on)


# --- analog "driver mode" (Huntsman V2/V3 analog keyboards) -------------------
# The one proven analog command: the generic "set device mode" (0x00/0x04) that
# flips the board between normal HID and driver mode. Driver mode unlocks the raw
# per-key analog value stream (0x0000-0xFFFF press depth) that external tools read
# to implement custom actuation IN SOFTWARE. The actual on-device actuation-point
# opcode is NOT public (undecoded in every open-source project), so we don't set
# it here -- Synapse is still the only way to change the physical actuation height.
# Verified byte-for-byte against a captured driver-mode packet (CRC 0x05 on / 0x06
# off). WARNING for callers: while in driver mode the keyboard stops sending normal
# keystrokes to the OS, so anything that turns it on must turn it back off.
def set_device_mode(driver, txn=0xFF):
    """Enter (driver=True) or leave (False) analog driver mode. arg0: 0x03/0x00."""
    return [razer_report(0x00, 0x04, 0x02, bytes([0x03 if driver else 0x00, 0x00]), txn)]


# --- Razer Blade laptop: performance mode / battery (EC via the keyboard MCU)
# Opcodes verified on Blade 16 2024 (1532:02b7); MODEL/FIRMWARE-SPECIFIC (see
# BLADE_VERIFIED in core). Both fan zones (1, 2) are addressed; args[0]=0x01
# matters (0x00 may ACK but not apply). Performance mode sets the firmware fan
# curve -- we intentionally do NOT expose a manual fan-rpm knob (thermal safety).
BLADE_TXN = 0x1F
PERF_MODES = {"balanced": 0, "gaming": 1, "creator": 2}


def blade_perf(mode):
    """Set performance mode (0=balanced/1=gaming/2=creator) with firmware/auto fan."""
    mode &= 0xFF
    return [razer_report(0x0D, 0x02, 0x04, bytes([0x01, z, mode, 0x00]), BLADE_TXN) for z in (1, 2)]


def blade_charge(percent):
    """Battery charge limit. percent falsy/None => off (0x41); else (pct|0x80). Needs the commit."""
    raw = 0x41 if not percent else (int(percent) & 0x7F) | 0x80
    return [razer_report(0x07, 0x12, 0x01, bytes([raw]), BLADE_TXN),
            razer_report(0x07, 0x0F, 0x01, bytes([0x02]), BLADE_TXN)]      # required commit


# Blade reads (send; transport reads the 90-byte reply). Response arg offsets
# are into the reply: arg0 = byte[8], arg2 = byte[10]; status at byte[0] == 0x02.
def q_blade_fan(zone):  return razer_report(0x0D, 0x88, 0x04, bytes([0x00, zone & 0xFF]), BLADE_TXN)  # resp arg2 * 100
def q_blade_perf():     return razer_report(0x0D, 0x82, 0x04, bytes([0x00, 0x01]), BLADE_TXN)          # resp arg2 (0/1/2)
def q_blade_charge():   return razer_report(0x07, 0x8F, 0x01, bytes([0x00]), BLADE_TXN)                # resp arg0


# --- headset on-device EQ: BlackShark V2 Pro (1532:0555) ----------------------
# A DIFFERENT frame from the 90-byte razer report: 64-byte "PA" packets written
# as raw HID output reports to the vendor (0xFF00) collection. No CRC.
# Layout: [0]=0x02 report type  [1]=0x80 host->device  [2]=total_len
#         [5:7]='PA' magic  [7]=inner_len  [9]=cmd_class  [10]=cmd_id  [11:]=params
# Verified only on the BlackShark V2 Pro (see EQ_VERIFIED in core).
EQ_PRESETS = {
    'flat':  [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    'game':  [-3, -3, -4, 0, 5, 5, 4, 1, 0, -1],
    'music': [2, 2, 1, 1, 2, 3, 3, 3, 1, 0],
    'movie': [4, 4, 3, 0, -3, -1, 3, 5, 2, 1],
}


def _pa_packet(total, inner, cls, cid, params):
    b = bytearray(64)
    b[0], b[1], b[2] = 0x02, 0x80, total
    b[5:7] = b'PA'
    b[7] = inner
    b[9], b[10] = cls, cid
    b[11:11 + len(params)] = bytes(p & 0xFF for p in params)
    return bytes(b)


def eq_remote_mode(on):
    """Must precede most audio commands (Synapse toggles it around each batch)."""
    return _pa_packet(0x07, 0x0E, 0x02, 0xE1, [1 if on else 0])


def eq_config():
    """DSP pipeline config -- constant blob captured from Synapse."""
    return _pa_packet(0x0B, 0x08, 0x06, 0x01, [0xC2, 0x03, 0xF8, 0x5F, 0x04])


def eq_preset_enable(on):
    """On = use the on-device preset slot; off = take the custom band gains."""
    return _pa_packet(0x09, 0x08, 0x04, 0x9E, [0x00, 1 if on else 0])


def eq_bands_report(bands):
    """10 band gains, signed dB steps (approx. -5..+5 used by Synapse presets)."""
    if len(bands) != 10 or any(not -12 <= int(b) <= 12 for b in bands):
        raise ValueError("EQ needs exactly 10 band gains, each -12..12")
    return _pa_packet(0x12, 0x08, 0x0D, 0x95, [0x00, 0x0A] + [int(b) for b in bands])


def build_eq_sequence(bands):
    """The apply sequence Synapse sends (minus volume/enhancement -- we don't
    touch those). Caller spaces packets ~35ms apart and re-sends the bands once
    after ~300ms, which is what makes the setting stick."""
    return [eq_remote_mode(False), eq_config(), eq_remote_mode(True),
            eq_preset_enable(False), eq_remote_mode(True), eq_bands_report(bands)]
