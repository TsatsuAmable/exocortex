#!/usr/bin/env python3
"""Bounded launchd tick for delivery + Nemosyne supervision."""
from pathlib import Path
import os
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def run_bounded(command: list[str], timeout: int) -> int:
    process = subprocess.Popen(command, cwd=ROOT, start_new_session=True)
    try:
        return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"Aineko watchdog: terminating overrun after {timeout}s: {' '.join(command)}", file=sys.stderr)
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
        except Exception:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except Exception:
                pass
        return 124


exit_code = 0
for command, timeout in [
    ([sys.executable, str(ROOT / 'delivery.py'), 'tick'], 60),
    ([sys.executable, str(ROOT / 'autopilot.py')], 120),
    ([sys.executable, str(ROOT / 'nemosyne_continuous.py')], 240),
]:
    code = run_bounded(command, timeout)
    if code:
        exit_code = code
sys.exit(exit_code)
