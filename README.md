# whisper-type

F9 push-to-type voice-to-text for the terminal on Debian 13 / GNOME-on-Wayland.

Press **F9** to start recording, press **F9** again to stop, transcribe locally with a
whisper model, and **type the text into the focused window** via a virtual keyboard
(`/dev/uinput`). No clipboard — works on native Wayland.

## Quickstart

```bash
# from v1/
./scripts/run.sh
```

Then in any text field: press F9, speak, press F9. The sentence appears.

Dry-run (print instead of type, for headless testing):

```bash
WHISPER_DRY=1 ./scripts/run.sh
```

## How it works

```
F9 press -> f9_trigger (evdev) -> spawn sdl_rec (mic -> 16kHz WAV)
F9 press -> SIGTERM recorder -> whisper-cli transcribes -> uinput_type types it
```

Three pieces, no pynput:

- `src/f9_trigger.py`   — F9 detector (evdev listener, one press per physical press)
- `src/uinput_type.py`  — typer (evdev virtual keyboard on /dev/uinput)
- `src/whisper_type.py` — the daemon that orchestrates the above
- `bin/sdl_rec`          — SDL2 mic recorder (prebuilt C binary; source in `recorder/`)
- `whisper-cli`          — transcription (CUDA, from whisper.cpp)

## Dependencies

- System: `whisper.cpp` (built), gcc (only to rebuild the recorder), `evdev`
- Python (venv `~/.local/share/vox-venv`): `evdev` only
- Group: `matt` in `input`; `/dev/uinput` is `root:input 0660` (udev rule)

Install the venv dep:

```bash
~/.local/share/vox-venv/bin/pip install evdev
```

> The `input` group takes effect at **login**. If `/dev/uinput` opens with Permission
> denied, log out/in (or `sudo` for a live test). Verify with `id`, not `id matt`.

## Configuration (env vars)

| Var | Default | Meaning |
|---|---|---|
| `WHISPER_DEVICE_ID` | `0` | SDL capture device (0 = mic) |
| `WHISPER_RECORD_BIN` | `~/.local/bin/sdl_rec` | recorder path |
| `WHISPER_MODEL` | `.../ggml-small.en.bin` | whisper model |
| `WHISPER_BIN` | `.../whisper-cli` | whisper binary |
| `WHISPER_RAW` | `/tmp/whisper-rec.wav` | raw wav path |
| `WHISPER_DRY` | (empty) | non-empty -> print instead of type |

Copy `conf.env.example` to `conf.env` to set overrides permanently.

## Docs

`README.md` — this quickstart. `PLAN.md` — the build plan. `DOCS.md` — how it works
under the hood, the full test suite, **measured latency and trade-offs**,
deployment, and troubleshooting. Read `DOCS.md` before tuning.

## Autostart on login

```bash
./scripts/autostart.sh
```

This installs and enables the systemd user service. (A plain XDG autostart `.desktop`
running `scripts/run.sh` is an alternative.)

## Testing

```bash
./scripts/test_all.sh      # capture, f9 loopback, type loopback, transcribe
```

The f9/type loopback tests open `/dev/uinput`, so run as a user in the `input` group
(or with `sudo` for a live check).

## Troubleshooting

- **No F9 detected / permission denied on /dev/uinput** -> fresh login (input group),
  or `sudo` for a live test.
- **Recorder still recording after kill** -> it was SIGKILLed; SIGTERM finalizes cleanly.
- **whisper says "failed to read audio data"** -> corrupted WAV header; re-run capture
  (never SIGKILL sdl_rec).
- **Typing nothing into a native-Wayland app** -> confirm /dev/uinput is writable
  (input group). This build types via uinput directly, not the X/clipboard backends.

## Known limitations

- F9 also reaches the focused app (passive listener) — harmless in terminals.
- Voice pickup and on-screen paste depend on your real environment.
