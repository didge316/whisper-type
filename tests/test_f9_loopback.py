#!/usr/bin/env python3
"""test_f9_loopback.py — uinput keyboard -> f9_trigger, expect one F9_PRESSED.

Creates a virtual keyboard on /dev/uinput, runs f9_trigger against it, emits a
decoy 'A' then a single F9 press, and asserts the detector reports F9_PRESSED
exactly once (and ignores the decoy).
"""
import os
import sys
import time
import glob
import subprocess
from evdev import UInput, InputDevice, ecodes as e

HERE = os.path.dirname(os.path.abspath(__file__))
F9_TRIGGER = os.path.join(HERE, "..", "src", "f9_trigger.py")


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


def main():
    if not uinput_ok():
        print("SKIP: /dev/uinput not accessible (add user to 'input' group, or run with sudo)"); sys.exit(0)
    events = {e.EV_KEY: list(range(256))}
    with UInput(events=events, name="virtual-keyboard", bustype=e.BUS_HOST) as ui:
        dev_path = None
        for _ in range(60):
            dev_path = find_by_name("virtual-keyboard")
            if dev_path:
                break
            time.sleep(0.05)
        if not dev_path:
            print("FAIL: virtual-keyboard device did not appear (need /dev/uinput access)"); sys.exit(1)
        print("loopback device:", dev_path)

        p = subprocess.Popen(
            [sys.executable, F9_TRIGGER, dev_path],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        time.sleep(0.6)  # let the detector attach

        # decoy
        ui.write(e.EV_KEY, e.KEY_A, 1); ui.syn()
        ui.write(e.EV_KEY, e.KEY_A, 0); ui.syn()
        time.sleep(0.1)
        # F9 press + release (no hold -> no auto-repeat)
        ui.write(e.EV_KEY, e.KEY_F9, 1); ui.syn()
        ui.write(e.EV_KEY, e.KEY_F9, 0); ui.syn()
        time.sleep(0.4)

        p.terminate()
        try:
            out = p.communicate(timeout=5)[0]
        except subprocess.TimeoutExpired:
            p.kill(); out = p.communicate()[0]

        count = out.count("F9_PRESSED")
        print("F9_PRESSED count:", count)
        if count == 1:
            print("PASS")
        else:
            print("FAIL: expected exactly 1 F9_PRESSED"); sys.exit(1)


if __name__ == "__main__":
    main()
