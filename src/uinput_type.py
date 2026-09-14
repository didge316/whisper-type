#!/usr/bin/env python3
"""Minimal uinput typer: types text into the focused window via a virtual
keyboard written to /dev/uinput. No pynput, no X, no dumpkeys. Reaches native
Wayland apps (kitty) directly. Run with enough privilege to open /dev/uinput."""
import sys, time
from collections import OrderedDict
from evdev import UInput, ecodes as e

SHIFT = e.KEY_LEFTSHIFT

# base (unshifted) key name for punctuation; digits/letters resolved by name
BASE = {
    ' ': 'KEY_SPACE', '.': 'KEY_DOT', ',': 'KEY_COMMA', '/': 'KEY_SLASH',
    '-': 'KEY_MINUS', '=': 'KEY_EQUAL', ';': 'KEY_SEMICOLON', "'": 'KEY_APOSTROPHE',
    '`': 'KEY_GRAVE', '\\': 'KEY_BACKSLASH', '[': 'KEY_LEFTBRACE',
    ']': 'KEY_RIGHTBRACE',
}
# shifted pair: char -> (base char, needs_shift)
SHIFTED = {
    '!': ('1', True), '@': ('2', True), '#': ('3', True), '$': ('4', True),
    '%': ('5', True), '^': ('6', True), '&': ('7', True), '*': ('8', True),
    '(': ('9', True), ')': ('0', True), '_': ('-', True), '+': ('=', True),
    ':': (';', True), '"': ("'", True), '~': ('`', True), '|': ('\\', True),
    '<': (',', True), '>': ('.', True), '?': ('/', True),
}

# base char -> evdev key name (reverse of BASE, plus digits/letters)
_BASE_NAME = {ch: name for ch, name in BASE.items()}


def _resolve(ch):
    """Resolve a single base character to an evdev key name (e.g. '1'->'KEY_1')."""
    if ch.isascii() and ch.isdigit():
        return 'KEY_' + ch
    if ch.isalpha():
        return 'KEY_' + ch.upper()
    return _BASE_NAME.get(ch, 'KEY_' + ch.upper())


def keyname_for(ch):
    if ch in SHIFTED:
        base, need_shift = SHIFTED[ch]
        return _resolve(base), need_shift
    if ch in BASE:
        return BASE[ch], False
    if ch.isascii() and ch.isdigit():
        return 'KEY_' + ch, False
    if ch.isascii() and ch.isalpha():
        return 'KEY_' + ch.upper(), ch.isupper()
    return None, False

# Persistent virtual-keyboard handle so the compositor attaches ONE keyboard
# device for the daemon's whole lifetime. Creating+closing a uinput device per
# transcription cycle races with the compositor: a stale device from the prior
# cycle can still be live when the next one appears, and the compositor then
# interleaves their events -> characters land out of order / duplicated.
# Reusing one device removes that race entirely.
_UINPUT = None

def _get_ui():
    global _UINPUT
    if _UINPUT is not None:
        return _UINPUT
    events = {e.EV_KEY: list(range(256))}
    ui = UInput(events=events, name='virtual-keyboard', bustype=e.BUS_HOST)
    time.sleep(0.5)  # let the compositor fully attach the new uinput device
    _UINPUT = ui
    return ui

def type_text(text, gap=0.008, ui=None):
    if ui is None:
        ui = _get_ui()
    for ch in text:
        name, need_shift = keyname_for(ch)
        if name is None:
            sys.stderr.write(f"skip char {ch!r}\n")
            continue
        code = getattr(e, name)
        if need_shift:
            ui.write(e.EV_KEY, SHIFT, 1); ui.syn()
        ui.write(e.EV_KEY, code, 1); ui.syn()
        ui.write(e.EV_KEY, code, 0); ui.syn()
        if need_shift:
            ui.write(e.EV_KEY, SHIFT, 0); ui.syn()
        time.sleep(gap)

if __name__ == "__main__":
    msg = " ".join(sys.argv[1:]) or "uinput typer ok"
    type_text(msg)
    sys.stderr.write(f"typed: {msg!r}\n")
