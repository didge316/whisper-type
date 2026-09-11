# Suspend/Resume Test — what we're trying now

**Date:** 2026-09-11
**Goal:** Confirm the push-to-type daemon still works after the laptop suspends and resumes.

## Background — why we're testing this

On 2026-09-11 the daemon broke: every F9 cycle returned **"nothing transcribed"**
(`whisper` logged `[BLANK_AUDIO]`). Recording "worked" (a WAV was produced) but the
audio was ~35–40 dB too quiet, so whisper's VAD treated it as silence.

**Root cause:** the Logitech H390 USB mic captures very weakly — even at max ALSA
capture gain (11 dB) and high PipeWire volume, recorded speech peaked at only
~200 / 32767. Below whisper's speech-detection threshold → blank.

**Fix applied** (`cf712c8`): digital capture gain in `sdl_rec`
(`WHISPER_RECORD_GAIN`, default 64 = +36 dB, clamped to int16). Recorded audio now
reaches full scale and whisper decodes it.

## The risk this test is checking

The gain fix is in-memory, so it survives resume fine. But **suspend/resume has its
own failure modes**, and two of them produce *exactly* the symptom we just fixed:

1. **CUDA context loss** — whisper-cli runs on the RTX 3060 (CUDA). After wake the
   GPU context can be stale and decode fails → blank.
   → Handled by the systemd wake hook (`scripts/99-whisper-resume`), which restarts
   the daemon and re-inits CUDA.

2. **PipeWire/ALSA audio state** — the mic node can come back muted, suspended, or at
   the wrong gain after wake. Since our bug was *in the capture-gain path*, this is
   the one we're worried about. Restarting the daemon does **not** reset the audio
   stack, so a stale mic could reintroduce blank audio.
   → We hardened the wake hook to `pactl resync` the audio graph on wake (this commit).

## What we will do

1. Suspend the machine (close the laptop / `systemctl suspend`).
2. Wait ~30 s.
3. Resume.
4. Press the trigger key (default `KEY_COMPOSE`; was configured as `KEY_F9` earlier)
   and speak a clear sentence, e.g. *"please open the file and read the document"*.
   Hold the trigger ~3–5 s.
5. Watch the focused window: does the speech appear as typed text?

## Expected outcomes

| Result | Meaning |
|---|---|
| Speech types correctly | Both failure modes handled. We're done. |
| **"nothing transcribed" / blank** | Audio stack came back wrong after wake. The `pactl resync` in the hook should fix it; if not, the mic node needs a re-activate (check `pactl list sources`, un-mute, re-set volume). |
| **whisper errors / crashes** | CUDA context not restored — the daemon restart in the hook should cover this. |
| **Types garbage / hallucinations** ("helicopter", "gunfire") | Whisper is decoding room *tone*, not speech. Same weak-signal symptom — speak closer/louder and hold longer. Not a crash. |

## If it breaks again after wake

- Check the mic is active: `pactl list sources | grep -A6 "H390"` — confirm it's not
  `SUSPENDED` and the volume is up.
- Force a resync: `pactl resync-loop` or re-load the capture node.
- Check the wake hook is installed/enabled:
  ```bash
  sudo cp scripts/99-whisper-resume /etc/systemd/system-sleep/99-whisper-resume
  sudo chmod +x /etc/systemd/system-sleep/99-whisper-resume
  ```
- Tail logs while testing:
  ```bash
  journalctl --user -u whisper-type.service --follow
  ```

## Notes / open questions

- The `WHISPER_RECORD_GAIN=64` default is aggressive — room tone alone can saturate,
  so expect more room-tone hallucinations. If you get clipping, lower it.
- We could not place a mic directly on the H390 during diagnosis (remote agent), so
  the exact gain you need depends on how close you speak. Tune `WHISPER_RECORD_GAIN`
  if 64 is too much or too little.
- Long-term: an AGC (automatic gain control) or a better mic would remove the need for
  a fixed gain bump and reduce hallucinations.
