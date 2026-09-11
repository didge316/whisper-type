#!/usr/bin/env bash
# Foreground launcher: sets PATH, loads optional conf.env, execs the daemon.
# The Python interpreter defaults to the project venv but can be overridden with
# WHISPER_PYTHON (e.g. systemd passes the interpreter your distro actually has).
set -euo pipefail
cd "$(cd "$(dirname "$0")/.." && pwd)"
export PATH="/home/matt/.local/share/vox-venv/bin:$PATH"
PYTHON="${WHISPER_PYTHON:-/home/matt/.local/share/vox-venv/bin/python}"
if [ -f conf.env ]; then
    set -a; . ./conf.env; set +a
fi
exec "$PYTHON" src/whisper_type.py
