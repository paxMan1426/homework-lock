"""Where things live, running from source (python main.pyw) or as the packaged HomeworkLock.exe."""
from __future__ import annotations

import os
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
ROOT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent.parent
# Settings and the log: next to the code when run from source, in %APPDATA% for the installed app, so they
# survive updates and don't depend on where the exe was downloaded to.
DATA_DIR = Path(os.environ["APPDATA"]) / "HomeworkLock" if FROZEN else ROOT
LOG_PATH = DATA_DIR / "homework_lock.log"


def pythonw() -> str:
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    return str(candidate if candidate.exists() else exe)


def launch_command(*args: str) -> list[str]:
    """Command that starts Homework Lock with these arguments."""
    if FROZEN:
        return [sys.executable, *args]
    return [pythonw(), str(ROOT / "main.pyw"), *args]
