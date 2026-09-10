#!/usr/bin/env bash
# Install and enable the systemd user service for whisper-type.
set -euo pipefail
dir="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$HOME/.config/systemd/user"
ln -sf "$dir/systemd/whisper-type.service" "$HOME/.config/systemd/user/whisper-type.service"
systemctl --user daemon-reload
systemctl --user enable --now whisper-type.service
echo "whisper-type enabled for the current user session."
