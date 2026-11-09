"""Guard process: if Homework Lock is ended from Task Manager, start it again.

The app starts this guard; the guard watches the app. If the app process disappears, the guard relaunches
it (which starts a new guard) and exits. The app also restarts the guard if the guard is ended. Quitting the
app the normal way (homework done, free time, or parent PIN) stops the guard first, so nothing restarts.

Run by the app as:  pythonw -m homework_lock.watchdog <app pid> <app create_time>
          (packaged:  HomeworkLock.exe --watchdog <app pid> <app create_time>)
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import psutil

from .paths import FROZEN, ROOT, launch_command, pythonw

RESTARTED_FLAG = "--restarted"
GUARD_MODULE = "homework_lock.watchdog"
GUARD_FLAG = "--watchdog"
POLL_SECONDS = 1.0
_DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


def _same_process(pid: int, create_time: float) -> bool:
    try:
        return abs(psutil.Process(pid).create_time() - create_time) < 1.0  # guards against pid reuse
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def launch_app():
    subprocess.Popen(launch_command(RESTARTED_FLAG), cwd=str(ROOT), creationflags=_DETACHED, close_fds=True)


def watch(pid: int, create_time: float, relaunch=launch_app, poll: float = POLL_SECONDS):
    while _same_process(pid, create_time):
        time.sleep(poll)
    relaunch()


def start_guard(app_pid: int | None = None):
    """Start a guard for this app process. It runs on its own (not as a child that ends with the app)."""
    p = psutil.Process(app_pid) if app_pid else psutil.Process()
    # Started through "cmd /c start" so the guard isn't our child process: ending Homework Lock (or its
    # process tree) in Task Manager doesn't end the guard too. Passed as one string so cmd sees the quotes.
    how = f'"{sys.executable}" {GUARD_FLAG}' if FROZEN else f'"{pythonw()}" -m {GUARD_MODULE}'
    cmd = f'cmd /c start "" {how} {p.pid} {p.create_time()}'
    subprocess.Popen(cmd, cwd=str(ROOT), creationflags=subprocess.CREATE_NO_WINDOW)


def find_guards(app_pid: int | None = None) -> list[psutil.Process]:
    app_pid = app_pid or psutil.Process().pid
    names = {"pythonw.exe", "python.exe", Path(sys.executable).name.lower()}
    found = []
    for p in psutil.process_iter(["name", "cmdline"]):
        cmd = p.info["cmdline"] or []
        if (p.info["name"] or "").lower() in names and (GUARD_MODULE in cmd or GUARD_FLAG in cmd) \
                and str(app_pid) in cmd:
            found.append(p)
    return found


def stop_guards(app_pid: int | None = None):
    for p in find_guards(app_pid):
        try:
            p.kill()
        except psutil.Error:
            pass


if __name__ == "__main__":
    watch(int(sys.argv[1]), float(sys.argv[2]))
