# whisper-type

F9 push-to-type voice-to-text for the terminal.

Press **F9** to start recording, press **F9** again to stop, transcribe locally with
a whisper model, and **type the text into the focused window** via a virtual keyboard
(`/dev/uinput`). No clipboard, no network, everything local.

> **Platform:** Linux only (uses `evdev` + `/dev/uinput`). Works under Wayland and X11
> on systemd distros (Debian, Arch/Fedora/Ubuntu, …). Not Windows or macOS.

## Quickstart

```bash
# from the repo root
./scripts/run.sh
```

Then in any text field: press **F9**, speak, press **F9** again. The sentence types in.

Dry-run (prints instead of types — good for headless testing):

```bash
WHISPER_DRY=1 ./scripts/run.sh
```

## How it works

```
F9 press -> f9_trigger (evdev) -> spawn sdl_rec (mic -> 16kHz WAV)
F9 press -> SIGTERM recorder -> whisper-cli transcribes -> uinput_type types it
```

Four pieces, no `pynput`:

- `src/f9_trigger.py`   — F9 detector (evdev listener, one press per physical press)
- `src/uinput_type.py`  — typer (evdev virtual keyboard on `/dev/uinput`)
- `src/whisper_type.py` — the daemon that orchestrates the above
- `recorder/sdl_rec.c`  — SDL2 mic recorder (build to `bin/sdl_rec` with `recorder/build.sh`)
- `whisper-cli`         — transcription (from [whisper.cpp](https://github.com/ggerganov/whisper.cpp))

## Installing on another machine

This is a per-machine setup. Work through these in order:

### 1. Build the recorder

```bash
recorder/build.sh          # needs: gcc + libSDL2-dev
```

This produces `bin/sdl_rec`. (The prebuilt binary is intentionally **not** shipped —
build it for your own architecture.)

### 2. Build whisper.cpp + get a model

```bash
git clone https://github.com/ggerganov/whisper.cpp
cd whisper.cpp && cmake -B build && cmake --build build --release
```

Download a model (e.g. `small`) into `whisper.cpp/models/`. The daemon defaults to
`~/whisper.cpp/models/ggml-small.en.bin` and `~/whisper.cpp/build/bin/whisper-cli` —
edit `conf.env` if yours live elsewhere.

### 3. Python dependency

```bash
python3 -m venv ~/.local/share/vox-venv
~/.local/share/vox-venv/bin/pip install evdev
```

### 4. Grant `/dev/uinput` + keyboard access

The daemon must read the keyboard and write the virtual keyboard, so your user needs
the `input` group and a udev rule:

```bash
sudo usermod -aG input "$USER"
sudo tee /etc/udev/rules.d/99-uinput.rules >/dev/null <<'EOF'
# /dev/uinput is a "misc" char device (major 10); match by kernel name.
KERNEL=="uinput", GROUP="input", MODE="0660"
EOF
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=misc
```

> **Log out and back in** — group membership only takes effect at login. Verify with
> `id` (your effective groups), **not** `id $USER`.

## Configuration (env vars)

All defaults are home/repo-relative; override any via env vars or `conf.env`.

| Var | Default | Meaning |
|---|---|---|
| `WHISPER_DEVICE_ID` | auto-detect | SDL capture device. Left unset → picks the best-named mic. |
| `WHISPER_RECORD_BIN` | repo `bin/sdl_rec` | recorder path |
| `WHISPER_MODEL` | `~/whisper.cpp/models/ggml-small.en.bin` | whisper model |
| `WHISPER_BIN` | `~/whisper.cpp/build/bin/whisper-cli` | whisper binary |
| `WHISPER_RAW` | `/tmp/whisper-rec.wav` | raw wav path |
| `WHISPER_DRY` | (empty) | non-empty → print instead of type |

If auto-detect picks the wrong source, set `WHISPER_DEVICE_ID` explicitly (find the
index with `bin/sdl_rec --list`).

Copy `conf.env.example` to `conf.env` to set overrides permanently.

## Autostart on login

```bash
./scripts/autostart.sh
```

This installs and enables the systemd user service (runs as you, after login, so it
inherits the `input` group). An XDG autostart `.desktop` running `scripts/run.sh` is
an alternative.

## Testing

```bash
./scripts/test_all.sh      # capture, f9 loopback, type loopback, transcribe, daemon
```

The f9/type loopback and daemon tests open `/dev/uinput`, so run as a user in the
`input` group (or with `sudo` for a live check).

## Troubleshooting

- **No F9 detected / permission denied on `/dev/uinput`** → fresh login (input group),
  or `sudo` for a live test.
- **`recorder not found` at startup** → build it first: `recorder/build.sh`.
- **Recorder still recording after kill** → it was SIGKILLed; SIGTERM finalizes cleanly.
- **whisper says "failed to read audio data"** → corrupted WAV header; re-run capture
  (never SIGKILL the recorder).
- **Recording works but "nothing transcribed" after wake from sleep** → two causes,
  both handled by the systemd resume hook (`scripts/99-whisper-resume`), which
  (a) resyncs PipeWire so the mic comes back at the right gain, and (b) restarts the
  daemon to restore the CUDA context. Install it with:
  ```bash
  sudo cp scripts/99-whisper-resume /etc/systemd/system-sleep/99-whisper-resume
  sudo chmod +x /etc/systemd/system-sleep/99-whisper-resume
  ```
  If blanks persist after wake, check the mic is not suspended:
  `pactl list sources | grep -A6 "H390"`.
- **"nothing transcribed" even when not suspended** → the mic is weak; the recorder
  applies digital capture gain (`WHISPER_RECORD_GAIN`, default 64). Speak closer/louder
  or hold the trigger ~3–5 s. See `SUSPEND-RESUME-TEST.md`.
- **Typing nothing into a native-Wayland app** → confirm `/dev/uinput` is writable
  (input group). This build types via uinput directly, not the X/clipboard backends.

## Known limitations

- F9 also reaches the focused app (passive listener) — harmless in terminals.
- Voice pickup and on-screen typing depend on your real environment (mic source, model).
- Linux-only; no hold-to-talk, mouse-button trigger, or per-app routing out of the box
  (optional follow-ups in `DOCS.md`).

---

## Docs

`README.md` — this quickstart. `DOCS.md` — how it works under the hood, the full test
suite, **measured latency and trade-offs**, deployment, and troubleshooting. Read
`DOCS.md` before tuning. `PLAN.md` — the historical development log. `SUSPEND-RESUME-TEST.md` — the live suspend/resume validation and what to do if blanks return after wake.

## License

MIT — see [LICENSE](LICENSE).
