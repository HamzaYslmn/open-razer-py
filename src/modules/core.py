"""Color/action parsing and device operations. No UI, no argparse."""

import drivers
import transport

ANIMATIONS = ("spectrum", "breathing", "wave")


def parse_color(s):
    named = {'red': (255, 0, 0), 'green': (0, 255, 0), 'blue': (0, 0, 255),
             'white': (255, 255, 255), 'off': (0, 0, 0), 'black': (0, 0, 0),
             'yellow': (255, 255, 0), 'cyan': (0, 255, 255), 'magenta': (255, 0, 255),
             'purple': (128, 0, 128), 'orange': (255, 80, 0)}
    t = s.strip().lstrip('#').lower()
    if t in named:
        return named[t]
    if ',' in s:
        parts = s.split(',')
        if len(parts) == 3 and all(p.strip().isdigit() and 0 <= int(p) <= 255 for p in parts):
            return tuple(int(p) for p in parts)
    if len(t) == 6 and all(ch in '0123456789abcdef' for ch in t):
        return tuple(int(t[i:i + 2], 16) for i in (0, 2, 4))
    raise ValueError(f"bad color {s!r} (use ff0000, '255,0,0', or a name)")


def resolve_action(what, color=None):
    """(action, rgb) from a positional that is either a color or an effect word."""
    lw = what.strip().lower()
    if lw in ('off', 'black'):
        return 'static', (0, 0, 0)                 # off == solid black, not the 'none' effect
    if lw in ANIMATIONS:
        return lw, (parse_color(color) if color else None)
    if lw == 'static':
        if not color:
            raise ValueError("'static' needs a color, e.g. static ff0000")
        return 'static', parse_color(color)
    return 'static', parse_color(what)             # plain color -> static


def describe(action, rgb):
    if action == 'static' or (action == 'breathing' and rgb):
        return f"#{''.join(f'{c:02x}' for c in rgb)}" + (" breathing" if action == 'breathing' else "")
    return action


def connected_list():
    """[(pid, name, control_found)] for connected devices, in list order."""
    out = []
    for pid, ok in sorted(transport.connected().items()):
        dev = drivers.get(pid)
        out.append((pid, dev.name if dev else "unknown model", ok))
    return out


_HZ = {0x01: 1000, 0x02: 500, 0x03: 125}


def read_hz(pid):
    """Polling rate in Hz read from the device, or None if it can't be read."""
    req = drivers.protocol.razer_report(0x00, 0x85, 0x01, b"", 0xFF)   # get polling rate
    for p in transport.control_paths(pid):
        try:
            r = transport.get_response(p, req)
        except OSError:
            continue
        if r[0] == 0x02 and r[8]:           # status success + a real rate code
            return _HZ.get(r[8]) or (1000 // r[8] if 1 <= r[8] <= 8 else None)
    return None


def select_targets(selector=None):
    """Resolve which device pids to act on from one -d value.

    selector: None=auto, 'all'=every connected, a list number ('2'), or a pid hex ('008a').
    Auto-pick = the default device if present, else the sole connected one, else ask.
    """
    devs = connected_list()
    conn = [d[0] for d in devs]
    if selector is None:
        if drivers.DEFAULT_PID in conn:
            return [drivers.DEFAULT_PID]
        if len(conn) == 1:
            return conn
        if not conn:
            return [drivers.DEFAULT_PID]    # apply() will give the friendly "not found"
        listing = "\n".join(f"  {i}. {n}  (1532:{p:04x})" for i, (p, n, _ok) in enumerate(devs, 1))
        raise SystemExit("multiple devices connected -- pick one with -d N (or -d all):\n" + listing)
    s = selector.strip().lower()
    if s == 'all':
        if not conn:
            raise SystemExit("no Razer devices connected")
        return conn
    if len(s) <= 2 and s.isdigit():         # short decimal -> list number
        i = int(s)
        if not 1 <= i <= len(devs):
            raise SystemExit(f"-d {selector}: only {len(devs)} device(s) connected")
        return [devs[i - 1][0]]
    try:                                     # otherwise a pid in hex
        return [int(s, 16)]
    except ValueError:
        raise SystemExit(f"bad -d {selector!r} (use a list number, a pid like 008a, or 'all')")


def apply(pid, action, rgb, save=True, method=None, txn=None, led=None):
    """Run `action` on the device with this pid. Returns (label, method)."""
    dev = drivers.get(pid)
    if dev:
        method, txn, led = method or dev.method, dev.txn if txn is None else txn, dev.led if led is None else led
        label = dev.name
    else:
        method, txn, led = method or 'custom', 0x3F if txn is None else txn, 0x00 if led is None else led
        label = f"unknown 1532:{pid:04x}"
    try:
        reports = drivers.build(method, action, rgb, txn, led, save)
    except NotImplementedError as e:
        raise SystemExit(f"{label}: {e}")

    paths = transport.control_paths(pid)
    if not paths:
        raise SystemExit(f"{label}: no 1532:{pid:04x} device found (plugged in?)")
    last = None
    for path in paths:
        try:
            for rep in reports:
                transport.set_feature(path, rep)
            return label, method
        except OSError as e:
            last = e
    raise SystemExit(f"{label}: every candidate collection rejected the report (last: {last})")
