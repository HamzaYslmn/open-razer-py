"""HID transport -- auto-selects the backend for the current OS.

Public API (identical on every platform):
  connected()            -> {pid: control_found_bool} for connected Razer devices
  control_paths(pid)     -> candidate device paths to send control reports to
  set_feature(path, rep) -> push one 90-byte report (raises OSError on failure)
  get_response(path, req) -> send a request report, read the 90-byte response

Windows uses the Win32 HID API (windows.py); Linux uses hidraw (linux.py).
"""

import sys

if sys.platform == 'win32':
    from .windows import connected, control_paths, get_response, set_feature
elif sys.platform.startswith('linux'):
    from .linux import connected, control_paths, get_response, set_feature
else:
    def connected():
        return {}

    def control_paths(pid):
        return []

    def set_feature(path, report):
        raise OSError(f"unsupported platform: {sys.platform} (Windows and Linux only)")

    def get_response(path, request):
        raise OSError(f"unsupported platform: {sys.platform} (Windows and Linux only)")


SUPPORTED = sys.platform == 'win32' or sys.platform.startswith('linux')

__all__ = ["connected", "control_paths", "set_feature", "get_response", "SUPPORTED"]
