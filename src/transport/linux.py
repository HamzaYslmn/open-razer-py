"""Linux HID transport: find Razer hidraw nodes and push feature reports.

Pure stdlib (glob + fcntl ioctl) -- no external libraries. Sends the Razer control
protocol as a HID feature report via HIDIOCSFEATURE on /dev/hidraw*.

Needs write access to /dev/hidraw* -> run with sudo, or install a udev rule:
  SUBSYSTEM=="hidraw", ATTRS{idVendor}=="1532", MODE="0660", TAG+="uaccess"
"""

import glob
import os

RAZER_VID = 0x1532


def _hidraws(pid=None):
    """[(path, pid)] for Razer hidraw nodes, optionally filtered by pid."""
    out = []
    for sysdir in sorted(glob.glob('/sys/class/hidraw/hidraw*')):
        try:
            with open(os.path.join(sysdir, 'device', 'uevent')) as f:
                uevent = f.read()
        except OSError:
            continue
        hid_id = next((ln.split('=', 1)[1] for ln in uevent.splitlines()
                       if ln.startswith('HID_ID=')), None)
        if not hid_id:
            continue
        parts = hid_id.split(':')           # e.g. 0003:00001532:0000008A
        if len(parts) != 3:
            continue
        vid, dpid = int(parts[1], 16), int(parts[2], 16)
        if vid == RAZER_VID and (pid is None or dpid == pid):
            out.append(('/dev/' + os.path.basename(sysdir), dpid))
    return out


def connected():
    """{pid: True} for every connected Razer device (control node found by trying)."""
    return {pid: True for _path, pid in _hidraws()}


def control_paths(pid):
    """Candidate hidraw nodes for a pid; only the vendor interface accepts the report."""
    return [path for path, _ in _hidraws(pid)]


def _hidiocsfeature(length):
    # _IOC(dir=READ|WRITE=3, type='H', nr=0x06, size=len)
    return (3 << 30) | (length << 16) | (ord('H') << 8) | 0x06


def set_feature(path, report):
    """HIDIOCSFEATURE one 90-byte report (+ leading report-id byte) to a hidraw node."""
    import fcntl
    buf = bytearray(91)
    buf[0] = 0x00                # report id (Razer uses 0)
    buf[1:] = report
    op = _hidiocsfeature(len(buf))
    if op >= 1 << 31:           # fcntl.ioctl wants a signed C int on some builds
        op -= 1 << 32
    fd = os.open(path, os.O_RDWR)
    try:
        fcntl.ioctl(fd, op, buf, True)
    finally:
        os.close(fd)


def _hidiocgfeature(length):
    return (3 << 30) | (length << 16) | (ord('H') << 8) | 0x07


def get_response(path, request):
    """Send a request report (SFEATURE), then read the 90-byte response (GFEATURE)."""
    import fcntl
    fd = os.open(path, os.O_RDWR)
    try:
        sbuf = bytearray(91)
        sbuf[1:] = request
        ops, opg = _hidiocsfeature(91), _hidiocgfeature(91)
        if ops >= 1 << 31:
            ops -= 1 << 32
        if opg >= 1 << 31:
            opg -= 1 << 32
        fcntl.ioctl(fd, ops, sbuf, True)
        rbuf = bytearray(91)
        fcntl.ioctl(fd, opg, rbuf, True)
        return bytes(rbuf[1:])
    finally:
        os.close(fd)
