#!/usr/bin/env python3
"""F9 (push-to-type trigger) detector using evdev directly.

Reads raw key events from a keyboard device and reports the F9 PRESS
(value==1), ignoring auto-repeat (value==2) and release (value==0). Passive:
it only reads, so F9 also reaches the focused app (no consumption -> clean toggle).

Usage:
  f9_listen.py [device-path]   read from given /dev/input/eventN
  f9_listen.py --list          list keyboard devices with KEY_F9
  f9_listen.py                 auto-select first keyboard with KEY_F9

Prints "F9_PRESSED" to stdout on each F9 press. Exit on SIGINT/SIGTERM.
"""
import sys, time, signal
from evdev import InputDevice, ecodes as e

KEY_F9 = e.KEY_F9

def find_keyboards():
    """Return list of (path, InputDevice) for devices that emit KEY_F9."""
    import glob
    out = []
    for path in sorted(glob.glob('/dev/input/event*')):
        try:
            dev = InputDevice(path)
        except Exception:
            continue
        caps = dev.capabilities()
        has_f9 = any(KEY_F9 in codes for codes in caps.values())
        # Gaming mice expose a full HID keyboard interface (F-keys, space, 163 keys),
        # so capabilities can't tell them apart. The real keyboard's name contains
        # "keyboard"; mice say "Mouse". Prefer name, but require F9 too.
        if has_f9 and 'keyboard' in dev.name.lower():
            out.append((path, dev))
    return out

def _run(dev, label):
    print(f"{label}: {dev} ({dev.name}) listening for F9 ...", file=sys.stderr, flush=True)
    def _quit(*a):
        sys.exit(0)
    signal.signal(signal.SIGTERM, _quit)
    signal.signal(signal.SIGINT, _quit)
    while True:
        event = dev.read_one()
        if event is None:
            time.sleep(0.05)  # evdev opens nonblocking; avoid busy-spin
            continue
        if event.type == e.EV_KEY and event.code == KEY_F9 and event.value == 1:
            print("F9_PRESSED"); sys.stdout.flush()

def main():
    args = sys.argv[1:]
    if args == ['--list']:
        kbs = find_keyboards()
        if not kbs:
            print("no keyboard with KEY_F9 found", file=sys.stderr)
        for path, dev in kbs:
            print(f"{path}  name={dev.name!r}")
        return
    if args and args[0] != '--repeat':
        _run(InputDevice(args[0]), f"listening on {args[0]}")
        return
    kbs = find_keyboards()
    if not kbs:
        print("no keyboard with KEY_F9 found", file=sys.stderr); sys.exit(1)
    path, dev = kbs[0]
    _run(dev, f"auto-selected {path}")

if __name__ == "__main__":
    main()
