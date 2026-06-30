"""Set the color or run a built-in effect on any Razer device -- Windows/Linux, no deps.

Entry point only. The implementation is split across modules/ (core, menu, cli),
with device tables/protocol in drivers/ and the HID I/O in transport/.

    python src/main.py                  # menu app (real terminal) / device list (piped)
    python src/main.py red              # default device -> static red
    python src/main.py spectrum         # on-device animation
    python src/main.py breathing 00ff88 -d 2     # 2nd listed device
    python src/main.py red -d all       # every connected device
"""

from modules.cli import main

if __name__ == "__main__":
    main()
