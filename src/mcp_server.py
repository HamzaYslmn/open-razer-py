"""Dep-free MCP server exposing RazerKit device control over stdio (JSON-RPC 2.0).

Lets Claude / AI agents change the mouse color, run effects, and read the
polling rate. Pure standard library -- no `mcp` package, no dependencies.

Run (stdio transport):  uv run python src/mcp_server.py
"""

import json
import sys

import drivers
from modules import core

SERVER = {"name": "razerkit", "version": "0.1.0"}

TOOLS = [
    {
        "name": "list_devices",
        "description": "List connected Razer devices with their polling rate (Hz).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "set_color",
        "description": "Set a solid RGB color on a Razer device (saved to onboard memory).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "color": {"type": "string",
                          "description": "color name (red, green, blue, white, off...) or hex like ff1e00 or 'r,g,b'"},
                "device": {"type": "string",
                           "description": "optional: list number, pid hex (008a), or 'all'. default: auto-detect"},
            },
            "required": ["color"],
        },
    },
    {
        "name": "set_effect",
        "description": "Run a built-in lighting effect on a Razer device.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "effect": {"type": "string", "enum": ["spectrum", "breathing", "wave", "off"]},
                "color": {"type": "string", "description": "optional color for 'breathing'"},
                "device": {"type": "string", "description": "optional device selector (number, pid, or 'all')"},
            },
            "required": ["effect"],
        },
    },
    {
        "name": "get_polling_rate",
        "description": "Read the polling rate (Hz) of a Razer device.",
        "inputSchema": {
            "type": "object",
            "properties": {"device": {"type": "string", "description": "optional device selector"}},
        },
    },
]


def _text(s, is_error=False):
    out = {"content": [{"type": "text", "text": s}]}
    if is_error:
        out["isError"] = True
    return out


def _apply_to(selector, action, rgb):
    lines = []
    for pid in core.select_targets(selector):
        label, _ = core.apply(pid, action, rgb)
        lines.append(f"set {label} -> {core.describe(action, rgb)}")
    return "\n".join(lines)


def _call(name, args):
    try:
        if name == "list_devices":
            devs = core.connected_list()
            if not devs:
                return _text("No Razer devices connected.")
            rows = []
            for pid, dname, ok in devs:
                hz = core.read_hz(pid) if ok else None
                rows.append(f"1532:{pid:04x}  {dname}" + (f"  {hz} Hz" if hz else ""))
            return _text("\n".join(rows))
        if name == "set_color":
            action, rgb = core.resolve_action(args["color"])
            return _text(_apply_to(args.get("device"), action, rgb))
        if name == "set_effect":
            action, rgb = core.resolve_action(args["effect"], args.get("color"))
            return _text(_apply_to(args.get("device"), action, rgb))
        if name == "get_polling_rate":
            rows = []
            for pid in core.select_targets(args.get("device")):
                hz = core.read_hz(pid)
                dev = drivers.get(pid)
                rows.append(f"{dev.name if dev else f'1532:{pid:04x}'}: {hz or 'unknown'} Hz")
            return _text("\n".join(rows))
        return _text(f"unknown tool: {name}", is_error=True)
    except (ValueError, KeyError, SystemExit) as e:
        return _text(str(e), is_error=True)


def _handle(msg):
    """Return a JSON-RPC response dict, or None for notifications."""
    method, mid = msg.get("method"), msg.get("id")
    if method == "initialize":
        pv = (msg.get("params") or {}).get("protocolVersion", "2024-11-05")
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": pv,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER,
        }}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = msg.get("params") or {}
        return {"jsonrpc": "2.0", "id": mid,
                "result": _call(params.get("name"), params.get("arguments") or {})}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method and method.startswith("notifications/"):
        return None                       # notifications get no reply
    if mid is not None:
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": -32601, "message": f"method not found: {method}"}}
    return None


def main():
    # Newline-delimited JSON-RPC over stdio. Keep stdout clean -- only protocol messages.
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = _handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
