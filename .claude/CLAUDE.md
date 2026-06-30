# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A zero-dependency, stdlib-only Python tool to set the RGB color on any Razer
device on **Windows or Linux**, by speaking the Razer USB-HID protocol directly
— no external dependencies. The transport auto-selects the Win32 HID API
or Linux hidraw by platform. Verified on a Razer Viper Mini (1532:008a) on Windows.

## Commands

Args were deliberately kept few. Everyday surface is just `action` + `-d`.

- No args: menu app on a real terminal, else the numbered device list.
- Static color: `main.py red` — or `ff1e00`, `'0,128,255'`, `off` (off = solid black `000000`, not the `none` effect).
- On-device effect: `main.py spectrum` | `breathing 00ff88`. (`wave` needs a *multi-zone* device — single-LED mice like the Viper Mini raise a clear error.)
- `-d SEL` picks the device: a **list number** (`-d 2`), a **pid hex** (`-d 008a`), or **`all`**. Omit it to auto-pick: the default (Viper Mini) if present, else the sole connected device, else it asks. See `core.select_targets`.
- `-m` (or `-i`) opens the menu. `--temp` applies once (no onboard memory, no `settings.txt`). `--txn`/`--led` are advanced per-call tuning knobs. `--models` lists every known model; `--selftest` self-checks.
- **Startup**: any apply records itself into `settings.txt`. `--startup apply` replays it (what the logon launcher runs — keep that flag and the launcher command strings in sync); `--startup install` / `remove` register/remove it — **no admin** on either OS. Windows writes a hidden `RazerRGB.vbs` **directly in the user's Startup folder** (runs `pythonw main.py --startup apply`, window style 0). It's a *bare file*, not a shortcut, on purpose: Task Manager labels a Startup-folder shortcut by its target program (so a `.lnk → pythonw` shows "Python", and `.lnk → some.vbs` shows the target's full path), but a bare file is labelled by its filename → "RazerRGB". A custom Task Manager icon isn't achievable for a script-based launcher without packaging an `.exe`, so there's no logo there by design. Linux writes a `~/.config/autostart` entry.

Targets Python `>=3.14`. No test framework — `--selftest` is the regression check (report layout, CRC, per-method/effect builders, the VARSTORE/NOSTORE flag, action parsing, registry sanity). Run it after touching `drivers/protocol.py` or the tables.

## Layout

`src/main.py` is a ~15-line launcher (`from modules.cli import main`). The real work is in three packages:

- `src/modules/` — the **app logic**, split by concern: `core.py` (color/action parsing, `apply()`, `select_targets()` — no UI), `menu.py` (the terminal menu app + `list_connected`), `settings.py` (`settings.txt` read/write + `install_startup`/`uninstall_startup`), `cli.py` (argparse `main()` + `_selftest`). Import direction is one-way: `cli → {menu, settings} → core`. `settings.txt` lives in `docs/` (gitignored) as an aligned, human-readable table — one row per device: `device | pid | action | color` (color is hex or `-`). All settings/startup paths are anchored to `main.py` (`settings._main_py()`), not the cwd; on install it seeds the file with `drivers.DEFAULT_PID`. `load()` also still accepts the older `pid action color` whitespace form; the name column is informational (pid is the key).
- `src/transport/` — the **HID I/O**, the only OS-specific code. `__init__.py` dispatches by `sys.platform` to `windows.py` (ctypes against `hid.dll` + `setupapi.dll`) or `linux.py` (hidraw + `HIDIOCSFEATURE` ioctl via `fcntl`). Both expose the same API: `connected()`, `control_paths(pid)`, `set_feature(path, report)`, `get_response(path, request)` (send a request, read the 90-byte reply — used by `core.read_hz`), plus the `SUPPORTED` flag. Linux needs write access to `/dev/hidraw*` (sudo or a udev rule — see `linux.py`).
- `src/drivers/` — everything device-related:
  - `protocol.py` — the 90-byte report builder + `build(method, action, rgb, txn, led, store)`. `action` ∈ `static/off/spectrum/breathing/wave`; `store=True` sets **VARSTORE** (persist to onboard memory), `store=False` **NOSTORE** (volatile). Animations map per method via `_FAMILY` (`custom`/`logo` mice animate through their logo LED's CLASSIC effects; `ext`/`std` use the matrix effect commands).
  - `mouse.py` / `keyboard.py` / `headset.py` / `accessory.py` — generated `DEVICES` tables, one row per model: `(pid, name, method, txn, led)`.
  - `__init__.py` — registry: `get(pid)` resolves any pid to a `Device` across all categories; `all_devices()`; `DEFAULT_PID`.
- `src/mcp_server.py` — a **dep-free MCP server** (JSON-RPC 2.0 over stdio, pure stdlib — no `mcp` package) exposing `list_devices` / `set_color` / `set_effect` / `get_polling_rate`, calling straight into `core`. Registered for Claude Code via `.mcp.json` at the repo root (project-scoped MCP config does NOT go in `.claude/settings.json`). Keep stdout clean — only protocol JSON, never `print()`.

## Protocol / method model

Every command is a fixed **90-byte "razer report"** (`razer_report()`): `[1]`=transaction id, `[5]`=data_size, `[6]`=command_class, `[7]`=command_id, `[8..87]`=arguments, `[88]`=CRC = **XOR of bytes 2..87**. Wrong offsets → the device silently ignores it.

A device's **`method`** is how a solid color is set — these are the only behaviours that differ across ~267 models:
- `ext_static` — extended-matrix static (`0x0F/0x02`, effect `0x01`). Most modern devices.
- `std_static` — standard-matrix static (`0x03/0x0A`, effect `0x06`). Older keyboards.
- `custom` — single-LED logo mice (**Viper Mini**). Static and all animations route through the **extended-matrix** family on `LOGO_LED` (`led=0x04`), txn `0x3f` (breathing `0xff`) — `_STATIC['custom']` and `_FAMILY['custom']` both point at `ext`. Static uses VARSTORE so the color is **stored on-device**. The old volatile custom-frame builder (`_custom_static`, `0x0F/0x03`+`0x0F/0x02` effect `0x08`) is kept but unused. (Razer firmware still may not persist lighting across a power-cycle — that's what `--startup` works around.)
- `logo` — standard LED on `LOGO_LED` (`0x03/0x01` rgb + `0x03/0x02` effect + `0x03/0x00` on). Older single-zone mice.
- `kraken` — headsets use a different report protocol; `build` raises `NotImplementedError` (honest "not implemented" rather than a wrong report).

`transaction_id` and `led` vary per device; a handful may need tuning — that's what `--txn`/`--led` are for. `custom`/`ext_static`/`txn 0x3f` is the safe default for an unknown pid.

## Transport specifics (the non-obvious parts)

Both backends send the same buffer: a leading report-id byte `0x00` + the 90-byte report (91 total), and try `control_paths()` in order until one collection accepts it.

**Windows** (`windows.py`):
- `find_devices()` enumerates HID collections via `setupapi.dll`, reading VID/PID + `HIDP_CAPS`. Mind the `SP_DEVICE_INTERFACE_DETAIL_DATA` `cbSize` quirk (8 on 64-bit, 6 on 32-bit; DevicePath at byte offset 4 regardless).
- The control protocol lives on the collection with a **91-byte feature report** — `CONTROL_FEATURE_LEN`. On the Viper Mini that's `mi_00`. Usage page is not a reliable selector (this device reports `0x0001`, not `0xff00`).
- That collection is a mouse collection, so Windows **refuses `GENERIC_READ/WRITE` opens**; `set_feature` falls back to a **zero-access handle**, through which `HidD_SetFeature`'s IOCTL still works.

**Linux** (`linux.py`):
- Finds nodes by scanning `/sys/class/hidraw/*/device/uevent` for `HID_ID=...:00001532:<pid>`; sends via `HIDIOCSFEATURE` ioctl. A device has several hidraw nodes — only the vendor interface accepts the report, so `control_paths` returns all of them and `set_color` tries each.
- Needs write access to `/dev/hidraw*` (root, or a `1532` udev rule with `TAG+="uaccess"`).

**Other RGB software**, if running, can re-apply its profile and overwrite the color — close it for changes to stick. There is no "Viper Mini V2"; that name is a mix-up for the Viper Mini (`008a`).
