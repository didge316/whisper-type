#!/usr/bin/env python3
"""whisper-type — F9 push-to-type voice-to-text daemon (v1).

Press F9 to start recording, press F9 again to stop, transcribe locally with a
whisper model, and type the text into the focused window via a virtual keyboard
(/dev/uinput). No clipboard — works on native Wayland.

Three proven pieces, wired together, no pynput:
  - f9_trigger   : F9 detector (evdev listener, passive, one press per physical press)
  - sdl_rec       : SDL2 mic recorder -> 16 kHz mono 16-bit WAV (standalone C binary)
  - uinput_type  : typer (evdev virtual keyboard on /dev/uinput)
  - whisper-cli   : transcription (CUDA, from whisper.cpp)

State machine:
    IDLE --F9--> RECORDING --F9--> TRANSCRIBING --done--> IDLE

Config via environment (see conf.env.example):
    WHISPER_DEVICE_ID  SDL capture device (default 0 = mic)
    WHISPER_RECORD_BIN recorder path
    WHISPER_MODEL      whisper model path
    WHISPER_BIN        whisper-cli path
    WHISPER_RAW        raw wav path (whisper writes <RAW>.json)
    WHISPER_DRY        non-empty -> print text instead of typing
"""
import os
import sys
import time
import json
import signal
import queue
import subprocess
from evdev import InputDevice, ecodes as e

# --- configuration -----------------------------------------------------------
DEVICE_ID = int(os.environ.get("WHISPER_DEVICE_ID", "0"))
RECORD_BIN = os.environ.get("WHISPER_RECORD_BIN",
                            os.path.expanduser("~/.local/bin/sdl_rec"))
MODEL = os.environ.get("WHISPER_MODEL",
                       "/home/matt/whisper.cpp/models/ggml-small.en.bin")
WHISPER_BIN = os.environ.get("WHISPER_BIN",
                             "/home/matt/whisper.cpp/build/bin/whisper-cli")
RAW = os.environ.get("WHISPER_RAW", "/tmp/whisper-rec.wav")
DRY = os.environ.get("WHISPER_DRY", "")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from f9_trigger import find_keyboards  # noqa: E402
from uinput_type import type_text  # noqa: E402

STATE_IDLE, STATE_RECORDING, STATE_TRANSCRIBING = 0, 1, 2


def log(msg):
    print(f"[whisper-type] {msg}", file=sys.stderr, flush=True)


def collapse_ws(text):
    return " ".join(text.split())


