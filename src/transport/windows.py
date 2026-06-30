"""Windows HID transport: find Razer collections and push feature reports.

The only OS-specific code in the project. Pure stdlib ctypes against hid.dll +
setupapi.dll -- no external libraries. The Razer control protocol rides on a HID
feature report; this module finds the right collection and sends 90-byte reports.
"""

import sys

RAZER_VID = 0x1532
CONTROL_FEATURE_LEN = 91  # Razer control collection: 90-byte report + 1 report-id byte


def _winapi():
    """Load the Win32 structs/functions we need. Returns a small namespace."""
    import ctypes
    from ctypes import wintypes
    ns = type('win', (), {})()
    ns.ctypes, ns.wintypes = ctypes, wintypes
    ns.setupapi = ctypes.WinDLL('setupapi', use_last_error=True)
    ns.hid = ctypes.WinDLL('hid', use_last_error=True)
    ns.kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("InterfaceClassGuid", GUID),
                    ("Flags", wintypes.DWORD), ("Reserved", ctypes.c_void_p)]

    class HIDD_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Size", wintypes.ULONG), ("VendorID", wintypes.USHORT),
                    ("ProductID", wintypes.USHORT), ("VersionNumber", wintypes.USHORT)]

    class HIDP_CAPS(ctypes.Structure):
        _fields_ = ([("Usage", wintypes.USHORT), ("UsagePage", wintypes.USHORT),
                     ("InputReportByteLength", wintypes.USHORT),
                     ("OutputReportByteLength", wintypes.USHORT),
                     ("FeatureReportByteLength", wintypes.USHORT),
                     ("Reserved", wintypes.USHORT * 17)] +
                    [(f, wintypes.USHORT) for f in (
                        "NumberLinkCollectionNodes", "NumberInputButtonCaps",
                        "NumberInputValueCaps", "NumberInputDataIndices",
                        "NumberOutputButtonCaps", "NumberOutputValueCaps",
                        "NumberOutputDataIndices", "NumberFeatureButtonCaps",
                        "NumberFeatureValueCaps", "NumberFeatureDataIndices")])

    ns.GUID, ns.IFACE, ns.ATTRS, ns.CAPS = (
        GUID, SP_DEVICE_INTERFACE_DATA, HIDD_ATTRIBUTES, HIDP_CAPS)

    ns.setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
    ns.setupapi.SetupDiGetClassDevsW.argtypes = [
        ctypes.POINTER(GUID), wintypes.LPCWSTR, wintypes.HWND, wintypes.DWORD]
    ns.setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
    ns.setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(GUID), wintypes.DWORD,
        ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
    ns.setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
    ns.setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA), ctypes.c_void_p,
        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    ns.setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]

    ns.kernel32.CreateFileW.restype = wintypes.HANDLE
    ns.kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    ns.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    ns.hid.HidD_GetHidGuid.argtypes = [ctypes.POINTER(GUID)]
    ns.hid.HidD_GetAttributes.restype = wintypes.BOOL
    ns.hid.HidD_GetAttributes.argtypes = [wintypes.HANDLE, ctypes.POINTER(HIDD_ATTRIBUTES)]
    ns.hid.HidD_GetPreparsedData.restype = wintypes.BOOL
    ns.hid.HidD_GetPreparsedData.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
    ns.hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
    ns.hid.HidP_GetCaps.restype = wintypes.LONG       # NTSTATUS
    ns.hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]
    ns.hid.HidD_SetFeature.restype = wintypes.BOOL
    ns.hid.HidD_SetFeature.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
    ns.hid.HidD_GetFeature.restype = wintypes.BOOL
    ns.hid.HidD_GetFeature.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]

    ns.INVALID = ctypes.c_void_p(-1).value
    return ns


def _open(w, path, access):
    h = w.kernel32.CreateFileW(path, access, 0x3, None, 3, 0, None)  # share R/W, OPEN_EXISTING
    return None if h in (None, 0, w.INVALID) else h


