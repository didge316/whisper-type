#!/usr/bin/env bash
# Foreground launcher: sets PATH, loads optional conf.env, execs the daemon.
set -euo pipefail
cd "$(cd "$(dirname "$0")/.." && pwd)"
export PATH="$HOME/.local/share/vox-venv/bin:$PATH"
if [ -f conf.env ]; then
    set -a; . ./conf.env; set +a
fi
exec "$HOME/.local/share/vox-venv/bin/python" src/whisper_type.py
