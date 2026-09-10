#!/usr/bin/env python3
"""test_type_loopback.py — typer -> uinput keyboard reader, round-trip text.

Types a known string with uinput_type.type_text and reads it back from the
virtual keyboard, asserting every character round-trips (shift-aware). Uses a
single shared UInput device so the typer and reader see the same event stream.
"""
import os
import sys
import time
import glob
import threading
from evdev import UInput, InputDevice, ecodes as e

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
from uinput_type import type_text, BASE, SHIFTED

# code -> KEY_ name (evdev 2.0 has no evdev_keyname)
_KEYNAME = {getattr(e, n): n for n in dir(e) if n.startswith("KEY_")}
# KEY_ name -> unshifted char
KEY2CHAR = {name: ch for ch, name in BASE.items()}
KEY2CHAR.update({"KEY_" + d: d for d in "0123456789"})
KEY2CHAR.update({"KEY_" + c.upper(): c for c in "abcdefghijklmnopqrstuvwxyz"})
# unshifted char -> shifted char
CH2S = {base: ch for ch, (base, _) in SHIFTED.items()}


def uinput_ok():
    try:
        open("/dev/uinput", "w").close()
        return True
    except OSError:
        return False


def find_by_name(name):
    for p in sorted(glob.glob("/dev/input/event*")):
        try:
            if InputDevice(p).name == name:
                return p
        except Exception:
            continue
    return None


def decode(presses):
    out = []
    shift = False
    for code, val in presses:
        full = _KEYNAME.get(code, "")
        if full == "KEY_LEFTSHIFT":
            shift = val == 1
            continue
        if val != 1:
            continue
        ch = KEY2CHAR.get(full)
        if ch is None:
            continue
        if shift:
            ch = CH2S.get(ch, ch.upper() if ch.isalpha() else ch)
        out.append(ch)
        shift = False
    return "".join(out)


def main():
    target = "Build the daemon, then run the tests at 9am!"
    if not uinput_ok():
        print("SKIP: /dev/uinput not accessible (add user to 'input' group, or run with sudo)"); sys.exit(0)
    events = {e.EV_KEY: list(range(256))}
    ui = UInput(events=events, name="virtual-keyboard", bustype=e.BUS_HOST)
    dev_path = None
    for _ in range(60):
        dev_path = find_by_name("virtual-keyboard")
        if dev_path:
            break
        time.sleep(0.05)
    if not dev_path:
        ui.close()
        print("FAIL: virtual-keyboard did not appear (need /dev/uinput access)"); sys.exit(1)
    dev = InputDevice(dev_path)
    presses = []

    def reader():
        try:
            for ev in dev.read_loop():
                if ev.type == e.EV_KEY:
                    presses.append((ev.code, ev.value))
        except Exception:
            pass  # device closed at end of test

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    time.sleep(0.4)
    type_text(target, ui=ui)          # type into the SAME device we read from
    time.sleep(1.0)
    ui.close()

    got = decode(presses)
    print("target:", repr(target))
    print("got   :", repr(got))
    if got == target:
        print("PASS")
    else:
        print("FAIL: round-trip mismatch"); sys.exit(1)


if __name__ == "__main__":
    main()
