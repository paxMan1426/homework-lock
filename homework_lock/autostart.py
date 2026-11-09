"""Run every minute by the scheduled task (see startup.py). Starts Homework Lock if apps should be locked and
it isn't running. Kept light: it doesn't import the UI, so running it every minute costs almost nothing."""
from __future__ import annotations

import ctypes
import subprocess

from . import schedule
from .config import Config
from .paths import ROOT, launch_command

MUTEX = "Local\\HomeworkLock.SingleInstance"
SYNCHRONIZE = 0x00100000
_DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
_BREAKAWAY = 0x01000000              # CREATE_BREAKAWAY_FROM_JOB: keep running after the task ends


def app_running() -> bool:
    k32 = ctypes.windll.kernel32
    handle = k32.OpenMutexW(SYNCHRONIZE, False, MUTEX)
    if handle:
        k32.CloseHandle(handle)
        return True
    return False


def needed(config: Config) -> bool:
    return schedule.is_locked(config)


def launch():
    from .startup import STARTUP_FLAG
    args = launch_command(STARTUP_FLAG)
    try:
        subprocess.Popen(args, cwd=str(ROOT), creationflags=_DETACHED | _BREAKAWAY, close_fds=True)
    except OSError:  # the task's job doesn't allow breakaway
        subprocess.Popen(args, cwd=str(ROOT), creationflags=_DETACHED, close_fds=True)


def main():
    if not app_running() and needed(Config()):
        launch()


if __name__ == "__main__":
    main()