class WhisperType:
    def __init__(self):
        self.state = STATE_IDLE
        self.recorder = None          # subprocess.Popen of sdl_rec
        self.typing = False           # guard: block new F9 while typing
        self._stop = False
        self.f9q = queue.Queue()

        # pick the real keyboard (name contains "keyboard", has KEY_F9)
        kbs = find_keyboards()
        if not kbs:
            log("no keyboard with KEY_F9 found (check input-group access to /dev/input)")
            sys.exit(1)
        self.path, self.dev = kbs[0]
        log(f"using keyboard {self.path} ({self.dev.name})")

    # -- F9 listener (runs in a background thread) ---------------------------
    def _listen(self):
        log(f"listening for F9 on {self.path} ...")
        try:
            while not self._stop:
                event = self.dev.read_one()
                if event is None:
                    time.sleep(0.05)
                    continue
                if (event.type == e.EV_KEY
                        and event.code == e.KEY_F9
                        and event.value == 1):
                    self.f9q.put(True)
        except Exception as exc:  # noqa: BLE001
            log(f"listener error: {exc}")

    # -- recording -----------------------------------------------------------
    def _start_recording(self):
        os.makedirs(os.path.dirname(RAW) or "/", exist_ok=True)
        for p in (RAW, RAW + ".json"):
            try:
                os.unlink(p)
            except FileNotFoundError:
                pass
        log("recording ... (press F9 to stop)")
        self.recorder = subprocess.Popen(
            [RECORD_BIN, str(DEVICE_ID), "0", RAW],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self.state = STATE_RECORDING

    def _stop_recording(self):
        if not self.recorder or self.recorder.poll() is not None:
            return
        self.recorder.terminate()              # SIGTERM -> sdl_rec finalizes WAV
        try:
            self.recorder.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.recorder.kill()               # SIGKILL fallback (bad WAV, but stop capture)
            self.recorder.wait()
        self.recorder = None

    # -- transcription + typing ---------------------------------------------
    def _transcribe_and_type(self):
        try:
            if not os.path.exists(RAW):
                log("no wav produced by recorder; skipping")
                return
            log("transcribing ...")
            subprocess.run(
                [WHISPER_BIN, "-m", MODEL, "-f", RAW,
                 "-oj", "-nt", "-np", "-of", RAW],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                check=False,
            )
            text = ""
            jpath = RAW + ".json"
            if os.path.exists(jpath):
                try:
                    with open(jpath) as fh:
                        data = json.load(fh)
                    text = collapse_ws(
                        "".join(t.get("text", "")
                                for t in data.get("transcription", [])))
                except (json.JSONDecodeError, KeyError, AttributeError) as exc:
                    log(f"parse failed: {exc}")
            if not text:
                log("nothing transcribed")
                return
            if DRY:
                print(text)
                sys.stdout.flush()
                log(f"[dry-run] {text!r}")
            else:
                self.typing = True
                log(f"typing: {text!r}")
                type_text(text + " ")          # trailing space words don't stick
                self.typing = False
        except Exception as exc:               # never let a typing/transcribe
            log(f"transcribe/type failed: {exc}")  # failure kill the daemon
        finally:
            for p in (RAW, RAW + ".json"):
                try:
                    os.unlink(p)
                except FileNotFoundError:
                    pass

    def _handle_signal(self, *_a):
        # Do NOT sys.exit() here: it races queue.get() and raises on the lock.
        # Just flag shutdown; the main loop and listener both watch self._stop.
        self._stop = True
        self._stop_recording()

    # -- main loop -----------------------------------------------------------
    def run(self):
        import threading
        t = threading.Thread(target=self._listen, daemon=True)
        t.start()

        while not self._stop:
            try:
                self.f9q.get(timeout=0.2)
            except queue.Empty:
                continue

            if self.typing:
                continue                      # ignore F9 while typing

            try:
                if self.state == STATE_IDLE:
                    self._start_recording()
                elif self.state == STATE_RECORDING:
                    self._stop_recording()
                    self.state = STATE_TRANSCRIBING
                    self._transcribe_and_type()
                    self.state = STATE_IDLE
            except Exception as exc:               # belt-and-suspenders: one bad
                log(f"state-machine error: {exc}")      # F9 cycle must not crash us

        self._stop_recording()
        log("shutting down")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--list":
        for path, dev in find_keyboards():
            print(f"{path}  name={dev.name!r}")
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        # one full cycle for automated testing: record 2s, transcribe, print
        import subprocess as _sp
        os.makedirs(os.path.dirname(RAW) or "/", exist_ok=True)
        for p in (RAW, RAW + ".json"):
            try:
                os.unlink(p)
            except FileNotFoundError:
                pass
        _sp.run([RECORD_BIN, str(DEVICE_ID), "2", RAW],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _sp.run([WHISPER_BIN, "-m", MODEL, "-f", RAW, "-oj", "-nt", "-np", "-of", RAW],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with open(RAW + ".json") as fh:
            data = json.load(fh)
        print(collapse_ws("".join(t.get("text", "")
                                  for t in data.get("transcription", []))))
        return
    d = WhisperType()
    signal.signal(signal.SIGTERM, d._handle_signal)
    signal.signal(signal.SIGINT, d._handle_signal)
    d.run()


if __name__ == "__main__":
    main()
