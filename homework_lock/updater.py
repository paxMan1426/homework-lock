"""Auto-update for the packaged app (a folder with HomeworkLock.exe, shipped as HomeworkLock.zip).

1. The running app finds a newer GitHub release and unpacks its zip into a temp folder.
2. It starts the NEW exe from there with --finish-update and quits.
3. The new exe waits for the old one to exit, copies itself over the install folder, and starts it from there.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

from .paths import FROZEN, ROOT
from .version import GITHUB_REPO, VERSION

ASSET_NAME = "HomeworkLock.zip"
EXE_NAME = "HomeworkLock.exe"
FINISH_FLAG = "--finish-update"
UPDATE_DIR = Path(tempfile.gettempdir()) / "HomeworkLock-update"
_DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


def parse_version(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.strip().lstrip("vV").split(".") if x.isdigit())


def _get(url: str, timeout: float):
    req = urllib.request.Request(url, headers={"User-Agent": f"HomeworkLock/{VERSION}",
                                               "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=timeout)


def latest_update() -> tuple[str, str] | None:
    """(version, download URL) if GitHub has a newer release than this app, else None."""
    if "YOUR-" in GITHUB_REPO:
        return None  # repo not filled in yet
    with _get(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest", 15) as r:
        rel = json.loads(r.read())
    tag = rel.get("tag_name") or ""
    asset = next((a for a in rel.get("assets", []) if a.get("name") == ASSET_NAME), None)
    if asset and parse_version(tag) > parse_version(VERSION):
        return tag.lstrip("vV"), asset["browser_download_url"]
    return None


def download(url: str) -> Path:
    """Download and unpack the release. Returns the folder holding the new HomeworkLock.exe."""
    shutil.rmtree(UPDATE_DIR, ignore_errors=True)
    UPDATE_DIR.mkdir(parents=True)
    zpath = UPDATE_DIR / ASSET_NAME
    with _get(url, 60) as r, open(zpath, "wb") as f:
        shutil.copyfileobj(r, f)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(UPDATE_DIR / "new")
    zpath.unlink()
    exe = next((UPDATE_DIR / "new").rglob(EXE_NAME), None)
    if exe is None:
        raise OSError("the download has no HomeworkLock.exe")
    return exe.parent


def start_finisher(new_dir: Path):
    """Hand over to the new version; the caller then quits."""
    subprocess.Popen([str(new_dir / EXE_NAME), FINISH_FLAG, str(ROOT), str(os.getpid())],
                     cwd=str(new_dir), creationflags=_DETACHED, close_fds=True)


def finish_update(install_dir: str, old_pid: str):
    """Runs in the NEW exe from the temp folder: copy this version over the install folder, then start it."""
    import psutil
    src, dst = Path(sys.executable).parent, Path(install_dir)
    try:
        psutil.Process(int(old_pid)).wait(timeout=60)
    except (psutil.Error, ValueError):
        pass
    target_exe = str(dst / EXE_NAME).lower()
    for _ in range(30):
        # The scheduled task may have started the old version again in the meantime: end it first.
        for p in psutil.process_iter(["exe"]):
            if (p.info["exe"] or "").lower() == target_exe:
                try:
                    p.kill()
                except psutil.Error:
                    pass
        try:
            shutil.copytree(src, dst, dirs_exist_ok=True)
            break
        except OSError:
            time.sleep(1)
    else:
        logging.error("update: could not copy the new version into %s", dst)
    subprocess.Popen([str(dst / EXE_NAME)], cwd=str(dst), creationflags=_DETACHED, close_fds=True)


def remove_leftovers():
    """Delete the temp copy from the last update (it was still running then)."""
    if FROZEN and UPDATE_DIR not in Path(sys.executable).parents:
        shutil.rmtree(UPDATE_DIR, ignore_errors=True)
