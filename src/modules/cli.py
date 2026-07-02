"""Argparse entry point and the no-device self-check."""

import argparse
import sys

import drivers
from modules import settings
from modules.core import (apply, blade_status, describe, read_status, resolve_action,
                          select_targets, set_analog_mode, set_brightness, set_charge,
                          set_dpi, set_eq, set_perf, set_poll)
from modules.menu import list_connected, menu


def _dpi_arg(s):
    try:
        vals = [int(v) for v in s.lower().replace('x', ',').split(',')]
    except ValueError:
        raise argparse.ArgumentTypeError("dpi: use N or X,Y (e.g. 1600 or 1600,800)")
    if len(vals) == 1:
        return (vals[0], vals[0])
    if len(vals) == 2:
        return (vals[0], vals[1])
    raise argparse.ArgumentTypeError("dpi: use N or X,Y")


def _print_info(pid):
    st = read_status(pid)
    dev = drivers.get(pid)
    name = dev.name if dev else f"1532:{pid:04x}"
    bits = []
    if st['hz']:
        bits.append(f"{st['hz']} Hz")
    if st['dpi']:
        bits.append(f"{st['dpi'][0]}x{st['dpi'][1]} dpi")
    if st['battery'] is not None:
        bits.append(f"battery {st['battery']}%" + (" (charging)" if st['charging'] else ""))
    if st['firmware']:
        bits.append(f"fw {st['firmware']}")
    if st['serial']:
        bits.append(f"sn {st['serial']}")
    if "Blade" in name:                              # laptop: also fan/perf/charge
        bs = blade_status(pid)
        if bs['perf']:
            bits.append(f"perf {bs['perf']}")
        if any(bs['fan']):
            bits.append("fan " + "/".join(str(f) for f in bs['fan'] if f) + " rpm")
        if bs['charge']:
            bits.append(f"charge<={bs['charge']}%")
    print(f"{name}: " + ("  ".join(bits) if bits else "no readable info"))


