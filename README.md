# open-razer-py

> Set your Razer mouse's RGB from the terminal — no extra software, no drivers, no background process.

![platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-blue)
![dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)
![python](https://img.shields.io/badge/python-3.14%2B-blue)
[![web app](https://img.shields.io/badge/web%20app-WebHID-10b981)](https://hamzayslmn.github.io/open-razer-py/)

I got really tired of the Razer app and other things always running in the background, so I wrote this small Python app. It talks to the device directly over USB-HID, sets the color, and exits.

> **No install at all?** There's also a **[browser version](https://hamzayslmn.github.io/open-razer-py/)** — same protocol over WebHID. Just open it in Chrome/Edge and click *Connect*. See [Browser app](#-browser-app-no-install).

## ✨ Why

- **Nothing runs in the background** — it sets the lighting and quits.
- **Zero dependencies** — pure Python standard library.
- **Windows & Linux** — picks the right HID backend automatically.
- **Saves to the mouse's onboard memory**, so the color sticks with no software running — including on the **Viper Mini**, where Razer hides this feature.

## 📦 Setup

Needs [uv](https://docs.astral.sh/uv/) — it brings its own Python, so there's nothing else to install.

**Windows**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
uv sync
```

**Linux / macOS**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync
```

`uv sync` sets up the venv and Python 3.14 (still zero dependencies).

## 🎨 Usage

```bash
uv run python src/main.py                 # list devices, or open the menu in a terminal
uv run python src/main.py red             # solid color (name, ff0000, or '255,0,0')
uv run python src/main.py spectrum        # on-device effect
uv run python src/main.py breathing 00ff88
uv run python src/main.py off             # solid black
uv run python src/main.py red -d all      # every connected Razer device
uv run python src/main.py -m              # interactive menu
```

`-d` picks a device by list number (`-d 2`), product id (`-d 008a`), or `all`. The color saves to onboard memory by default; add `--temp` to apply it just once.

## 🌐 Browser app (no install)

Don't want to install anything — not even Python? Open the **[web version](https://hamzayslmn.github.io/open-razer-py/)** in Chrome or Edge, click **Connect**, pick your device, and set colors/effects. It speaks the exact same Razer HID protocol from the browser via [WebHID](https://developer.mozilla.org/docs/Web/API/WebHID_API).

- Same 267-model table, same color/effect builders as the CLI.
- Runs entirely client-side — nothing is uploaded, no background process.
- Or run it locally: `python -m http.server` in the repo, then open `http://localhost:8000/frontend/`.

> Chrome blocks WebHID on *protected* (mouse/keyboard) HID collections, so a few devices whose control interface is a plain mouse collection may be refused by the browser — the app tells you when that happens. The CLI has no such restriction.

## 🔌 Device access

**Windows** — works out of the box. If other RGB software is running, close it first — it can re-apply its own profile and overwrite your color.

**Linux** — you need write access to `/dev/hidraw*`. Either run with `sudo`, or add a udev rule once:
```bash
echo 'SUBSYSTEM=="hidraw", ATTRS{idVendor}=="1532", MODE="0660", TAG+="uaccess"' \
  | sudo tee /etc/udev/rules.d/99-razer.rules
sudo udevadm control --reload && sudo udevadm trigger
```

## 🚀 Run at startup

Re-apply your saved colors at every logon (replays `settings.txt`):

**Windows** — no admin needed. Drops a hidden `RazerRGB.vbs` in your Startup folder; it appears in **Task Manager → Startup apps** as *RazerRGB*, where you can toggle it too.
```powershell
uv run python src/main.py --startup install
uv run python src/main.py --startup remove     # undo
```

**Linux** — no admin needed (adds a `~/.config/autostart` entry):
```bash
uv run python src/main.py --startup install
uv run python src/main.py --startup remove     # undo
```

## 🤖 MCP server (control it from Claude / AI agents)

A built-in [MCP](https://modelcontextprotocol.io) server lets Claude (or any MCP client) change your lighting — still **dep-free**, pure stdlib over stdio.

```bash
uv run python src/mcp_server.py
```

Tools: `list_devices`, `set_color`, `set_effect`, `get_polling_rate`. For **Claude Code**, the included [`.mcp.json`](.mcp.json) registers it automatically — open the project and approve the `razer-rgb` server when prompted (or run `/mcp`). Then just ask: *"set my mouse to ff1e00"*.

## 📝 Notes

Verified on the Razer Viper Mini; ~260 other models are included. Some may need a tweak — `--txn` / `--led` are there for tuning. Effects like `wave` need a multi-zone device; single-LED mice (Viper Mini) say so instead of doing nothing.
