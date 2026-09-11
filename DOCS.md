# whisper-type — Operations & Design Notes

Companion to `PLAN.md` (build plan) and `README.md` (quickstart). This doc covers
everything you need to run, verify, tune, and troubleshoot the live system: how it
works under the hood, what the tests actually prove, measured latency and the
trade-offs around it, deployment, and the gotchas learned along the way.

> **Status:** implemented, tested, and deployed (systemd user service, enabled).
> **One prerequisite before it works live:** log out and back in so the `input`
> group is live (see §7).

---

## 1. What it does

Press **F9** → start recording. Press **F9** again → stop, transcribe locally, and
type the sentence into whichever window is focused. No clipboard, no network, all
local. Built for this machine: Debian 13 trixie + GNOME 48 on Wayland, RTX 3060,
Logitech H390 mic (via NoiseTorch), wired USB keyboard.

```
F9 press ──▶ f9_trigger (evdev) ──▶ spawn sdl_rec (H390 mic → 16 kHz WAV)
F9 press ──▶ SIGTERM recorder ──▶ whisper-cli transcribes ──▶ uinput_type types it
```

Three independent pieces, wired by the daemon `src/whisper_type.py`:

| Piece | File | Role |
|---|---|---|
| F9 detector | `src/f9_trigger.py` | Reads the real keyboard, reports one F9 per physical press. Passive (F9 also reaches the app → clean toggle). |
| Typer | `src/uinput_type.py` | Writes keystrokes to `/dev/uinput` (virtual keyboard) → reaches native Wayland apps. |
| Recorder | `bin/sdl_rec` (+ `recorder/sdl_rec.c`) | SDL2 capture → 16 kHz mono 16-bit WAV, finalizes cleanly on SIGTERM. |
| Transcriber | `whisper-cli` (whisper.cpp) | Loads the model, transcribes the WAV. Binary + model are external. |
| Orchestrator | `src/whisper_type.py` | The daemon: state machine tying the above together. |

---

## 2. What runs when (resource footprint)

This is the #thing people ask about, so it's called out explicitly.

