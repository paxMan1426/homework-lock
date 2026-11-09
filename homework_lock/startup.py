"""Keep Homework Lock running whenever apps should be locked (per-user scheduled task, no admin needed).

The task runs homework_lock.autostart when you sign in and then every minute. autostart is tiny: it exits at
once if Homework Lock is already running or apps don't need blocking right now (free time, or unlocked), and
otherwise starts Homework Lock minimized. So the app comes back within a minute of a lock starting, even if it
was closed after homework, both processes were ended in Task Manager, or the PC woke from sleep.
"""
from __future__ import annotations

import getpass
import os
import subprocess
import sys
import tempfile
import winreg
from datetime import datetime
from xml.sax.saxutils import escape

from .paths import FROZEN, ROOT, pythonw

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"  # older versions used this; removed on enable
VALUE = "HomeworkLock"  # scheduled task name
STARTUP_FLAG = "--startup"
AUTOSTART_MODULE = "homework_lock.autostart"
AUTOSTART_FLAG = "--autostart"  # the packaged exe runs autostart with this instead of -m
_NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW


def task_action() -> tuple[str, str]:
    """(program, arguments) the scheduled task runs every minute."""
    if FROZEN:
        return sys.executable, AUTOSTART_FLAG
    return pythonw(), f"-m {AUTOSTART_MODULE}"


def _user() -> str:
    domain = os.environ.get("USERDOMAIN")
    return f"{domain}\\{getpass.getuser()}" if domain else getpass.getuser()


def task_xml() -> str:
    user = escape(_user())
    program, arguments = task_action()
    start = datetime.now().replace(second=0, microsecond=0).isoformat()
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Keeps Homework Lock running while apps should be locked.</Description></RegistrationInfo>
  <Triggers>
    <LogonTrigger><Enabled>true</Enabled><UserId>{user}</UserId></LogonTrigger>
    <TimeTrigger>
      <StartBoundary>{start}</StartBoundary><Enabled>true</Enabled>
      <Repetition><Interval>PT1M</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition>
    </TimeTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author"><UserId>{user}</UserId><LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel></Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <ExecutionTimeLimit>PT5M</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec><Command>{escape(program)}</Command><Arguments>{escape(arguments)}</Arguments>
      <WorkingDirectory>{escape(str(ROOT))}</WorkingDirectory></Exec>
  </Actions>
</Task>
"""


def _schtasks(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["schtasks", *args], capture_output=True, text=True, creationflags=_NO_WINDOW)


def is_enabled() -> bool:
    return _schtasks("/Query", "/TN", VALUE).returncode == 0


def _remove_run_key():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, VALUE)
    except FileNotFoundError:
        pass


def enable():
    fd, path = tempfile.mkstemp(suffix=".xml")
    try:
        with os.fdopen(fd, "w", encoding="utf-16") as f:
            f.write(task_xml())
        r = _schtasks("/Create", "/TN", VALUE, "/XML", path, "/F")
    finally:
        os.remove(path)
    if r.returncode != 0:
        raise OSError((r.stderr or r.stdout).strip() or "schtasks failed")
    _remove_run_key()


def disable():
    _schtasks("/Delete", "/TN", VALUE, "/F")
    _remove_run_key()
