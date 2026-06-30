"""Terminal menu app + the plain device listing (the no-args default)."""

import os
import sys

import drivers
import transport
from modules import settings
from modules.core import apply, connected_list, describe, parse_color, read_hz

_QUICK = [('1', 'red'), ('2', 'green'), ('3', 'blue'), ('4', 'white'),
          ('5', 'yellow'), ('6', 'cyan'), ('7', 'magenta'), ('8', 'orange')]


# --- ANSI helpers (no-op when output isn't a terminal) -----------------------
def _color():
    return sys.stdout.isatty()


def _enable_ansi():
    if sys.platform == 'win32':
        try:                                  # turn on VT processing so escapes render
            import ctypes
            k = ctypes.windll.kernel32
            h = k.GetStdHandle(-11)
            mode = ctypes.c_uint()
            k.GetConsoleMode(h, ctypes.byref(mode))
            k.SetConsoleMode(h, mode.value | 0x0004)
        except Exception:
            pass


def _wrap(s, code):
    return f"\033[{code}m{s}\033[0m" if _color() else s


def _swatch(rgb):
    if not _color():
        return ''
    return f"\033[48;2;{rgb[0]};{rgb[1]};{rgb[2]}m  \033[0m"


def _clear():
    if sys.stdout.isatty():
        os.system('cls' if sys.platform == 'win32' else 'clear')


# --- plain listing (no-args, non-interactive) --------------------------------
def list_connected():
    """Numbered list of connected devices + brief usage."""
    if not transport.SUPPORTED:
        print(f"This OS ({sys.platform}) isn't supported -- Windows and Linux only.")
        print("(--selftest and --devices work anywhere.)")
        return
    devs = connected_list()
    if not devs:
        print("No Razer (1532:*) devices connected.")
    else:
        print("Connected Razer devices:")
        for i, (pid, name, ok) in enumerate(devs, 1):
            star = " *" if pid == drivers.DEFAULT_PID else ""
            hz = read_hz(pid) if ok else None
            rate = f"  {hz} Hz" if hz else ""
            note = "" if ok else "  (no control collection)"
            print(f"  {i}. 1532:{pid:04x}  {name}{star}{rate}{note}")
    print("\nUsage:  python src/main.py <color|effect> [-d N|all]")
    print("        color  = red green blue white off | ff1e00 | '255,0,0'")
    print("        effect = spectrum | breathing [color]   (wave needs a multi-zone device)")
    print("        -m menu,  --temp apply once,  --startup install,  * = default.")


# --- the menu app ------------------------------------------------------------
def _choose_device(devs):
    """Numbered device picker. Returns a pid, or None to cancel."""
    _clear()
    print(_wrap("  Pick a device", "1"))
    for i, (pid, name, _ok) in enumerate(devs, 1):
        print(f"   {_wrap(str(i), '36')}. {name}  {_wrap(f'1532:{pid:04x}', '2')}")
    ans = input("  number (blank = cancel): ").strip()
    try:
        return devs[int(ans) - 1][0]
    except (ValueError, IndexError):
        return None


def _render(name, save, status, can_wave, hz):
    rule = _wrap("-" * 44, "2")        # ASCII only -- box-drawing chars break on cp125x consoles
    print(_wrap("  RAZER RGB", "1;35"))
    print("  " + rule)
    rate = _wrap(f"   {hz} Hz", "2") if hz else ""
    print(f"  {_wrap('device', '36')}  {name}{rate}")
    print(f"  {_wrap('save', '36')}    " + (_wrap("on", "32") if save else _wrap("off", "2")))
    if status:
        print(f"  {_wrap('status', '36')}  {status}")
    print("  " + rule)
    print("  " + _wrap("colors", "1"))
    cells = [f"[{_wrap(k, '36')}]{_swatch(parse_color(n))} {n:<8}" for k, n in _QUICK]
    for i in range(0, len(cells), 4):
        print("    " + " ".join(cells[i:i + 4]))
    print(f"    [{_wrap('c', '36')}]{_swatch((136, 136, 136))} custom...")
    wave = f"[{_wrap('w', '36')}] wave   " if can_wave else ""    # hidden on single-LED devices
    print("  " + _wrap("effects", "1") +
          f"   [{_wrap('p', '36')}] spectrum   [{_wrap('b', '36')}] breathing   "
          f"{wave}[{_wrap('o', '36')}] off")
    print("  " + _wrap("manage", "1") +
          f"    [{_wrap('d', '36')}] device   [{_wrap('s', '36')}] save   [{_wrap('q', '36')}] quit")
    print("  " + rule)


def menu():
    """A small redrawing terminal menu: pick a device, fire colors/effects."""
    if not transport.SUPPORTED:
        return list_connected()
    _enable_ansi()
    devs = connected_list()
    if not devs:
        print("No Razer (1532:*) devices connected.")
        return
    pid, save, status = devs[0][0], True, ""
    hz = read_hz(pid)
    colors = dict(_QUICK)
    while True:
        _clear()
        dev = drivers.get(pid)
        can_wave = not dev or dev.method not in ('custom', 'logo')
        _render(dev.name if dev else f"1532:{pid:04x}", save, status, can_wave, hz)
        c = input("  > ").strip().lower()
        if c in ('q', 'quit'):
            return
        try:
            if c == 'd':
                newpid = _choose_device(connected_list())
                if newpid:
                    pid = newpid
                    hz = read_hz(pid)
                status = ""
                continue
            if c == 's':
                save = not save
                status = _wrap(f"save {'on' if save else 'off'}", "2")
                continue
            if c in colors:
                action, rgb = 'static', parse_color(colors[c])
            elif c == 'c':
                action, rgb = 'static', parse_color(input("  hex / r,g,b: ").strip())
            elif c == 'b':
                col = input("  breathe color (blank = random): ").strip()
                action, rgb = 'breathing', (parse_color(col) if col else None)
            elif c == 'o':
                action, rgb = 'static', (0, 0, 0)            # off == solid black
            elif c in ('p', 'w'):
                action, rgb = {'p': 'spectrum', 'w': 'wave'}[c], None
            else:
                status = _wrap("?  pick a listed key", "33")
                continue
            label, _ = apply(pid, action, rgb, save=save)
            settings.save(pid, action, rgb)         # remember for --startup apply at logon
            status = _wrap(f"OK  {label} -> {describe(action, rgb)}", "32")
        except ValueError as e:
            status = _wrap(str(e), "31")
        except SystemExit as e:          # apply() failures shouldn't kill the menu
            status = _wrap(str(e), "31")