def main(argv=None):
    p = argparse.ArgumentParser(
        description="RazerKit -- set a color or effect (Windows/Linux, no deps). "
                    "No args opens the menu.")
    p.add_argument('action', nargs='?', help="color (red, ff0000) or effect (spectrum, breathing, wave, off)")
    p.add_argument('color', nargs='?', help="color for 'breathing'")
    p.add_argument('-d', '--device', metavar='SEL',
                   help="device: a list number, a pid like 008a, or 'all' (default: auto)")
    p.add_argument('-m', '-i', '--menu', dest='menu', action='store_true', help="open the menu app")
    p.add_argument('--temp', action='store_true', help="apply once: don't save to memory or settings.txt")
    p.add_argument('--startup', choices=('apply', 'install', 'remove'),
                   help="apply settings.txt now, or (un)install the logon task")
    p.add_argument('--profile', nargs='+', metavar='ARG',
                   help="named profiles: save NAME | load NAME | list | delete NAME")
    p.add_argument('--game', nargs='+', metavar='ARG',
                   help="game mapping: add EXE PROFILE | remove EXE | list")
    p.add_argument('--watch', action='store_true',
                   help="watch running games and auto-switch profiles (see --game)")
    p.add_argument('--brightness', type=int, metavar='PCT', help="set brightness 0-100")
    p.add_argument('--dpi', type=_dpi_arg, metavar='N', help="set mouse DPI: N or X,Y")
    p.add_argument('--poll', type=int, metavar='HZ', help="set polling rate: 8000/4000/2000/1000/500/250/125")
    p.add_argument('--perf', choices=('balanced', 'gaming', 'creator'), help="Blade laptop: performance mode (sets the fan curve)")
    p.add_argument('--charge', metavar='PCT', help="Blade laptop: battery charge limit 50-95, or 'off'")
    p.add_argument('--eq', metavar='SPEC', help="headset on-device EQ: flat/game/music/movie, or 10 comma gains -12..12 (BlackShark V2 Pro)")
    p.add_argument('--analog', choices=('on', 'off'), help="Huntsman analog keyboard: toggle analog driver mode (unlocks the raw key-depth stream; pauses normal typing). On-device actuation height stays Synapse-only")
    p.add_argument('--gpu', choices=('status', 'eco', 'on'),
                   help="laptop dGPU: status | eco = power the dGPU off (admin) | on. Not a display MUX -- see README")
    p.add_argument('--force', action='store_true', help="allow Blade perf/charge or headset --eq on an untested model")
    p.add_argument('--info', action='store_true', help="read battery/firmware/serial/DPI/Hz from the device")
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
    if args.profile:
        return _profile_cmd(p, args.profile)
    if args.game:
        return _game_cmd(p, args.game)
    if args.watch:
        from modules.watcher import watch
        return watch()
    if args.gpu:
        from modules import gpu
        return gpu.main(args.gpu)
    if args.menu:
        return menu()
    ops = (args.brightness is not None or args.dpi or args.poll or args.info
           or args.perf or args.charge is not None or args.eq or args.analog)
    if args.action is None and not ops:  # bare run: menu on a real terminal, list if piped
        return menu() if sys.stdin.isatty() and sys.stdout.isatty() else list_connected()

    action = rgb = None
    if args.action is not None:
        try:
            action, rgb = resolve_action(args.action, args.color)
        except ValueError as e:
            p.error(str(e))

    for pid in select_targets(args.device):       # may raise SystemExit (ambiguous)
        try:
            if action is not None:
                label, used = apply(pid, action, rgb, save=not args.temp, txn=args.txn, led=args.led)
                print(f"set {label} -> {describe(action, rgb)} (method={used})")
                if not args.temp:
                    settings.save(pid, action, rgb)   # so --startup apply reproduces it at logon
            if args.brightness is not None:
                print(f"set {set_brightness(pid, args.brightness, save=not args.temp, txn=args.txn, led=args.led)}"
                      f" brightness -> {args.brightness}%")
            if args.dpi:
                lbl, (x, y) = set_dpi(pid, *args.dpi, txn=args.txn)
                print(f"set {lbl} dpi -> {x}x{y}")
            if args.poll:
                print(f"set {set_poll(pid, args.poll, txn=args.txn)} polling -> {args.poll} Hz")
            if args.perf:
                print(f"set {set_perf(pid, args.perf, force=args.force)} perf -> {args.perf}")
            if args.charge is not None:
                lbl, val = set_charge(pid, args.charge, force=args.force)
                print(f"set {lbl} charge limit -> {val}{'' if val == 'off' else '%'}")
            if args.eq:
                lbl, bands = set_eq(pid, args.eq, force=args.force)
                print(f"set {lbl} eq -> {','.join(str(b) for b in bands)}")
            if args.analog:
                print(f"set {set_analog_mode(pid, args.analog == 'on', txn=args.txn)} analog mode -> {args.analog}")
            if args.info:
                _print_info(pid)
        except (SystemExit, ValueError) as e:   # one device failing shouldn't abort the rest
            print(e)


def _profile_cmd(p, argv):
    """--profile save NAME | load NAME | list | delete NAME"""
    cmd, name = argv[0].lower(), (argv[1] if len(argv) > 1 else None)
    if cmd == 'list':
        profs = settings.load_profiles()
        if not profs:
            return print(f"no profiles yet -- snapshot one: --profile save <name>  ({settings.profiles_path()})")
        for n in sorted(profs):
            print(f"[{n}]" + ("  (watch default)" if n == 'default' else ""))
            for pid, (action, rgb) in sorted(profs[n].items()):
                print(f"  {pid:04x}  {describe(action, rgb)}")
        return
    if not name:
        p.error(f"--profile {cmd} needs a NAME")
    if cmd == 'save':
        print(f"saved profile [{settings.save_profile(name)}] from current settings")
    elif cmd == 'delete':
        settings.delete_profile(name)
        print(f"deleted profile [{name.lower()}]")
    elif cmd == 'load':
        for pid, action, rgb in settings.profile_rows(name):
            try:
                label, used = apply(pid, action, rgb)
                settings.save(pid, action, rgb)          # loading makes it current
                print(f"set {label} -> {describe(action, rgb)} (method={used})")
            except SystemExit as e:
                print(e)
    else:
        p.error("--profile: use save NAME | load NAME | list | delete NAME")


