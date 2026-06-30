"""Device registry: look up any Razer device by USB product id.

Device kinds live one-per-module (mouse, keyboard, headset, accessory), each a
generated DEVICES table. This package aggregates them so the rest of the tool
never cares which category a pid is in.
"""
from collections import namedtuple

from . import accessory, headset, keyboard, mouse
from .protocol import ACTIONS, build

Device = namedtuple("Device", "pid name category method txn led")

DEFAULT_PID = 0x008A   # Razer Viper Mini (wired) -- the verified default target

_CATEGORIES = {"mouse": mouse, "keyboard": keyboard,
               "headset": headset, "accessory": accessory}

_BY_PID = {}
for _cat, _mod in _CATEGORIES.items():
    for _pid, _name, _method, _txn, _led in _mod.DEVICES:
        _BY_PID[_pid] = Device(_pid, _name, _cat, _method, _txn, _led)


def get(pid):
    """Return the Device for a USB product id, or None if unknown."""
    return _BY_PID.get(pid)


def all_devices():
    """Every known Device, sorted by category then pid."""
    return sorted(_BY_PID.values(), key=lambda d: (d.category, d.pid))


__all__ = ["Device", "DEFAULT_PID", "ACTIONS", "get", "all_devices", "build"]
