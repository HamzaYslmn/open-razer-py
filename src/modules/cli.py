"""Argparse entry point and the no-device self-check."""

import argparse
import sys

import drivers
from modules import settings
from modules.core import apply, describe, resolve_action, select_targets
from modules.menu import list_connected, menu


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Razer RGB -- set a color or effect (Windows/Linux, no deps). "
                    "No args opens the menu.")
    p.add_argument('action', nargs='?', help="color (red, ff0000) or effect (spectrum, breathing, wave, off)")
    p.add_argument('color', nargs='?', help="color for 'breathing'")
    p.add_argument('-d', '--device', metavar='SEL',
                   help="device: a list number, a pid like 008a, or 'all' (default: auto)")
    p.add_argument('-m', '-i', '--menu', dest='menu', action='store_true', help="open the menu app")
    p.add_argument('--temp', action='store_true', help="apply once: don't save to memory or settings.txt")
    p.add_argument('--startup', choices=('apply', 'install', 'remove'),
                   help="apply settings.txt now, or (un)install the logon task")
    p.add_argument('--txn', type=lambda x: int(x, 16), help="advanced: override transaction id (hex)")
    p.add_argument('--led', type=lambda x: int(x, 16), help="advanced: override LED id (hex)")
    p.add_argument('--models', action='store_true', help="list every Razer model the registry knows")
    p.add_argument('--selftest', action='store_true', help="self-check, no device")
    args = p.parse_args(argv)

    if args.selftest:
        return _selftest()
    if args.startup:
        fn = {'apply': _apply_settings, 'install': lambda: print(settings.install_startup()),
              'remove': lambda: print(settings.uninstall_startup())}[args.startup]
        return fn()
    if args.models:
        for d in drivers.all_devices():
            print(f"1532:{d.pid:04x}  {d.category:9} {d.method:10} txn=0x{d.txn:02x}  {d.name}")
        print(f"\n{len(drivers.all_devices())} devices")
        return
    if args.menu:
        return menu()
    if args.action is None:              # bare run: menu on a real terminal, list if piped
        return menu() if sys.stdin.isatty() and sys.stdout.isatty() else list_connected()

    try:
        action, rgb = resolve_action(args.action, args.color)
    except ValueError as e:
        p.error(str(e))

    for pid in select_targets(args.device):       # may raise SystemExit (ambiguous)
        try:
            label, used = apply(pid, action, rgb, save=not args.temp, txn=args.txn, led=args.led)
            print(f"set {label} -> {describe(action, rgb)} (method={used})")
            if not args.temp:
                settings.save(pid, action, rgb)    # so --startup apply reproduces it at logon
        except SystemExit as e:        # one device failing shouldn't abort the rest (-d all)
            print(e)


def _apply_settings():
    """Replay settings.txt onto each listed device. This is what the startup task runs."""
    rows = settings.load()
    if not rows:
        print(f"no settings to apply -- edit {settings.path()} or set a color first")
        return
    for pid, action, rgb in rows:
        try:
            label, used = apply(pid, action, rgb)
            print(f"set {label} -> {describe(action, rgb)} (method={used})")
        except SystemExit as e:
            print(e)


def _selftest():
    b = drivers.build
    r = b('ext_static', 'static', (0xFF, 0x10, 0x20), 0x3F, 0x00)[0]
    assert len(r) == 90 and (r[1], r[6], r[7]) == (0x3F, 0x0F, 0x02)
    assert (r[14], r[15], r[16]) == (0xFF, 0x10, 0x20)
    crc = 0
    for i in range(2, 88):
        crc ^= r[i]
    assert r[88] == crc and crc != 0
    # custom mice (Viper Mini) static = VARSTORE extended-matrix static, so it saves on-device
    f = b('custom', 'static', (1, 2, 3), 0x3F, 0x04)
    assert len(f) == 1 and (f[0][6], f[0][7]) == (0x0F, 0x02)
    assert (f[0][14], f[0][15], f[0][16]) == (1, 2, 3) and f[0][8] == 0x01   # args[0]=VARSTORE
    assert b('ext_static', 'spectrum', None, 0xFF, 0)[0][10] == 0x03
    # custom mice (Viper Mini) animate via extended matrix on the logo LED, not 0x03
    sp = b('custom', 'spectrum', None, 0x3F, 0x04)[0]
    assert (sp[6], sp[7], sp[9], sp[10]) == (0x0F, 0x02, 0x04, 0x03)   # class, id, led, spectrum
    assert b('custom', 'breathing', None, 0x3F, 0x04)[0][1] == 0xFF    # breathing txn override
    assert len(b('logo', 'static', (1, 1, 1), 0xFF, 0x04)) == 3
    assert b('ext_static', 'static', (1, 2, 3), 0xFF, 0, store=True)[0][8] == 0x01
    assert b('ext_static', 'static', (1, 2, 3), 0xFF, 0, store=False)[0][8] == 0x00
    assert drivers.get(0x008A).method == 'custom'
    assert resolve_action('red') == ('static', (255, 0, 0))
    assert resolve_action('spectrum') == ('spectrum', None)
    assert resolve_action('breathing', 'ff0000') == ('breathing', (255, 0, 0))
    assert resolve_action('off') == ('static', (0, 0, 0))     # off == solid black
    assert select_targets('009e') == [0x009e]                 # -d pid hex (no hardware)
    try:
        b('custom', 'wave', None, 0x3F, 0x04)                 # single-LED can't wave
        assert False
    except NotImplementedError:
        pass
    print(f"selftest ok ({len(drivers.all_devices())} devices in registry)")