def find_devices(pid=None):
    """[(path, vid, pid, usage_page, feature_len)] for every Razer HID collection."""
    if sys.platform != 'win32':
        return []
    w = _winapi()
    c = w.ctypes
    guid = w.GUID()
    w.hid.HidD_GetHidGuid(c.byref(guid))
    hdev = w.setupapi.SetupDiGetClassDevsW(c.byref(guid), None, None, 0x12)  # PRESENT|DEVICEINTERFACE
    if not hdev or hdev == w.INVALID:
        return []
    out = []
    cb = 8 if c.sizeof(c.c_void_p) == 8 else 6   # SP_..._DETAIL_DATA cbSize quirk
    try:
        i = 0
        iface = w.IFACE()
        iface.cbSize = c.sizeof(w.IFACE)
        while w.setupapi.SetupDiEnumDeviceInterfaces(hdev, None, c.byref(guid), i, c.byref(iface)):
            i += 1
            req = w.wintypes.DWORD(0)
            w.setupapi.SetupDiGetDeviceInterfaceDetailW(hdev, c.byref(iface), None, 0, c.byref(req), None)
            if not req.value:
                continue
            buf = c.create_string_buffer(req.value)
            c.cast(buf, c.POINTER(w.wintypes.DWORD))[0] = cb
            if not w.setupapi.SetupDiGetDeviceInterfaceDetailW(hdev, c.byref(iface), buf, req.value, None, None):
                continue
            path = c.wstring_at(c.addressof(buf) + c.sizeof(w.wintypes.DWORD))  # DevicePath at offset 4
            h = _open(w, path, 0xC0000000) or _open(w, path, 0)  # RW, else metadata-only
            if not h:
                continue
            try:
                attrs = w.ATTRS()
                attrs.Size = c.sizeof(w.ATTRS)
                if not w.hid.HidD_GetAttributes(h, c.byref(attrs)) or attrs.VendorID != RAZER_VID:
                    continue
                if pid is not None and attrs.ProductID != pid:
                    continue
                usage_page = feat = 0
                pp = c.c_void_p()
                if w.hid.HidD_GetPreparsedData(h, c.byref(pp)):
                    caps = w.CAPS()
                    if w.hid.HidP_GetCaps(pp, c.byref(caps)) == 0x00110000:  # HIDP_STATUS_SUCCESS
                        usage_page, feat = caps.UsagePage, caps.FeatureReportByteLength
                    w.hid.HidD_FreePreparsedData(pp)
                out.append((path, attrs.VendorID, attrs.ProductID, usage_page, feat))
            finally:
                w.kernel32.CloseHandle(h)
    finally:
        w.setupapi.SetupDiDestroyDeviceInfoList(hdev)
    return out


def connected():
    """{pid: has_control_collection} for every connected Razer device."""
    seen = {}
    for _path, _vid, pid, _up, feat in find_devices():
        seen[pid] = seen.get(pid, False) or (feat == CONTROL_FEATURE_LEN)
    return seen


def control_paths(pid):
    """Device paths to send control reports to, control collection first."""
    devs = find_devices(pid)
    return [d[0] for d in devs if d[4] == CONTROL_FEATURE_LEN] or [d[0] for d in devs]


def set_feature(path, report):
    """HidD_SetFeature one 90-byte report (+ leading report-id byte) to a collection."""
    w = _winapi()
    c = w.ctypes
    # Windows blocks GENERIC_READ/WRITE opens on mouse/keyboard collections; fall back
    # to a zero-access handle -- HidD_SetFeature's IOCTL still works through it.
    h = _open(w, path, 0xC0000000) or _open(w, path, 0)
    if not h:
        raise OSError(f"cannot open {path} (another app holding it? close it and retry)")
    try:
        buf = bytearray(91)
        buf[0] = 0x00                # report id (Razer uses 0)
        buf[1:] = report
        cbuf = (c.c_char * len(buf)).from_buffer(buf)
        if not w.hid.HidD_SetFeature(h, cbuf, len(buf)):
            raise OSError(f"HidD_SetFeature failed (winerror {c.get_last_error()})")
    finally:
        w.kernel32.CloseHandle(h)


def get_response(path, request):
    """Send a request report, then read the device's 90-byte response (HidD_GetFeature)."""
    w = _winapi()
    c = w.ctypes
    h = _open(w, path, 0xC0000000) or _open(w, path, 0)
    if not h:
        raise OSError(f"cannot open {path}")
    try:
        sbuf = bytearray(91)
        sbuf[1:] = request
        scbuf = (c.c_char * 91).from_buffer(sbuf)
        if not w.hid.HidD_SetFeature(h, scbuf, 91):
            raise OSError(f"HidD_SetFeature failed (winerror {c.get_last_error()})")
        rbuf = bytearray(91)
        rcbuf = (c.c_char * 91).from_buffer(rbuf)
        if not w.hid.HidD_GetFeature(h, rcbuf, 91):
            raise OSError(f"HidD_GetFeature failed (winerror {c.get_last_error()})")
        return bytes(rbuf[1:])           # drop the leading report-id byte -> 90-byte response
    finally:
        w.kernel32.CloseHandle(h)
