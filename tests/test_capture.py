#!/usr/bin/env python3
"""test_capture.py — record 3s via sdl_rec, validate the WAV header + volume.

Headless-friendly: the silence check is a soft warning (no speech is played),
but the WAV header must always be structurally valid.
"""
import os
import struct
import subprocess
import sys

BIN = os.environ.get("WHISPER_RECORD_BIN", os.path.expanduser("~/.local/bin/sdl_rec"))
DEV = int(os.environ.get("WHISPER_DEVICE_ID", "0"))
OUT = "/tmp/whisper-test-capture.wav"


def fail(msg):
    print(f"  FAIL: {msg}"); sys.exit(1)


def main():
    if not os.path.exists(BIN):
        fail(f"recorder not found at {BIN}")
    try:
        os.unlink(OUT)
    except FileNotFoundError:
        pass
    print("recording 3s ...")
    r = subprocess.run([BIN, str(DEV), "3", OUT],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode != 0:
        fail(f"sdl_rec exited {r.returncode}: {r.stderr.decode(errors='replace')[:200]}")
    if not os.path.exists(OUT):
        fail("no wav produced")

    with open(OUT, "rb") as fh:
        data = fh.read(44)
    if len(data) < 44 or data[0:4] != b"RIFF" or data[8:12] != b"WAVE":
        fail("bad RIFF/WAVE header")
    riff_size = struct.unpack("<I", data[4:8])[0]
    data_size = struct.unpack("<I", data[40:44])[0]
    expected_riff = data_size + 36
    if riff_size != expected_riff:
        fail(f"RIFF size {riff_size} != data+36 ({expected_riff})")
    # fmt chunk
    if data[12:16] != b"fmt ":
        fail("missing fmt chunk")
    # Standard 44-byte WAV header layout (little-endian).
    audio_format = struct.unpack("<H", data[20:22])[0]
    channels = struct.unpack("<H", data[22:24])[0]
    rate = struct.unpack("<I", data[24:28])[0]
    block_align = struct.unpack("<H", data[32:34])[0]
    bits = struct.unpack("<H", data[34:36])[0]
    checks = {
        "audio_format==1 (PCM)": audio_format == 1,
        "channels==1 (mono)": channels == 1,
        "rate==16000": rate == 16000,
        "blockAlign==2": block_align == 2,
        "bitsPerSample==16": bits == 16,
        "byteRate==32000": struct.unpack("<I", data[28:32])[0] == 32000,
    }
    for name, ok in checks.items():
        print(f"  {'ok ' if ok else 'BAD'} {name}")
        if not ok:
            fail(name)
    if riff_size < 44:
        fail(f"data chunk empty (size={riff_size}); was sdl_rec SIGKILLed?")

    # volume: read the data chunk peak (best-effort, offset 44)
    peak = 0
    try:
        with open(OUT, "rb") as fh:
            fh.seek(44)
            chunk = fh.read(min(1 << 20, os.path.getsize(OUT) - 44))
        n = len(chunk) // 2
        vals = struct.unpack(f"<{n}h", chunk[:n * 2])
        peak = max(abs(v) for v in vals) if vals else 0
    except Exception:
        peak = -1
    print(f"  peak amplitude = {peak} (0=silence)")
    if peak == 0:
        print("  WARN: captured silence — check mic (SDL device %d) and NoiseTorch" % DEV)
    print("  PASS: WAV header valid")


if __name__ == "__main__":
    main()
