# Build Prompt: Whisper-Type — Push-to-Type Voice-to-Text Daemon

> Copy-paste this entire prompt into another agent on a fresh machine. Build in order.

## Context

Build a Linux daemon: press a key → record → press again → transcribe locally → type text into focused window. No clipboard, no network, all local. Uses `evdev` directly (not `pynput`), `sdl_rec` (C/SDL2) for audio capture, `whisper.cpp` (CUDA) for transcription, `/dev/uinput` for typing.

---

## Stage 0 — Prerequisites

```bash
sudo apt update
sudo apt install -y build-essential gcc libSDL2-dev
python3 -m venv ~/.local/share/vox-venv
~/.local/share/vox-venv/bin/pip install --upgrade pip evdev>=2.0
```

---

## Stage 1 — Build whisper.cpp

```bash
cd ~
git clone https://github.com/ggerganov/whisper.cpp
cd whisper.cpp
cmake -B build -DGGML_CUDA=ON
cmake --build build --release -j$(nproc)
mkdir -p ~/whisper.cpp/models
# Download model (small.en ~50MB file, ~487MB VRAM)
wget https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.en.bin -O ~/whisper.cpp/models/ggml-small.en.bin
```

Test:
```bash
~/whisper.cpp/build/bin/whisper-cli --help 2>&1 | head -3
# Should show help with CUDA support
```

---

## Stage 2 — Build the SDL2 recorder

Create `recorder/sdl_rec.c` and `recorder/build.sh` (see files below).

```bash
chmod +x recorder/build.sh
recorder/build.sh
```

Test:
```bash
timeout -s TERM 3 bin/sdl_rec 0 0 /tmp/test.wav
soxi /tmp/test.wav   # should show 16kHz mono 16-bit
bin/sdl_rec --list   # note your mic's device index
```

---

## Stage 3 — udev rules and group (REQUIRED, log out/in after)

```bash
sudo modprobe uinput
echo uinput | sudo tee /etc/modules-load.d/uinput.conf
sudo tee /etc/udev/rules.d/99-uinput.rules >/dev/null <<'EOF'
KERNEL=="uinput", GROUP="input", MODE="0660"
EOF
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=misc
sudo usermod -aG input "$USER"
```

**LOG OUT AND BACK IN.** This is mandatory — group membership only takes effect at login.

Verify: `id` should list "input"; `ls -la /dev/uinput` should show `root:input 0660`.

---

## Stage 4 — Write all source files

### `src/f9_trigger.py`

```python
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
import os, sys, time, signal
from evdev import InputDevice, ecodes as e

_TRIGGER_KEY = os.environ.get("WHISPER_TRIGGER_KEY", "KEY_F9").strip()
if _TRIGGER_KEY.startswith("e."):
    _TRIGGER_KEY = _TRIGGER_KEY[2:]
KEY_TRIGGER = getattr(e, _TRIGGER_KEY, e.KEY_F9)
KEY_TRIGGER_NAME = _TRIGGER_KEY

def find_keyboards():
    """Return list of (path, InputDevice) for devices that emit the trigger key."""
    import glob
    out = []
    for path in sorted(glob.glob('/dev/input/event*')):
        try:
            dev = InputDevice(path)
        except Exception:
            continue
        caps = dev.capabilities()
        has_trigger = any(KEY_TRIGGER in codes for codes in caps.values())
        if has_trigger and 'keyboard' in dev.name.lower():
            out.append((path, dev))
    return out

def _run(dev, label):
    print(f"{label}: {dev} ({dev.name}) listening for {KEY_TRIGGER_NAME} ...", file=sys.stderr, flush=True)
    def _quit(*a):
        sys.exit(0)
    signal.signal(signal.SIGTERM, _quit)
    signal.signal(signal.SIGINT, _quit)
    while True:
        event = dev.read_one()
        if event is None:
            time.sleep(0.05)
            continue
        if event.type == e.EV_KEY and event.code == KEY_TRIGGER and event.value == 1:
            print(f"{KEY_TRIGGER_NAME}_PRESSED"); sys.stdout.flush()

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
        print(f"no keyboard with {KEY_TRIGGER_NAME} found", file=sys.stderr); sys.exit(1)
    path, dev = kbs[0]
    _run(dev, f"auto-selected {path} for {KEY_TRIGGER_NAME}")

if __name__ == "__main__":
    main()
```

### `src/uinput_type.py`

