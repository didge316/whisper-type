# whisper-type v1 — Implementation Plan

**Project:** F9 push-to-type voice-to-text for the terminal on Debian 13 / GNOME-on-Wayland.
**Status of this doc:** master plan for tying the three proven pieces into one working daemon.
Everything below is ready to build; the actual build happens in a fresh session (`v1/` is the working folder).

Press **F9** → record → press **F9** again → transcribe locally → **type the text into the focused window** via a virtual keyboard. No clipboard. Works on native Wayland.

---

## 0. One-paragraph summary

Three sub-problems were each solved and verified separately against the real hardware:

1. **Voice capture** — a small C recorder (`sdl_rec`) that captures the H390/wired mic via SDL2 → 16 kHz mono 16-bit WAV and finalizes cleanly on SIGTERM. (Fixed a WAV-header bug that made whisper reject the file.)
2. **Typing into the window** — a self-contained `evdev` typer that writes keystrokes to `/dev/uinput`, reaching native Wayland apps (kitty) directly.
3. **F9 detection** — a self-contained `evdev` listener that fires once per F9 press on the real keyboard, excluding gaming mice, without consuming the key.

The `v1` daemon is a Python orchestrator that **wires these three together** and — critically — **does not use `pynput`**, which is broken in this venv (missing `pynput/mouse/_uinput.py` breaks the whole import). F9 detection and typing both use the installed `evdev` lib directly.

---

## 1. Goals (v1 = shippable)

- [ ] `whisper-type` daemon runs, listens for F9, records on press/stop, transcribes, and types into the focused window.
- [ ] Zero hard dependency on `pynput`. Only `evdev` (Python) + `sdl_rec` (C) + `whisper-cli` (binary).
- [ ] Works on the real wired keyboard + mic, in the focused app (terminal/text field), on native Wayland.
- [ ] Clean start/stop: SIGTERM/SIGINT stops recording and exits with no lingering mic or half-written files.
- [ ] Configurable via environment variables; supports a dry-run mode for headless testing.
- [ ] Autostarts on login (systemd user service or XDG autostart).

## 2. Non-goals

