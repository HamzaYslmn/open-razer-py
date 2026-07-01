"""settings.txt persistence + register the app to run at startup.

settings.txt (one device per line, in docs/) records what to re-apply:
    <pid_hex> <action> [colorhex]     e.g.  008a static ff1e00  |  008a spectrum

`--startup apply` replays it (what the logon launcher runs); a normal run records
the applied setting back into it so "set once" survives reboots.
"""

import os
import sys

import drivers

_HEADER = (
    "# RazerKit startup settings -- replayed at logon with:  python src/main.py --startup apply\n"
    "# columns:  device | pid | action | color    (color = hex like ff1e00, or - for effects)\n"
)


# Everything is anchored to main.py so paths don't depend on the cwd.
def _main_py():
    here = os.path.dirname(os.path.abspath(__file__))      # <proj>/src/modules
    return os.path.join(os.path.dirname(here), 'main.py')   # <proj>/src/main.py


def _proj():
    return os.path.dirname(os.path.dirname(_main_py()))     # <proj>


def _docs(*parts):
    return os.path.join(_proj(), 'docs', *parts)


def path():
    return _docs('settings.txt')


def load():
    """[(pid, action, rgb_or_None)] from settings.txt; [] if missing/empty.

    Accepts the aligned 'name | pid | action | color' table and the older
    whitespace 'pid action color' form. The name column is informational.
    """
    from modules.core import parse_color
    p = path()
    if not os.path.exists(p):
        return []
    out = []
    with open(p, encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith('#'):
                continue
            fields = [x.strip() for x in s.split('|')] if '|' in s else s.split()
            pidtok = fields[1] if '|' in s else fields[0]   # name|pid|...  vs  pid ...
            rest = fields[2:] if '|' in s else fields[1:]
            try:
                pid = int(pidtok, 16)
            except ValueError:
                continue
            action = rest[0] if rest and rest[0] else 'static'
            coltok = rest[1] if len(rest) > 1 else '-'
            rgb = None
            if coltok and coltok != '-':
                try:
                    rgb = parse_color(coltok)
                except ValueError:
                    rgb = None
            out.append((pid, action, rgb))
    return out


def _name(pid):
    d = drivers.get(pid)
    return d.name if d else f"Unknown 1532:{pid:04x}"


def save(pid, action, rgb):
    """Record/replace this device's setting in settings.txt as an aligned table."""
    rows = {p: (a, c) for p, a, c in load()}
    rows[pid] = (action, rgb)
    namew = max([6] + [len(_name(p)) for p in rows])
    actw = max([6] + [len(a) for a, _ in rows.values()])
    lines = [_HEADER]
    for p in sorted(rows):
        a, c = rows[p]
        col = f"{c[0]:02x}{c[1]:02x}{c[2]:02x}" if (c and a in ('static', 'breathing')) else "-"
        lines.append(f"{_name(p):<{namew}} | {p:04x} | {a:<{actw}} | {col}\n")
    with open(path(), 'w', encoding='utf-8') as f:
        f.write("".join(lines))


# --- run at logon ------------------------------------------------------------
def _launcher():
    """(exe, script) that runs --startup apply; prefer pythonw to hide the console."""
    exe = sys.executable
    if sys.platform == 'win32':
        pyw = exe.replace('python.exe', 'pythonw.exe')
        if os.path.exists(pyw):
            exe = pyw
    return exe, _main_py()


def _startup_dir():
    return os.path.join(os.environ.get('APPDATA', ''), 'Microsoft', 'Windows',
                        'Start Menu', 'Programs', 'Startup')


def _startup_vbs():
    return os.path.join(_startup_dir(), 'RazerRGB.vbs')


def _make_vbs(exe, script):
    """Hidden launcher (window style 0). A bare RazerRGB.vbs *directly* in the Startup
    folder makes Task Manager show the entry as "RazerRGB" -- Startup-folder files are
    labelled by filename, unlike shortcuts (which show their target program, e.g. pythonw)."""
    cmd = f'"{exe}" "{script}" --startup apply'
    with open(_startup_vbs(), 'w', encoding='utf-8') as f:
        f.write(f'CreateObject("Wscript.Shell").Run "{cmd.replace(chr(34), chr(34) * 2)}", 0, False\n')


def install_startup():
    """Run --startup apply at logon. Returns a status string. No admin needed.

    Windows: a hidden RazerRGB.vbs in the user's Startup folder (shows in Task Manager
    > Startup apps as "RazerRGB"). Linux: a ~/.config/autostart entry.
    """
    if not os.path.exists(path()):                 # seed: default device, brand color ff1e00
        save(drivers.DEFAULT_PID, 'static', (0xFF, 0x1E, 0x00))
    exe, script = _launcher()
    if sys.platform == 'win32':
        os.makedirs(_startup_dir(), exist_ok=True)
        _make_vbs(exe, script)
        for old in (os.path.join(_startup_dir(), 'RazerRGB.lnk'),   # clean older iconed-shortcut bits
                    _docs('logo.ico'), _docs('RazerRGB.vbs')):
            if os.path.exists(old):
                os.remove(old)
        return (f'installed Startup launcher (no admin):\n  {_startup_vbs()}\n'
                f'  shows in Task Manager > Startup apps as "RazerRGB". Edit {path()}')
    if sys.platform.startswith('linux'):
        d = os.path.expanduser('~/.config/autostart')
        os.makedirs(d, exist_ok=True)
        desktop = os.path.join(d, 'razer-rgb.desktop')
        with open(desktop, 'w', encoding='utf-8') as f:
            f.write("[Desktop Entry]\nType=Application\nName=RazerKit\n"
                    f'Exec={exe} "{script}" --startup apply\n'
                    "X-GNOME-Autostart-enabled=true\n")
        return f"installed autostart entry {desktop}. Edit {path()}"
    raise SystemExit(f"startup install not supported on {sys.platform}")


def uninstall_startup():
    if sys.platform == 'win32':
        targets = [_startup_vbs(), os.path.join(_startup_dir(), 'RazerRGB.lnk'),
                   _docs('logo.ico'), _docs('RazerRGB.vbs')]
    else:
        targets = [os.path.expanduser('~/.config/autostart/razer-rgb.desktop')]
    removed = []
    for t in targets:
        if os.path.exists(t):
            os.remove(t)
            removed.append(t)
    return "removed: " + ("; ".join(removed) if removed else "nothing was installed")