| Component | When it runs | Footprint |
|---|---|---|
| `whisper_type.py` daemon | **Always**, after login (it's the F9 listener) | Tiny — a few MB, one idle thread doing nothing until F9. |
| `sdl_rec` (mic capture) | **Only** while recording (between the two F9 presses) | None when idle. Mic is not read otherwise. |
| `whisper-cli` + model | **Only** while transcribing (after the 2nd F9) | ~487 MB in VRAM for the ~2–3 s of a transcription cycle, then freed. |

**The model is NOT loaded all the time.** Only the small listener is persistent.
The 487 MB `small.en` model loads on demand and is freed after each cycle.

### Why toggle (start/stop) instead of hold-to-talk

- Release the key, reposition, think, then stop cleanly — no hand fatigue.
- Trade-off: there's a processing delay **after** you press F9 to stop (see §5),
  because the system must stop → transcribe → type. Hold-to-talk has the same
  processing cost but tires your hand.

---

## 3. Architecture / state machine

```
IDLE --F9--> RECORDING --(sdl_rec running) --F9--> TRANSCRIBING --done--> IDLE
```

- **IDLE:** listener active, waiting for F9.
- **RECORDING:** on F9, unlink stale wav/json, spawn `sdl_rec 0 0 <RAW>` (device 0 =
  mic, `0` seconds = infinite), store the PID.
- **RECORDING:** on next F9, `SIGTERM` the recorder (finalizes the WAV), wait up to
  5 s, then go to TRANSCRIBING.
- **TRANSCRIBING:** run `whisper-cli -m <MODEL> -f <RAW> -oj -nt -np -of <RAW>`
  (whisper appends `.json`), parse `transcription[].text`, collapse whitespace,
  type it via uinput (trailing space so words don't stick to preceding text),
  clean up raw/json, back to IDLE.
- A `typing` guard blocks a new F9 from firing mid-type.

**Signal handling:** SIGTERM/SIGINT set a stop flag (never `sys.exit()` from the
handler — it races `queue.get()` and raises on the lock). The main loop and the
listener thread both watch the flag and exit cleanly. Signals are installed in
`main()` (main thread only), so `run()` can be exercised from a test thread.

**No state file.** Recording state and the recorder PID live in an in-memory dict.
Single recorder at a time; the second F9 stops it cleanly.

---

## 4. Testing

Run the whole suite:

```bash
./scripts/test_all.sh
```

It auto-runs the `/dev/uinput` tests under `sudo -n -u <user>` if the current
session lacks the `input` group, so it works both with and without a fresh login.
Each test skips (not fails) gracefully when `/dev/uinput` isn't accessible.

| Test | What it proves | Needs `/dev/uinput` |
|---|---|---|
| `tests/test_capture.py` | `sdl_rec` writes a structurally valid 16 kHz/mono/16-bit WAV (RIFF/data sizes, PCM, byteRate…). Reports peak amplitude (0 = silence). | no |
| `tests/test_f9_loopback.py` | Creates a virtual keyboard, runs `f9_trigger` against it, emits a decoy `A` + one F9 → asserts exactly **one** `F9_PRESSED`, decoy ignored. | yes |
| `tests/test_type_loopback.py` | Types `"Build the daemon, then run the tests at 9am!"` via `uinput_type`, reads it back from the same device, asserts an exact shift-aware round-trip. | yes |
| `tests/test_transcribe.py` | `espeak-ng` → 16 kHz clip → `whisper-cli` → asserts "quick brown fox" transcribed. | no |
| `tests/test_daemon_integration.py` | Drives the **real daemon state machine**: points it at a virtual keyboard, injects two F9 presses, asserts `recording …` then `transcribing …` fire. | yes |

All five pass on this box.

### Bugs caught by testing (worth remembering)

1. **`uinput_type.py` shifted punctuation** — `SHIFTED` returned the raw base char
   (`'1'`) instead of the evdev key name (`'KEY_1'`), so `getattr(e, '1')` crashed.
   Fixed with a `_resolve()` helper that always resolves to a key name.
2. **`test_capture.py` offsets** — was reading the WAV header at the wrong bytes;
   the actual `sdl_rec` output was always correct.
3. **`evdev_keyname` removed in evdev 2.0** — `ecodes` is header-generated and has no
   name lookup. Tests build a `code → KEY_*` map from the constants instead.
4. **Signal handler in a non-main thread** — `sys.exit()` from the handler raced
   `queue.get()` (`RuntimeError: release unlocked lock`). Moved to a stop-flag method
   installed in `main()`.
5. **Loopback needed a shared device** — `type_text` created a *second* virtual
   keyboard, so the reader saw the wrong device. `type_text` now accepts an optional
   existing `UInput` so typer and reader share one device.

---

## 5. Latency (measured on this box)

Timing the real components (`small.en`, CUDA, RTX 3060, ~3 s clip):

| Stage (after you press F9 to stop) | Time |
|---|---|
| Finalize WAV | ~instant |
| Load whisper model | **~1.0 s** |
| Transcribe (3 s of speech) | **~1.2 s** |
| Type via uinput (0.3 s settle + ~15 ms/char) | **~0.9 s** |
| **Total: your last word → text on screen** | **~3 s** |

Notes:

- The delay is **after** you press F9 to stop, not while speaking. Recording itself
  is zero-latency.
- The **model load (~1 s) is a fixed cost that repeats on every stop**, because the
  daemon reloads the model per cycle. Back-to-back recordings pay it each time.
- Transcription is faster than real-time; longer speech adds proportionally little.
- The typing ~0.9 s is mostly the fixed 0.3 s device-settle; the per-char gap is
   intentional (raising it risks the compositor dropping keystrokes).

### Trade-offs to reduce it

| Option | Effect | Cost |
|---|---|---|
| **Preload the model** (keep `whisper-cli` resident) | Repeated 1 s load gone → ~2 s total; instant back-to-back. | ~487 MB stays in VRAM constantly. |
| **Smaller model** (`tiny.en` ~75 MB / `base.en` ~150 MB) | Load <0.5 s → ~1.5–2 s total; no persistent model. | Slightly less accuracy on noisy/technical audio. |
| Leave as-is | No always-on model; ~3 s lag after stop. | The 1 s reload repeats per cycle. |

**Recommendation:** keep the current design unless the ~3 s annoys you. If so,
`base.en` gives most of the speed win with almost no downside on the 3060.

---

## 6. Deployment

### Autostart (systemd user service)

```bash
./scripts/autostart.sh
```

Installs `~/.config/systemd/user/whisper-type.service` and enables it. The service
runs as `didge316` after login, so it inherits the live `input` group — no
stale-snapshot problem.

```bash
systemctl --user is-enabled whisper-type   # → enabled
systemctl --user is-active whisper-type    # → active once the input group is live
```

**Fallback:** XDG autostart running `scripts/run.sh` (also provided).

### Manual / foreground

```bash
./scripts/run.sh                         # normal: type into focused window
WHISPER_DRY=1 ./scripts/run.sh           # print text instead of typing (headless test)
```

`scripts/run.sh` sets the venv PATH and loads `conf.env` if present.

---

## 7. The one prerequisite: fresh login for the `input` group

`/dev/uinput` is `root:input 0660`, and the keyboard devices under `/dev/input/` are
`root:input` too. `didge316` must be in the `input` group to open them.

```bash
sudo usermod -aG input didge316              # done
sudo tee /etc/udev/rules.d/99-uinput.rules >/dev/null <<'EOF'
SUBSYSTEM=="uinput", GROUP="input", MODE="0660"
SUBSYSTEM=="misc", KERNEL=="uinput", GROUP="input", MODE="0660"
EOF
sudo udevadm control --reload-rules && sudo udevadm trigger --subsystem-match=misc
```

> **The `uinput` kernel module must be loaded, or `/dev/uinput` does not exist / is
> `root:root 0600` even with a correct udev rule.** On this box the module is not
> loaded by default at boot — the symptom is `ls -la /dev/uinput` showing
> `crw------- root root` (or the node missing). Load it and persist it:
> ```bash
> sudo modprobe uinput
> echo uinput | sudo tee /etc/modules-load.d/uinput.conf
> ```
> Without the persistence line, a reboot reverts `/dev/uinput` to `0600` and typing
> silently stops (the daemon logs `UInputError: "/dev/uinput" cannot be opened`).

> **Effective groups are a snapshot from login.** After `usermod`, the change does
> **not** apply until you **log out and back in** (or `sudo`, which re-reads the DB).
> Verify with `id` (your effective groups), **not** `id didge316` (which re-reads
> `/etc/group` and will always show it).

> **The udev rule must match `KERNEL=="uinput"`, not `SUBSYSTEM=="uinput"`.**
> `/dev/uinput` is a **`misc`** char device (major 10, minor 223) — its subsystem
> is `misc`, so a rule keyed on `SUBSYSTEM=="uinput"` never matches and the node
> stays `0600 root:root` (everyone except root is denied). After any change to the
> rule, `udevadm control --reload-rules` + a trigger on `subsystem-match=misc`.
> Symptom of a broken rule: `ls -la /dev/uinput` shows `crw------- root root`.

Symptom of a stale snapshot / broken rule: `/dev/uinput` or `/dev/input/eventN`
opens with *Permission denied*, and the daemon logs `no keyboard with KEY_F9 found`
or `UInputError: "/dev/uinput" cannot be opened for writing`. Both are fixed by a
fresh login (group) and the correct udev rule (perms).

---

## 8. Configuration (env vars)

Copy `conf.env.example` → `conf.env` to set overrides permanently (sourced by
`run.sh`).

| Var | Default | Meaning |
|---|---|---|
| `WHISPER_DEVICE_ID` | auto-detect | SDL capture device; left unset → picks the best-named mic (see `bin/sdl_rec --list`). |
| `WHISPER_RECORD_BIN` | repo `bin/sdl_rec` | recorder path (built from `recorder/sdl_rec.c`) |
| `WHISPER_MODEL` | `.../ggml-small.en.bin` | whisper model |
| `WHISPER_BIN` | `.../whisper-cli` | whisper binary |
| `WHISPER_RAW` | `/tmp/whisper-rec.wav` | raw wav path (whisper writes `+ .json`) |
| `WHISPER_DRY` | (empty) | non-empty → print instead of type |
| `WHISPER_VOCAB` | repo `vocab.txt` | one technical term per line; folded into the context prompt (this whisper-cli build has no `-tv` flag) |
| `WHISPER_PROMPT` | built from `vocab.txt` | explicit context prompt override; primes the model to spell terms correctly |

---

## 9. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| No F9 detected / `Permission denied` on `/dev/uinput` or `/dev/input/eventN` | Fresh login (input group), or `sudo` for a live test. |
| Service `failed` with `no keyboard with KEY_F9 found` | Same group issue — the current session predates `usermod`. Log out/in. |
| Recorder still recording after kill | It was SIGKILLed. SIGTERM finalizes cleanly; never `kill -9`. |
| whisper says "failed to read audio data" | Corrupted WAV header (from a SIGKILL). Re-run capture; never SIGKILL `sdl_rec`. |
| Recording works once then every cycle says "nothing transcribed" / `[BLANK_AUDIO]` | The mic input is ~35-40 dB under what whisper needs (weak H390 USB mic); recorded speech peaked at ~200/32767 even at max ALSA+PipeWire gain, so whisper's VAD treated it as silence. Fixed with digital capture gain in `sdl_rec` (`WHISPER_RECORD_GAIN`, default 64 = +36 dB, clamped to int16). See recorder/sdl_rec.c. |
| Whisper only outputs "you" / "helicopter" / "gunfire" (hallucinations) | The model is decoding room tone, not speech — same weak-mic issue, or a too-short hold. Speak clearly and hold the trigger ~3-5 s. |
| Nothing types into a native-Wayland app | `/dev/uinput` not writable. Check perms (`crw-rw---- root:input`); fix the udev rule (`SUBSYSTEM=="misc", KERNEL=="uinput"`, subsystem is `misc`), confirm `modprobe uinput` loaded the module, and log in fresh (input group). |
| Service died after one F9 cycle | Now crash-proof: transcribe/type errors are logged and the daemon returns to IDLE instead of exiting. A transient uinput/whisper failure no longer kills the listener. |
| Holding F9 fires repeatedly | Not applicable — Hyprland/GNOME binds with `repeat: false`; the daemon also fires once per physical press. |
| F9 itself appears as text | The listener is passive (F9 reaches the app). Usually harmless in terminals; switch trigger if it bothers you. |

### Gotchas learned the hard way

- **`uinput` module doesn't auto-load at boot.** `/dev/uinput` starts `0600 root:root`
  until `modprobe uinput` runs. Persisted via `/etc/modules-load.d/uinput.conf`.
- **The udev rule must key on `SUBSYSTEM=="misc"`, not `SUBSYSTEM=="uinput"`** — the
  node's real subsystem is `misc`. A rule keyed on `SUBSYSTEM=="uinput"` never matches.
- **whisper-cli in this repo has no `-tv`/`-pt` flags.** Domain vocabulary is applied
  through `--prompt` (built from `vocab.txt`), not a separate vocab file.
- **Group changes need a fresh login.** Effective groups are a login snapshot.

- **Don't SIGKILL `sdl_rec`.** It skips header finalization → RIFF/data sizes = 0
  (un-decodable). Always SIGTERM; the recorder finalizes its own WAV.
- **`wAV` header offsets** are the standard layout: audio_format @20, block_align
  @32, bits_per_sample @34. (A test once read these at +4 offsets.)
- **Gaming mice false-trigger F9** — they expose a full HID keyboard interface.
  `f9_trigger` selects the real keyboard by name containing "keyboard", not by
  capability counts.
- **uinput typing timing** — settle ~0.3 s after opening the device or the first
  chars are dropped.
- **whisper-cli appends `.json`** to the `-of` path. Account for it.

---

## 10. Optional follow-ups

- **Model upgrade:** `medium.en` for higher accuracy (~1 GB VRAM — fine on the 3060).
- **Trigger:** hold-to-talk or a mouse side-button to reduce hand strain.
- **Audio cue:** real start/stop notification (`libnotify-bin` for `notify-send`).
- **Trimming / VAD:** leading-silence trim or a small VAD pass before transcribe.
- **Per-app routing:** send transcription to a specific app instead of the focused one.
- **Preload the model** (§5 option) to cut the per-cycle reload latency.
