#!/usr/bin/env bash
# Runs the full whisper-type test suite in order.
# Some tests (f9/type loopback) need /dev/uinput access — run as a user in the
# `input` group, or with sudo for a live check.
set -uo pipefail
cd "$(cd "$(dirname "$0")/.." && pwd)"
export PATH="$HOME/.local/share/vox-venv/bin:$PATH"
PY="$HOME/.local/share/vox-venv/bin/python"

pass=0; fail=0; skip=0
run() {
    local name="$1"; shift
    echo "=== $name ==="
    local out
    out=$("$@" 2>&1)
    local rc=$?
    echo "$out"
    if echo "$out" | grep -q '^SKIP:'; then
        skip=$((skip+1)); echo "  --> $name SKIPPED"
    elif [ $rc -eq 0 ]; then
        pass=$((pass+1))
    else
        fail=$((fail+1)); echo "  --> $name FAILED"
    fi
    echo
}

# loopback tests need /dev/uinput; run them under sudo (original user) if we
# can't open it here, so the suite is runnable without a fresh login.
need_sudo=false
if [ "$(id -u)" -ne 0 ] && ! "$PY" -c "open('/dev/uinput','w').close()" 2>/dev/null; then
    need_sudo=true
fi

run "capture"        "$PY" tests/test_capture.py
if [ "$need_sudo" = true ]; then
    run "f9 loopback"   sudo -n -u "$(id -un)" "$PY" tests/test_f9_loopback.py
    run "type loopback" sudo -n -u "$(id -un)" "$PY" tests/test_type_loopback.py
else
    run "f9 loopback"   "$PY" tests/test_f9_loopback.py
    run "type loopback" "$PY" tests/test_type_loopback.py
fi
run "transcribe"     "$PY" tests/test_transcribe.py
run "daemon-integration" sudo -n -u "$(id -un)" "$PY" tests/test_daemon_integration.py

echo "======================================"
echo "passed: $pass   failed: $fail   skipped: $skip"
[ "$fail" -eq 0 ]
