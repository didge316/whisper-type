#!/usr/bin/env bash
# One-shot build of the SDL2 recorder -> ../bin/sdl_rec
set -euo pipefail
dir="$(cd "$(dirname "$0")" && pwd)"
src="$dir/sdl_rec.c"
out="$dir/../bin/sdl_rec"
gcc "$src" -lSDL2 -o "$out"
echo "built $out"
