#!/usr/bin/env python3
"""test_daemon_integration.py — drive the real daemon state machine.

Creates a virtual keyboard, points whisper_type.WhisperType at it, runs the
daemon (DRY mode -> prints instead of types), injects two F9 presses, and asserts
the state machine logs "recording" then "transcribing". Verifies the actual
F9 -> record -> F9 -> transcribe wiring end to end.

Needs /dev/uinput (input group) — skips otherwise. Run headless: no speech is
fed, so transcription is empty, but the state transitions still execute.
"""
import os
import sys
import time
import glob
import threading
from evdev import UInput, InputDevice, ecodes as e

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
import whisper_type  # noqa: E402

KEY_F9 = e.KEY_F9


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


def emit_f9(dev):
    dev.write(e.EV_KEY, KEY_F9, 1); dev.syn()
    dev.write(e.EV_KEY, KEY_F9, 0); dev.syn()


def main():
    if not uinput_ok():
        print("SKIP: /dev/uinput not accessible"); sys.exit(0)

    # capture log calls
    logs = []
    whisper_type.log = lambda m: logs.append(m)
    whisper_type.DRY = "1"          # print instead of type

    events = {e.EV_KEY: list(range(256))}
    ui = UInput(events=events, name="virtual-keyboard", bustype=e.BUS_HOST)
    dev_path = None
    for _ in range(60):
        dev_path = find_by_name("virtual-keyboard")
        if dev_path:
            break
        time.sleep(0.05)
    if not dev_path:
        ui.close(); print("FAIL: virtual-keyboard did not appear"); sys.exit(1)
    dev = InputDevice(dev_path)

    # point the daemon at our virtual keyboard
    whisper_type.find_keyboards = lambda: [(dev_path, dev)]
    d = whisper_type.WhisperType()

    t = threading.Thread(target=d.run, daemon=True)
    t.start()
    time.sleep(0.6)

    print("injecting F9 #1 (start record) ...")
    emit_f9(dev)
    time.sleep(0.8)
    if not any("recording" in m for m in logs):
        d._stop = True; t.join(timeout=3)
        ui.close(); print("FAIL: no 'recording' after F9 #1; logs:", logs); sys.exit(1)
    print("  ok: recording started")

    print("injecting F9 #2 (stop + transcribe) ...")
    emit_f9(dev)
    time.sleep(4)                   # transcription takes a few seconds
    if not any("transcribing" in m for m in logs):
        d._stop = True; t.join(timeout=3)
        ui.close(); print("FAIL: no 'transcribing' after F9 #2; logs:", logs); sys.exit(1)
    print("  ok: transcription executed")

    d._stop = True
    t.join(timeout=5)
    ui.close()
    print("logs:", logs)
    print("PASS")


if __name__ == "__main__":
    main()