- Clipboard paste (deliberately avoided — `wlclipboard` isn't installable here).
- Hold-to-talk is implemented (default trigger mode). Mouse-side-button triggers,
  VAD/trimming, model upgrades — optional follow-ups (see §13).
- Cross-distro support; this box is Debian 13 trixie + GNOME 48 on Wayland, RTX 3060.

---

## 3. Environment (confirmed facts)

| Item | Value |
|---|---|
| Distro / compositor | Debian 13 trixie + GNOME 48 on Wayland |
| Mic | Logitech H390 USB headset (SDL capture device **#0**) |
| Keyboard | Wired USB keyboard → `/dev/input/event2` (`  wired keyboard`) |
| GPU | RTX 3060 (11 GB) — whisper runs on CUDA |
| Compiler | gcc 14.2 |
| Python venv | `~/.local/share/vox-venv` (Python 3.13) |
| `input` group | `matt` is a member (`/etc/group`), and `/dev/uinput` is `root:input 0660` via udev rule |

**Gotcha (recurring):** a process's *effective* groups are a snapshot from login. If `matt` was added to `input` after the last login, the running session lacks it until a fresh login. Symptom: `/dev/uinput` or `/dev/input/eventN` opens with *Permission denied*. Fix: log out/in (or `sudo` for a live test). **Always verify with `id`** (not `id matt`, which re-reads `/etc/group`).

---

## 4. Why not pynput

`whisper.md` originally specified pynput for both F9 listening and typing. In this venv:

- `pynput/mouse/_uinput.py` is **missing**, and `pynput/__init__.py` imports the mouse backend at startup.
- So `import pynput` (and therefore its keyboard `Listener`/`Controller`) **fails to import** under any backend.
- Patching site-packages is fragile and wiped on `pip reinstall`.

**Decision:** use `evdev` directly for both F9 detection and typing. `evdev` is installed and proven for both. `sdl_rec` stays a standalone C binary (no Python dependency). `whisper-cli` stays a binary call.

---

## 5. Dependency list

### 5.1 System packages

| Package | Why | Install | Already? |
|---|---|---|---|
| `libSDL2-dev` | Build `sdl_rec` (headers + `libSDL2.so` link). Runtime `.so` is present; only the dev package is missing. | `sudo apt install libSDL2-dev` | **MISSING** (recorder binary already built & works) |
| `build-essential` / `gcc` | Compile `sdl_rec.c` | `sudo apt install build-essential` | present (gcc 14.2) |
| `whisper.cpp` (built) | `whisper-cli` binary | pre-built in repo | present |

> **Note:** `sdl_rec` is already compiled and deployed. We do **not** need to rebuild it for v1 unless we change its source. Keep `libSDL2-dev` installed only if we intend to rebuild; otherwise the prebuilt binary runs fine.

### 5.2 Python (venv: `~/.local/share/vox-venv`)

| Package | Used for | Notes |
|---|---|---|
| `evdev` (2.0.0) | F9 detection + typing (virtual keyboard) | **only third-party dep** |
| `pynput` (1.8.2) | — | **installed but BROKEN — do not import. Leave installed; unneeded.** |

No `numpy`, no `sounddevice`, no `jq` runtime (transcription JSON is parsed with the stdlib `json`).

### 5.3 Pre-existing / external binaries

| Path | Purpose |
|---|---|
| `/home/matt/whisper.cpp/build/bin/whisper-cli` | Transcription engine (CUDA) |
| `/home/matt/whisper.cpp/models/ggml-small.en.bin` | Whisper `small` English model (~487 MB) |
| `~/.local/bin/sdl_rec` | SDL2 mic recorder → 16 kHz mono 16-bit WAV |

### 5.4 Group / udev prerequisites (persistent)

```bash
# udev rule: make /dev/uinput group-accessible
sudo tee /etc/udev/rules.d/99-uinput.rules >/dev/null <<'EOF'
SUBSYSTEM=="uinput", GROUP="input", MODE="0660"
EOF
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=uinput

# group membership (requires a fresh login to take effect)
sudo usermod -aG input matt
```

---

## 6. Repository layout (`v1/`)

```
v1/
├── PLAN.md               # this file (master plan)
├── README.md             # user-facing overview + quickstart
├── requirements.txt      # Python deps (evdev only)
├── .gitignore
├── conf.env.example      # example environment overrides
├── src/
│   ├── whisper_type.py        # the daemon (orchestrator) — THE deliverable
│   ├── f9_trigger.py          # F9 detector (evdev listener) — extracted, tested
│   └── uinput_type.py         # typer (evdev virtual keyboard) — extracted, tested
├── recorder/
│   ├── sdl_rec.c              # source (already compiled; kept for rebuild)
│   └── build.sh               # one-shot build -> ../bin/sdl_rec
├── bin/
│   └── sdl_rec                  # compiled recorder (committed prebuilt)
├── scripts/
│   ├── run.sh                   # foreground launcher (sets env, execs daemon)
│   ├── autostart.sh             # systemd user service generator
│   └── test_all.sh              # runs the full test suite (see §10)
├── tests/
│   ├── test_f9_loopback.py      # uinput keyboard -> detector, expect F9_PRESSED
│   ├── test_type_loopback.py    # typer -> listener, expect text captured
│   ├── test_capture.py          # record 3s, validate WAV header + non-silence
│   └── test_transcribe.py       # whisper-cli on a known clip -> known text
└── systemd/
    └── whisper-type.service     # systemd user unit
```

The three `src/` modules are **already written and verified** (from the prior session). In v1 they are moved into the repo as-is (with minor cleanup) and imported by the daemon, rather than living in `/tmp`.

---

## 7. Component specifications

### 7.1 `f9_trigger.py` — F9 detector

- `InputDevice` on a keyboard, `read_one()` loop (evdev opens nonblocking; sleep 50 ms on empty to avoid busy-spin).
- Fires on `EV_KEY` + `KEY_F9` + `value==1`. Ignores `value==0` (release) and `value==2` (auto-repeat) → **one event per physical press**.
- **Passive** — only reads, so F9 reaches the focused app (clean toggle).
- **Device selection:** pick devices whose name contains `keyboard` (case-insensitive); require `KEY_F9` present. Gaming mice expose a full HID keyboard interface (163 key codes, F-keys, space) so name-filtering is required. Fall back to any `KEY_F9` device if none match.
- CLI: `f9_trigger.py [device-path]`, `f9_trigger.py --list`. Prints `F9_PRESSED` on each press. Exits cleanly on SIGTERM/SIGINT.

### 7.2 `uinput_type.py` — typer

- Creates a virtual keyboard on `/dev/uinput` via `evdev.UInput`, emits `EV_KEY` events with `write()` + `syn()`.
- Resolves every key by its `evdev.ecodes` **name** (no hardcoded keycodes); covers all printable ASCII; holds `KEY_LEFTSHIFT` for shifted chars.
- Sleeps **0.3 s** after opening the device so the compositor attaches before typing (without it, the first ~3 chars are dropped).
- No pynput, no X, no `dumpkeys`. Reaches native Wayland (kitty) directly.

### 7.3 `sdl_rec` — recorder (C binary, already built)

- `sdl_rec <device-id> <seconds=0=infinite> <out.wav>`; SDL2 capture → 16 kHz mono 16-bit WAV.
- On SIGTERM/SIGINT it finalizes the WAV header (patches RIFF + data sizes via `fseek` to offsets 4 and 40 — a plain `fwrite(hdr+40,...)` without `fseek` wrote at the wrong stream position).
- Keep `sdl_rec.c` + `build.sh` in `recorder/`; commit the prebuilt `bin/sdl_rec`.

### 7.4 `whisper_type.py` — the daemon (THE deliverable)

Orchestrates the three. No pynput. State held in memory (no state file).

**State machine:**

```
IDLE --F9 press--> RECORDING --(sdl_rec running) --F9 press--> TRANScribing --done--> IDLE
                    |                                        |
                  spawn sdl_rec                            whisper-cli -> text
                                                             -> uinput_type(text)
```

- `IDLE`: listener active, waiting for F9.
- `RECORDING`: on F9, unlink stale raw/json, spawn `sdl_rec 0 0 <RAW>` (device 0 = mic, infinite), store PID.
- `RECORDING`: on next F9, `SIGTERM` the recorder PID, wait up to 5 s (`kill` if it hangs), mark transcribing.
- `TRANSCRIBING`: run `whisper-cli -m <MODEL> -f <RAW> -oj -nt -np -of <RAW>` (whisper appends `.json`), parse `transcription[].text`, collapse whitespace.
- Type the text via `uinput_type` (append a trailing space), then clean up raw/json, back to `IDLE`.
- A `typing` guard blocks a new F9 from firing mid-type.

**Signal handling:** SIGTERM/SIGINT stop any in-progress recording (SIGTERM the recorder), then exit 0. No lingering mic.

**Config (env vars):**

| Var | Default | Meaning |
|---|---|---|
| `WHISPER_DEVICE_ID` | `0` | SDL capture device (0 = mic) |
| `WHISPER_RECORD_BIN` | `~/.local/bin/sdl_rec` | recorder path |
| `WHISPER_MODEL` | `/home/matt/whisper.cpp/models/ggml-small.en.bin` | model |
| `WHISPER_BIN` | `/home/matt/whisper.cpp/build/bin/whisper-cli` | whisper binary |
| `WHISPER_RAW` | `/tmp/whisper-rec.wav` | raw wav (whisper writes `+ .json`) |
| `WHISPER_DRY` | (empty) | non-empty → print text instead of typing |

**Dry-run** (`WHISPER_DRY=1`) prints transcribed text to stdout — useful for headless verification without typing anywhere.

---

## 8. Build steps (sequential, copy-pasteable)

Run in a fresh session. Assumes the venv and prior artifacts exist.

1. **Create the folder + move sources.**
   ```bash
   mkdir -p /home/matt/AI/whisper/v1/{src,recorder,bin,scripts,tests,systemd}
   cp /tmp/f9_listen.py   /home/matt/AI/whisper/v1/src/f9_trigger.py
   cp /tmp/uinput_type.py /home/matt/AI/whisper/v1/src/uinput_type.py
   cp /tmp/sdl_rec.c      /home/matt/AI/whisper/v1/recorder/sdl_rec.c
   cp /home/matt/.local/bin/sdl_rec /home/matt/AI/whisper/v1/bin/sdl_rec
   ```

2. **Install the one missing system dep only if we will rebuild the recorder.**
   The prebuilt `bin/sdl_rec` already works, so this is optional:
   ```bash
   sudo apt install libSDL2-dev   # only needed to rebuild sdl_rec
   ```

3. **Create the venv + install `evdev`** (if building fresh):
   ```bash
   python3 -m venv ~/.local/share/vox-venv
   ~/.local/share/vox-venv/bin/pip install --upgrade pip evdev
   ```

4. **Write `src/whisper_type.py`** per §7.4 — import `f9_trigger` and `uinput_type` logic (or call them as subprocesses; either is fine, in-process is lighter).

5. **Add `recorder/build.sh`:**
   ```bash
   #!/usr/bin/env bash
   set -euo pipefail
   gcc "$(dirname "$0")/sdl_rec.c" -lSDL2 -o "$(dirname "$0")/../bin/sdl_rec"
   ```

6. **Add `scripts/run.sh`** to set env and exec the daemon in the foreground:
   ```bash
   #!/usr/bin/env bash
   set -euo pipefail
   cd "$(dirname "$0")/.."
   export PATH="$HOME/.local/share/vox-venv/bin:$PATH"
   # load optional overrides from conf.env if present
   [ -f conf.env ] && set -a && . ./conf.env && set +a
   exec "$HOME/.local/share/vox-venv/bin/python" src/whisper_type.py
   ```

7. **Add packaging files:** `requirements.txt` (`evdev`), `.gitignore`, `conf.env.example`, `systemd/whisper-type.service`, `scripts/autostart.sh`, `scripts/test_all.sh`.

8. **Run the test suite** (§10). Fix anything red.

9. **Manual end-to-end:** start the daemon (fresh login so `input` group is live), press F9 in a terminal, speak, press F9, confirm text lands.

---

## 9. Daemon lifecycle details

- **Foreground, runs until killed.** No daemonization inside the script — let systemd/XDG autostart manage it.
- **No state file.** Recording state and the recorder PID live in an in-memory dict. Single recorder at a time; the second F9 stop kills it cleanly.
- **Transcription JSON:** whisper-cli writes `<RAW>.json`. Parse with stdlib `json`; join `transcription[].text`; collapse whitespace.
- **Typing:** `uinput_type` opens `/dev/uinput`, settles 0.3 s, then emits each keystroke; trailing space kept so typed words don't stick to preceding text.
- **Cleanup:** on both normal stop and SIGTERM, remove `<RAW>` and `<RAW>.json` so no partial captures linger.

---

## 10. Testing plan

Each test is standalone and headless-friendly. `scripts/test_all.sh` runs them in order.

### 10.1 `test_capture.py`
- Record 3 s via `sdl_rec 0 3 /tmp/t.wav` (clean exit, no SIGKILL).
- Assert WAV header valid: `RIFF == len-8`, `data == len-44`, `bitsPerSample==16`, `blockAlign==2`, `byteRate==32000`.
- Assert non-silence (peak > threshold) when speech is played during the clip.

### 10.2 `test_f9_loopback.py`
- Create a uinput keyboard; run `f9_trigger.py <that-device>` as a subprocess.
- Emit decoy `A`, then F9 (with settle time so the reader is attached).
- Assert the detector logs `F9_PRESSED` **exactly once** and ignores `A`.
- (Optional) emit F9 twice → two `F9_PRESSED`.

### 10.3 `test_type_loopback.py`
- Run an `evdev` reader on a uinput keyboard; use `uinput_type` to type a known string.
- Assert the reader captures every character (round-trip equals the input, accounting for the trailing space).

### 10.4 `test_transcribe.py`
- Feed a known WAV (e.g. `espeak-ng` "the quick brown fox") to `whisper-cli`.
- Assert the transcribed text contains "quick brown fox".

### 10.5 End-to-end (manual, needs a human)
- Fresh login (so `input` group is live). Start daemon. Focus a terminal.
- Press F9, speak a sentence, press F9. Confirm the exact sentence appears in the terminal.
- Dry-run variant: `WHISPER_DRY=1` prints the text to stdout (no typing) for headless sanity.

---

## 11. Gotchas / risks (learned the hard way)

1. **Fresh-login group membership.** `usermod -aG input` takes effect at login, not mid-session. Verify with `id` (effective groups), not `id matt`.
2. **uinput privilege.** Opening `/dev/uinput` needs the `input` group. A stale snapshot → *Permission denied*. `sudo` bypasses for a live test.
3. **SIGKILL breaks the WAV.** `kill -9` on `sdl_rec` skips header finalization → RIFF/data sizes = 0 (un-decodable). Always `SIGTERM`; the recorder finalizes on its own.
4. **WAV header offsets.** `fseek` before writing the RIFF size (offset 4) and data size (offset 40); a bare `fwrite(hdr+40,...)` lands at the stream position, not the offset.
5. **pynput is broken.** Missing `mouse/_uinput.py` breaks the whole import. Use `evdev`.
6. **Gaming mice false-trigger F9.** They expose a full HID keyboard interface; select the real keyboard by **name** containing "keyboard", not by capability counts.
7. **Typing timing.** Settle 0.3 s after opening `/dev/uinput` or the first ~3 chars are dropped.
8. **whisper-cli appends `.json`** to the `-of` path. Account for it (`RAW + ".json"`).
9. **SDL2 dev package missing** — prebuilt `sdl_rec` runs fine; only install `libSDL2-dev` if rebuilding.
10. **F9 passes through** to the focused app (passive listener). Usually harmless; if it ever types an unwanted F9, switch triggers.

---

## 12. Deployment / autostart

**systemd user service** (`systemd/whisper-type.service`):

```ini
[Unit]
Description=whisper-type F9 push-to-type
After=graphical-session.target

[Service]
Type=simple
ExecStart=%h/.local/share/vox-venv/bin/python %h/.local/bin/whisper-type
Restart=on-failure
# env overrides go here or in conf.env

[Install]
WantedBy=default.target
```

```bash
ln -s /home/matt/AI/whisper/v1/systemd/whisper-type.service \
      ~/.config/systemd/user/whisper-type.service
systemctl --user enable --now whisper-type.service
```

**Fallback:** XDG autostart (`~/.config/autostart/whisper-type.desktop`) running `scripts/run.sh`.

> The service runs as `matt` after login, so it inherits the live `input` group — no stale-snapshot problem.

---

## 13. Open questions / optional follow-ups

- **Model upgrade:** swap `medium.en` for higher accuracy (~1 GB VRAM — fine on the 3060). Set `WHISPER_MODEL`.
- **Trigger:** hold-to-talk is now implemented (default mode; press+hold to record,
  release to stop+transcribe, via `WHISPER_HOLD_TALK` / `Environment=WHISPER_HOLD_TALK=1`).
  Push-to-toggle remains available. A mouse side-button trigger is still a follow-up.
- **Audio cue:** wire up a real start/stop notification (the old `_beep` stub is unused).
- **Trimming / VAD:** leading-silence trim or a small VAD pass before transcription to cut wasted compute.
- **Per-app routing:** send transcription to a specific app instead of whichever is focused.
- **Confirm the real-F9 press** once the daemon is running (a human presses F9; expect one `F9_PRESSED`).

---

## 14. README.md contents (copy to `v1/README.md` when building)

```markdown
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
- `recorder/sdl_rec`    — SDL2 mic recorder (prebuilt C binary)
- `whisper-cli`         — transcription (CUDA, from whisper.cpp)

## Dependencies

- System: `whisper.cpp` (built), gcc (only to rebuild the recorder)
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

## Autostart on login

```bash
ln -s "$PWD/systemd/whisper-type.service" ~/.config/systemd/user/
systemctl --user enable --now whisper-type.service
```

## Testing

```bash
./scripts/test_all.sh      # capture, f9 loopback, type loopback, transcribe
```

## Troubleshooting

- **No F9 detected / permission denied on /dev/uinput** -> fresh login (input group),
  or `sudo` for a live test.
- **Recorder still recording after kill** -> it was SIGKILLed; SIGTERM finalizes cleanly.
- **whisper says "failed to read audio data"** -> corrupted WAV header; re-run capture
  (never SIGKILL sdl_rec).
- **Typing nothing into a native-Wayland app** -> the xorg backend can't reach it; this
  build uses uinput directly, so confirm /dev/uinput is writable (input group).

## Known limitations

- F9 also reaches the focused app (passive listener) — harmless in terminals.
- Voice pickup and on-screen paste depend on your real environment.
```

---

## 15. Definition of done for v1

- [ ] `whisper-type` daemon running under systemd user service (or XDG autostart).
- [ ] F9 press records; F9 press again transcribes and types into the focused window.
- [ ] All four automated tests green (`scripts/test_all.sh`).
- [ ] Clean SIGTERM shutdown; no lingering recorder, no partial WAVs.
- [ ] README documents quickstart, config, troubleshooting (fresh login, `sudo` for live tests).
- [ ] Repo is git-ready: `requirements.txt`, `.gitignore`, `PLAN.md`, `README.md` present.