def _game_cmd(p, argv):
    """--game add EXE PROFILE | remove EXE | list"""
    cmd = argv[0].lower()
    if cmd == 'list':
        games = settings.load_games()
        if not games:
            return print(f"no game mappings -- add one: --game add <exe> <profile>  ({settings.games_path()})")
        for exe in sorted(games):
            print(f"{exe}  ->  [{games[exe]}]")
        return
    if cmd == 'add' and len(argv) >= 3:
        settings.set_game(argv[1], argv[2])
        print(f"{argv[1].lower()}  ->  [{argv[2].lower()}]   (run --watch, or reinstall --startup install)")
    elif cmd == 'remove' and len(argv) >= 2:
        settings.remove_game(argv[1])
        print(f"removed mapping for {argv[1].lower()}")
    else:
        p.error("--game: use add EXE PROFILE | remove EXE | list")


def _apply_settings():
    """Replay settings.txt onto each listed device. This is what the startup task runs.

    If game mappings exist, stay resident and keep watching -- so the logon
    launcher doubles as the game-profile watcher with no extra setup.
    """
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
    if settings.load_games():
        from modules.watcher import watch
        watch()


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
    try:
        b('custom', 'reactive', (1, 1, 1), 0x3F, 0x04)        # single-LED can't react
        assert False
    except NotImplementedError:
        pass

    # --- device-internal features (opcodes verified vs openrazer) ------------
    pr = drivers.protocol
    # brightness: ext (0x0F/0x04) vs std LED (0x03/0x03)
    bri = pr.brightness('custom', 200, 0x3F, 0x04, True)[0]
    assert (bri[6], bri[7]) == (0x0F, 0x04) and (bri[8], bri[9], bri[10]) == (0x01, 0x04, 200)
    bls = pr.brightness('std_static', 128, 0xFF, 0x00, True)[0]
    assert (bls[6], bls[7]) == (0x03, 0x03) and (bls[8], bls[9], bls[10]) == (0x01, 0x05, 128)
    # dual-color breathing (ext): size 0x0C, effect 0x02, mode 0x02, two RGBs
    db = b('ext_static', 'breathing', (1, 2, 3), 0x1F, 0x05, rgb2=(4, 5, 6))[0]
    assert db[5] == 0x0C and (db[10], db[11]) == (0x02, 0x02)
    assert (db[14], db[15], db[16]) == (1, 2, 3) and (db[17], db[18], db[19]) == (4, 5, 6)
    # reactive (ext): effect 0x05, speed at arg4, rgb at arg6..8
    re = b('ext_static', 'reactive', (9, 8, 7), 0x1F, 0x05, speed=3)[0]
    assert re[5] == 0x09 and re[10] == 0x05 and re[12] == 3 and re[13] == 0x01
    assert (re[14], re[15], re[16]) == (9, 8, 7)
    # wave direction + speed byte
    wv = b('ext_static', 'wave', None, 0x1F, 0x05, direction=0x02)[0]
    assert (wv[10], wv[11], wv[12]) == (0x04, 0x02, 0x28)
    # std breathing single (0x03/0x0A, size 0x08, mode 0x01)
    sb = b('std_static', 'breathing', (1, 2, 3), 0xFF, 0x00)[0]
    assert (sb[6], sb[7]) == (0x03, 0x0A) and sb[5] == 0x08 and (sb[8], sb[9]) == (0x03, 0x01)
    assert (sb[10], sb[11], sb[12]) == (1, 2, 3)
    # DPI set: big-endian, VARSTORE (1600x800)
    sd = pr.set_dpi(1600, 800, 0xFF)[0]
    assert (sd[6], sd[7]) == (0x04, 0x05) and sd[8] == 0x01
    assert (sd[9], sd[10], sd[11], sd[12]) == (0x06, 0x40, 0x03, 0x20)
    # polling-rate set + validation
    assert pr.set_poll(500, 0xFF)[0][8] == 0x02
    try:
        pr.set_poll(333, 0xFF)                                 # only 1000/500/125
        assert False
    except ValueError:
        pass
    # query builders: class/id (+ serial data_size 0x16)
    assert (pr.q_firmware(0xFF)[6], pr.q_firmware(0xFF)[7]) == (0x00, 0x81)
    assert pr.q_serial(0xFF)[5] == 0x16 and pr.q_battery(0xFF)[6] == 0x07
    assert (pr.q_dpi(0xFF)[6], pr.q_dpi(0xFF)[7]) == (0x04, 0x85)
    # starlight (ext 0x0F/0x02 effect 0x07; std 0x03/0x0A mode 0x19)
    stl = b('ext_static', 'starlight', (7, 8, 9), 0x1F, 0x05, speed=2)[0]
    assert (stl[6], stl[7]) == (0x0F, 0x02) and stl[10] == 0x07 and stl[12] == 2
    assert (stl[14], stl[15], stl[16]) == (7, 8, 9)
    ssr = b('std_static', 'starlight', None, 0xFF, 0x00)[0]           # random on std matrix
    assert (ssr[6], ssr[7]) == (0x03, 0x0A) and ssr[8] == 0x19 and ssr[9] == 0x03
    try:
        b('custom', 'starlight', (1, 1, 1), 0x3F, 0x04)               # single-LED can't starlight
        assert False
    except NotImplementedError:
        pass
    # custom per-key frame: N set-row reports + one arm report
    rows = [(0, [(255, 0, 0), (0, 255, 0)]), (1, [(0, 0, 255)])]
    cf = pr.build_custom_frame('ext_static', rows, 0x1F, 0x05, True)
    assert len(cf) == 3 and (cf[0][6], cf[0][7]) == (0x0F, 0x03)      # 2 rows + arm; set-row cls/id
    assert (cf[0][10], cf[0][11], cf[0][12]) == (0, 0, 1)             # row, start_col, stop_col
    assert (cf[0][13], cf[0][14], cf[0][15]) == (255, 0, 0)           # first cell rgb @ arg5
    assert (cf[2][6], cf[2][7], cf[2][10]) == (0x0F, 0x02, 0x08)      # arm custom effect 0x08
    cfs = pr.build_custom_frame('std_static', rows, 0xFF, 0x00, False)
    assert (cfs[0][6], cfs[0][7]) == (0x03, 0x0B) and cfs[0][8] == 0xFF   # std set-row (0x03/0x0B)
    assert (cfs[-1][6], cfs[-1][7], cfs[-1][8], cfs[-1][9]) == (0x03, 0x0A, 0x05, 0x00)  # arm frame
    try:
        pr.build_custom_frame('logo', rows, 0xFF, 0x04, True)         # single-LED can't frame
        assert False
    except NotImplementedError:
        pass
    # HyperPolling (0x00/0x40), DPI stages (0x04/0x06), scroll modes, game/macro
    p2 = pr.set_poll2(8000, 0x1F)[0]
    assert (p2[6], p2[7]) == (0x00, 0x40) and p2[9] == 0x01
    try:
        pr.set_poll2(333, 0x1F)
        assert False
    except ValueError:
        pass
    ds = pr.set_dpi_stages([(400, 400), (1600, 900), (3200, 3200)], 2, 0x1F)[0]
    assert (ds[6], ds[7]) == (0x04, 0x06) and (ds[8], ds[9], ds[10]) == (0x01, 2, 3)   # varstore, active, count
    assert (ds[11], ds[12], ds[13], ds[14], ds[15]) == (1, 0x01, 0x90, 0x01, 0x90)     # stage1 = 400x400
    assert (ds[18], ds[19], ds[20]) == (2, 0x06, 0x40)                                 # stage2 x = 1600
    sm = pr.set_scroll_mode(1, 0x1F)[0]
    assert (sm[6], sm[7], sm[8], sm[9]) == (0x02, 0x14, 0x01, 0x01)
    assert pr.set_scroll_accel(True, 0x1F)[0][7] == 0x16 and pr.set_smart_reel(False, 0x1F)[0][9] == 0x00
    gm = pr.set_game_mode(True)[0]
    assert (gm[1], gm[6], gm[7]) == (0xFF, 0x03, 0x00) and (gm[8], gm[9], gm[10]) == (0x01, 0x08, 0x01)  # txn 0xFF, game LED on
    assert pr.set_macro_mode(False)[0][9] == 0x07                                      # macro LED id
    # analog driver mode (0x00/0x04, arg 0x03 on / 0x00 off) -- verified CRC 0x05 / 0x06
    am = pr.set_device_mode(True)[0]
    assert (am[1], am[5], am[6], am[7], am[8]) == (0xFF, 0x02, 0x00, 0x04, 0x03) and am[88] == 0x05
    assert pr.set_device_mode(False)[0][8] == 0x00 and pr.set_device_mode(False)[0][88] == 0x06
    # Razer Blade laptop (ported from razerctl, verified 1532:02b7): txn 0x1f, fan/perf/charge
    bp = pr.blade_perf(1)                                              # gaming, both fan zones, auto fan
    assert len(bp) == 2 and (bp[0][1], bp[0][6], bp[0][7]) == (0x1F, 0x0D, 0x02)
    assert (bp[0][8], bp[0][9], bp[0][10], bp[0][11]) == (0x01, 1, 1, 0x00) and bp[1][9] == 2
    bc = pr.blade_charge(80)
    assert (bc[0][6], bc[0][7], bc[0][8]) == (0x07, 0x12, 0xD0)        # 80 | 0x80
    assert (bc[1][6], bc[1][7], bc[1][8]) == (0x07, 0x0F, 0x02)        # required commit
    assert pr.blade_charge(0)[0][8] == 0x41                            # off
    assert (pr.q_blade_perf()[1], pr.q_blade_perf()[6], pr.q_blade_perf()[7]) == (0x1F, 0x0D, 0x82)
    assert (pr.q_blade_fan(1)[6], pr.q_blade_fan(1)[7]) == (0x0D, 0x88)
    assert (pr.q_blade_charge()[6], pr.q_blade_charge()[7]) == (0x07, 0x8F)
    assert drivers.get(0x02b7).name == 'Razer Blade 16 (2024)'        # verified model in registry
    # headset EQ: 64-byte "PA" packets (a different frame -- no CRC)
    pa = pr.eq_bands_report([-3, -3, -4, 0, 5, 5, 4, 1, 0, -1])
    assert len(pa) == 64 and (pa[0], pa[1], pa[2]) == (0x02, 0x80, 0x12)
    assert pa[5:7] == b'PA' and pa[7] == 0x08 and (pa[9], pa[10]) == (0x0D, 0x95)
    assert (pa[11], pa[12]) == (0x00, 0x0A) and pa[13] == 0xFD and pa[17] == 0x05  # -3 as u8; band5=+5
    seq = pr.build_eq_sequence(pr.EQ_PRESETS['game'])
    assert len(seq) == 6 and all(len(r) == 64 for r in seq)
    assert (seq[0][9], seq[0][10], seq[0][11]) == (0x02, 0xE1, 0x00)   # remote mode off first
    assert (seq[1][9], seq[1][10]) == (0x06, 0x01)                      # dsp config
    assert (seq[3][9], seq[3][10], seq[3][12]) == (0x04, 0x9E, 0x00)   # preset slot off -> custom bands
    try:
        pr.eq_bands_report([0] * 9)                                     # needs exactly 10 bands
        assert False
    except ValueError:
        pass
    assert drivers.get(0x0555).name == 'Razer BlackShark V2 Pro'
    # profiles + game watcher (pure parts -- no files, no device)
    assert settings.parse_row("Razer Viper Mini | 008a | static | ff1e00") == (0x8a, 'static', (255, 30, 0))
    assert settings.parse_row("008a spectrum") == (0x8a, 'spectrum', None)
    assert settings.parse_row("junk") is None
    from modules.watcher import match
    g = {'cs2.exe': 'fps', 'eldenring': 'rpg'}
    assert match({'cs2.exe', 'steam.exe'}, g) == 'fps'
    assert match({'eldenring.exe'}, g) == 'rpg'            # extension optional
    assert match({'notepad.exe'}, g) is None
    for rep in cf + cfs + [stl, ssr, p2, ds, sm, gm] + bp + bc:       # every new report: valid CRC
        c = 0
        for i in range(2, 88):
            c ^= rep[i]
        assert rep[88] == c
    print(f"selftest ok ({len(drivers.all_devices())} devices in registry)")