```python
#!/usr/bin/env python3
"""Minimal uinput typer: types text into the focused window via a virtual
keyboard written to /dev/uinput. No pynput, no X, no dumpkeys. Reaches native
Wayland apps directly."""
import sys, time
from evdev import UInput, ecodes as e

SHIFT = e.KEY_LEFTSHIFT

BASE = {
    ' ': 'KEY_SPACE', '.': 'KEY_DOT', ',': 'KEY_COMMA', '/': 'KEY_SLASH',
    '-': 'KEY_MINUS', '=': 'KEY_EQUAL', ';': 'KEY_SEMICOLON', "'": 'KEY_APOSTROPHE',
    '`': 'KEY_GRAVE', '\\': 'KEY_BACKSLASH', '[': 'KEY_LEFTBRACE',
    ']': 'KEY_RIGHTBRACE',
}
SHIFTED = {
    '!': ('1', True), '@': ('2', True), '#': ('3', True), '$': ('4', True),
    '%': ('5', True), '^': ('6', True), '&': ('7', True), '*': ('8', True),
    '(': ('9', True), ')': ('0', True), '_': ('-', True), '+': ('=', True),
    ':': (';', True), '"': ("'", True), '~': ('`', True), '|': ('\\', True),
    '<': (',', True), '>': ('.', True), '?': ('/', True),
}
_BASE_NAME = {ch: name for ch, name in BASE.items()}

def _resolve(ch):
    if ch.isascii() and ch.isdigit():
        return 'KEY_' + ch
    if ch.isalpha():
        return 'KEY_' + ch.upper()
    return _BASE_NAME.get(ch, 'KEY_' + ch.upper())

def keyname_for(ch):
    if ch in SHIFTED:
        base, need_shift = SHIFTED[ch]
        return _resolve(base), need_shift
    if ch in BASE:
        return BASE[ch], False
    if ch.isascii() and ch.isdigit():
        return 'KEY_' + ch, False
    if ch.isascii() and ch.isalpha():
        return 'KEY_' + ch.upper(), ch.isupper()
    return None, False

def type_text(text, gap=0.015, ui=None):
    created = ui is None
    if created:
        events = {e.EV_KEY: list(range(256))}
        ui = UInput(events=events, name='virtual-keyboard', bustype=e.BUS_HOST)
    try:
        time.sleep(0.3)  # let compositor attach the uinput device
        for ch in text:
            name, need_shift = keyname_for(ch)
            if name is None:
                continue
            code = getattr(e, name)
            if need_shift:
                ui.write(e.EV_KEY, SHIFT, 1); ui.syn()
            ui.write(e.EV_KEY, code, 1); ui.syn()
            ui.write(e.EV_KEY, code, 0); ui.syn()
            if need_shift:
                ui.write(e.EV_KEY, SHIFT, 0); ui.syn()
            time.sleep(gap)
    finally:
        if created:
            ui.close()

if __name__ == "__main__":
    msg = " ".join(sys.argv[1:]) or "uinput typer ok"
    type_text(msg)
    sys.stderr.write(f"typed: {msg!r}\n")
```

### `src/whisper_type.py`

```python
#!/usr/bin/env python3
"""whisper-type — F9 push-to-type voice-to-text daemon.
State machine: IDLE --F9--> RECORDING --F9--> TRANSCRIBING --done--> IDLE
Config via environment variables (see conf.env.example)."""
import os, sys, time, json, signal, queue, subprocess
from evdev import InputDevice, ecodes as e

HERE = os.path.dirname(os.path.abspath(__file__))

RECORD_BIN = os.environ.get("WHISPER_RECORD_BIN",
                            os.path.normpath(os.path.join(HERE, "..", "bin", "sdl_rec")))
MODEL = os.environ.get("WHISPER_MODEL",
                       os.path.expanduser("~/whisper.cpp/models/ggml-small.en.bin"))
WHISPER_BIN = os.environ.get("WHISPER_BIN",
                             os.path.expanduser("~/whisper.cpp/build/bin/whisper-cli"))
RAW = os.environ.get("WHISPER_RAW", "/tmp/whisper-rec.wav")
DRY = os.environ.get("WHISPER_DRY", "")
_TRIGGER_KEY = os.environ.get("WHISPER_TRIGGER_KEY", "KEY_F9").strip()
if _TRIGGER_KEY.startswith("e."):
    _TRIGGER_KEY = _TRIGGER_KEY[2:]
TRIGGER_KEY = getattr(e, _TRIGGER_KEY, e.KEY_F9)
VOCAB = os.environ.get("WHISPER_VOCAB", os.path.normpath(os.path.join(HERE, "..", "vocab.txt")))
_USER_PROMPT = os.environ.get("WHISPER_PROMPT", "").strip()
if _USER_PROMPT:
    PROMPT = _USER_PROMPT
elif VOCAB and os.path.isfile(VOCAB) and open(VOCAB).read().strip():
    _terms = [w.strip() for w in open(VOCAB).read().split() if w.strip()]
    PROMPT = "context: technical terms are " + " ".join(_terms)
else:
    PROMPT = ""

def _score_device_name(name):
    n = name.lower()
    s = 0
    if "microphone" in n or "mic" in n: s += 10
    if "headset" in n or "headphone" in n: s += 8
    if "h390" in n or "logitech" in n: s += 5
    if "input" in n or "capture" in n: s += 3
    return s

def detect_device_id():
    try:
        out = subprocess.run([RECORD_BIN, "--list"], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return 0
    best_idx, best_score = 0, 0
    for line in out.splitlines():
        line = line.strip()
        if ":" not in line: continue
        idx_s, _, name = line.partition(":")
        try:
            idx = int(idx_s.strip())
        except ValueError: continue
        score = _score_device_name(name)
        if score > best_score:
            best_score, best_idx = score, idx
    return best_idx

def resolve_device_id():
    raw = os.environ.get("WHISPER_DEVICE_ID", "").strip()
    if raw:
        try: return int(raw)
        except ValueError: log(f"invalid WHISPER_DEVICE_ID={raw!r}, auto-detecting")
    return detect_device_id()

sys.path.insert(0, HERE)
from f9_trigger import find_keyboards  # noqa: E402
from uinput_type import type_text  # noqa: E402

def log(msg):
    print(f"[whisper-type] {msg}", file=sys.stderr, flush=True)

def check_recorder():
    if not (os.path.exists(RECORD_BIN) and os.access(RECORD_BIN, os.X_OK)):
        sys.exit(f"recorder not found at {RECORD_BIN}\n  build it first: recorder/build.sh")

STATE_IDLE, STATE_RECORDING, STATE_TRANSCRIBING = 0, 1, 2

def collapse_ws(text):
    return " ".join(text.split())

class WhisperType:
    def __init__(self):
        self.state = STATE_IDLE
        self.recorder = None
        self.typing = False
        self._stop = False
        self.f9q = queue.Queue()
        kbs = find_keyboards()
        if not kbs:
            log("no keyboard with KEY_F9 found (check input-group access to /dev/input)")
            sys.exit(1)
        self.path, self.dev = kbs[0]
        log(f"using keyboard {self.path} ({self.dev.name})")
        self.device_id = resolve_device_id()
        if os.environ.get("WHISPER_DEVICE_ID", "").strip():
            log(f"using SDL capture device {self.device_id} (from config)")
        else:
            log(f"auto-detected SDL capture device {self.device_id}")

    def _listen(self):
        log(f"listening for {os.environ.get('WHISPER_TRIGGER_KEY', 'KEY_F9')} on {self.path} ...")
        try:
            while not self._stop:
                event = self.dev.read_one()
                if event is None:
                    time.sleep(0.05)
                    continue
                if event.type == e.EV_KEY and event.code == TRIGGER_KEY and event.value == 1:
                    self.f9q.put(True)
        except Exception as exc:
            log(f"listener error: {exc}")

    def _start_recording(self):
        os.makedirs(os.path.dirname(RAW) or "/", exist_ok=True)
        for p in (RAW, RAW + ".json"):
            try: os.unlink(p)
            except FileNotFoundError: pass
        log("recording ... (press F9 to stop)")
        self.recorder = subprocess.Popen([RECORD_BIN, str(self.device_id), "0", RAW],
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.state = STATE_RECORDING

    def _stop_recording(self):
        if not self.recorder or self.recorder.poll() is not None: return
        self.recorder.terminate()
        try: self.recorder.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.recorder.kill(); self.recorder.wait()
        self.recorder = None

    def _transcribe_and_type(self):
        try:
            if not os.path.exists(RAW):
                log("no wav produced by recorder; skipping"); return
            log("transcribing ...")
            cmd = [WHISPER_BIN, "-m", MODEL, "-f", RAW, "-oj", "-nt", "-np", "-of", RAW]
            if PROMPT: cmd += ["--prompt", PROMPT]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            text = ""
            jpath = RAW + ".json"
            if os.path.exists(jpath):
                try:
                    with open(jpath) as fh:
                        data = json.load(fh)
                    text = collapse_ws("".join(t.get("text", "") for t in data.get("transcription", [])))
                except (json.JSONDecodeError, KeyError, AttributeError) as exc:
                    log(f"parse failed: {exc}")
            if not text:
                log("nothing transcribed"); return
            if DRY:
                print(text); sys.stdout.flush(); log(f"[dry-run] {text!r}")
            else:
                self.typing = True
                log(f"typing: {text!r}")
                type_text(text + " ")
                self.typing = False
        except Exception as exc:
            log(f"transcribe/type failed: {exc}")
        finally:
            for p in (RAW, RAW + ".json"):
                try: os.unlink(p)
                except FileNotFoundError: pass

    def _handle_signal(self, *_a):
        self._stop = True
        self._stop_recording()

    def run(self):
        import threading
        t = threading.Thread(target=self._listen, daemon=True)
        t.start()
        while not self._stop:
            try:
                self.f9q.get(timeout=0.2)
            except queue.Empty:
                continue
            if self.typing: continue
            try:
                if self.state == STATE_IDLE:
                    self._start_recording()
                elif self.state == STATE_RECORDING:
                    self._stop_recording()
                    self.state = STATE_TRANSCRIBING
                    self._transcribe_and_type()
                    self.state = STATE_IDLE
            except Exception as exc:
                log(f"state-machine error: {exc}")
        self._stop_recording()
        log("shutting down")

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--list":
        for path, dev in find_keyboards():
            print(f"{path}  name={dev.name!r}")
        return
    check_recorder()
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        import subprocess as _sp
        os.makedirs(os.path.dirname(RAW) or "/", exist_ok=True)
        for p in (RAW, RAW + ".json"):
            try: os.unlink(p)
            except FileNotFoundError: pass
        dev_id = resolve_device_id()
        _sp.run([RECORD_BIN, str(dev_id), "2", RAW], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _sp.run([WHISPER_BIN, "-m", MODEL, "-f", RAW, "-oj", "-nt", "-np", "-of", RAW],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with open(RAW + ".json") as fh:
            data = json.load(fh)
        print(collapse_ws("".join(t.get("text", "") for t in data.get("transcription", []))))
        return
    d = WhisperType()
    signal.signal(signal.SIGTERM, d._handle_signal)
    signal.signal(signal.SIGINT, d._handle_signal)
    d.run()

if __name__ == "__main__":
    main()
```

### `vocab.txt`

```
# One technical term per line. Folded into whisper context prompt.
herdr
pane
brave-browser
Tyneham
```

---

## Stage 5 — Write scripts

### `scripts/run.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(cd "$(dirname "$0")/.." && pwd)"
export PATH="$HOME/.local/share/vox-venv/bin:$PATH"
PYTHON="${WHISPER_PYTHON:-$HOME/.local/share/vox-venv/bin/python}"
if [ -f conf.env ]; then set -a; . ./conf.env; set +a; fi
exec "$PYTHON" src/whisper_type.py
```

### `scripts/autostart.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
dir="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$HOME/.config/systemd/user"
ln -sf "$dir/systemd/whisper-type.service" "$HOME/.config/systemd/user/whisper-type.service"
systemctl --user daemon-reload
systemctl --user enable --now whisper-type.service
echo "whisper-type enabled."
```

### `systemd/whisper-type.service`

```ini
[Unit]
Description=whisper-type F9 push-to-type
Documentation=file://%h/AI/whisper/v1/README.md
After=graphical-session.target

[Service]
Type=simple
ExecStart=%h/AI/whisper/v1/scripts/run.sh
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
```

### `scripts/99-whisper-resume` — CRITICAL: restart daemon on wake from sleep

```bash
#!/bin/bash
# After wake from suspend, whisper.cpp's CUDA audio decode can fail due to
# stale GPU context, producing blank transcriptions. This hook restarts the
# daemon to restore a fresh CUDA context.
case "$1" in
    post)
        case "$2" in
            suspend|hybrid-sleep)
                systemctl --user restart whisper-type.service
                ;;
        esac
        ;;
esac
```

Install the resume hook:
```bash
sudo cp scripts/99-whisper-resume /etc/systemd/system-sleep/99-whisper-resume
sudo chmod +x /etc/systemd/system-sleep/99-whisper-resume
```

### `scripts/test_all.sh`

```bash
#!/usr/bin/env bash
set -uo pipefail
cd "$(cd "$(dirname "$0")/.." && pwd)"
export PATH="$HOME/.local/share/vox-venv/bin:$PATH"
PY="$HOME/.local/share/vox-venv/bin/python"
pass=0; fail=0; skip=0
run() {
    local name="$1"; shift
    echo "=== $name ==="
    local out; out=$("$@" 2>&1); local rc=$?
    echo "$out"
    if echo "$out" | grep -q '^SKIP:'; then skip=$((skip+1)); echo "  --> SKIPPED"
    elif [ $rc -eq 0 ]; then pass=$((pass+1))
    else fail=$((fail+1)); echo "  --> FAILED"
    fi; echo
}
need_sudo=false
if [ "$(id -u)" -ne 0 ] && ! "$PY" -c "open('/dev/uinput','w').close()" 2>/dev/null; then
    need_sudo=true
fi
run "capture" "$PY" tests/test_capture.py
if [ "$need_sudo" = true ]; then
    run "f9 loopback" sudo -n -u "$(id -un)" "$PY" tests/test_f9_loopback.py
    run "type loopback" sudo -n -u "$(id -un)" "$PY" tests/test_type_loopback.py
else
    run "f9 loopback" "$PY" tests/test_f9_loopback.py
    run "type loopback" "$PY" tests/test_type_loopback.py
fi
run "transcribe" "$PY" tests/test_transcribe.py
run "daemon-integration" sudo -n -u "$(id -un)" "$PY" tests/test_daemon_integration.py
echo "======================================"
echo "passed: $pass   failed: $fail   skipped: $skip"
[ "$fail" -eq 0 ]
```

---

## Stage 6 — Recorder source and build script

### `recorder/sdl_rec.c` (the complete C source — see full repo)

Key details:
- Writes a correct 44-byte WAV header at offsets 20, 24, 28, 32, 34 (PCM layout)
- On SIGTERM: closes the file, reopens for "r+b", seeks to offset 4 and 40, writes the RIFF and data sizes via `fseek` (not `fwrite` at stream position)
- Resamples from device-native rate to 16kHz mono via SDL CVT
- `--list` mode: enumerates capture devices by probing `SDL_GetAudioDeviceName(i, 1)` until NULL

### `recorder/build.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
dir="$(cd "$(dirname "$0")" && pwd)"
gcc "$dir/sdl_rec.c" -lSDL2 -o "$dir/../bin/sdl_rec"
echo "built $dir/../bin/sdl_rec"
```

---

## Stage 7 — Test everything

```bash
./scripts/test_all.sh
```

Expected: all tests pass (capture, f9 loopback, type loopback, transcribe, daemon integration).

If f9/type loopback tests are skipped, the current session lacks the `input` group — log out and in.

---

## Stage 8 — Start the daemon

```bash
./scripts/run.sh           # foreground, type into focused window
WHISPER_DRY=1 ./scripts/run.sh  # print instead of type (headless test)
```

Then press the trigger key (default F9, or whatever you set in conf.env):
- **First press:** starts recording
- **Second press:** stops, transcribes, types text

---

## Stage 9 — Enable autostart

```bash
./scripts/autostart.sh
```

This installs a systemd user service that starts on login (when the `input` group is live).

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Permission denied on `/dev/uinput` or `/dev/input/eventN` | Log out and back in (input group) |
| `recorder not found` | Run `recorder/build.sh` |
| Recorder still recording after kill | It was SIGKILLed (kill -9); SIGTERM finalizes WAV, never use kill -9 |
| whisper says "failed to read audio data" | SIGKILLed the recorder → corrupted WAV header |
| Recording works but "nothing transcribed" after wake from sleep | The resume hook (`/etc/systemd/system-sleep/99-whisper-resume`) should restart the daemon on suspend. If missing, run `sudo systemctl --user restart whisper-type.service`. |
| Typing nothing into a native-Wayland app | `/dev/uinput` not writable — check perms and udev rule (`KERNEL=="uinput"`) |
| Wrong audio source captured | Set `WHISPER_DEVICE_ID` explicitly (find index with `bin/sdl_rec --list`) |

---

## File structure

```
whisper-type/
├── src/
│   ├── whisper_type.py       # the daemon (orchestrator)
│   ├── f9_trigger.py          # F9 detector (evdev listener)
│   └── uinput_type.py         # typer (evdev virtual keyboard)
├── recorder/
│   ├── sdl_rec.c              # recorder source
│   └── build.sh               # build -> bin/sdl_rec
├── bin/
│   └── sdl_rec                # compiled recorder
├── scripts/
│   ├── run.sh                 # foreground launcher
│   ├── autostart.sh           # systemd service installer
│   ├── test_all.sh            # test suite
│   └── 99-whisper-resume      # restart on suspend (install to /etc/systemd/system-sleep/)
├── systemd/
│   └── whisper-type.service   # systemd user unit
├── tests/                     # test suite (test_capture.py, test_f9_loopback.py,
│                               #   test_type_loopback.py, test_transcribe.py,
│                               #   test_daemon_integration.py)
├── vocab.txt                  # preferred words for context prompt
├── conf.env.example           # env var overrides
└── requirements.txt           # evdev>=2.0
```
