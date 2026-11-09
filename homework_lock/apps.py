"""Find apps the user might want to block, with friendly names."""
from __future__ import annotations

import ctypes
import json
import os
import re
import subprocess
from ctypes import wintypes
from pathlib import Path

import psutil

from .config import PROTECTED, normalize_app

# label -> process names. Some games run under more than one process.
POPULAR = [
    ("Roblox", ["robloxplayerbeta.exe", "robloxstudiobeta.exe"]),
    ("Minecraft", ["minecraftlauncher.exe", "minecraft.exe", "minecraft.windows.exe"]),  # + Java game, see blocker
    ("CurseForge", ["curseforge.exe"]),
    ("Fortnite", ["fortniteclient-win64-shipping.exe", "fortnitelauncher.exe"]),
    ("Epic Games Launcher", ["epicgameslauncher.exe"]),
    ("Steam", ["steam.exe"]),
    ("Discord", ["discord.exe"]),
    ("Valorant / Riot Client", ["valorant-win64-shipping.exe", "riotclientservices.exe"]),
    ("League of Legends", ["leagueclient.exe", "league of legends.exe"]),
    ("Battle.net", ["battle.net.exe"]),
    ("Xbox app", ["xboxpcapp.exe"]),
    ("Spotify", ["spotify.exe"]),
    ("Google Chrome", ["chrome.exe"]),
    ("Microsoft Edge", ["msedge.exe"]),
    ("Firefox", ["firefox.exe"]),
]

_SKIP_SHORTCUT = re.compile(r"uninstall|setup|install|help|readme|manual|website|update|repair|support|license|"
                            r"documentation|release notes|private browsing", re.I)
# Background helper processes that own a window but aren't something you'd block on their own.
_SKIP_OPEN = re.compile(r"helper|\bhost\b|service|broker|crash|updater|overlay|notification|tray", re.I)


def _entry(label: str, exes, group: str) -> dict:
    return {"label": label, "exes": [normalize_app(e) for e in exes], "group": group}


# ---------- friendly names from the .exe's version info ----------
def file_description(path: str) -> str | None:
    return version_string(path, "FileDescription")


def version_string(path: str, field: str) -> str | None:
    """A string from the .exe's version info, such as FileDescription or OriginalFilename."""
    try:
        ver = ctypes.windll.version
        size = ver.GetFileVersionInfoSizeW(path, None)
        if not size:
            return None
        buf = ctypes.create_string_buffer(size)
        if not ver.GetFileVersionInfoW(path, 0, size, buf):
            return None
        ptr, n = ctypes.c_void_p(), wintypes.UINT()
        if not ver.VerQueryValueW(buf, r"\VarFileInfo\Translation", ctypes.byref(ptr), ctypes.byref(n)) or n.value < 4:
            return None
        lang, cp = ctypes.cast(ptr, ctypes.POINTER(wintypes.WORD * 2)).contents
        key = rf"\StringFileInfo\{lang:04x}{cp:04x}\{field}"
        if not ver.VerQueryValueW(buf, key, ctypes.byref(ptr), ctypes.byref(n)) or not n.value:
            return None
        text = ctypes.wstring_at(ptr, n.value).split("\x00", 1)[0].strip()
        return text or None
    except (OSError, AttributeError):
        return None


def friendly_name(exe_path: str | None, exe_name: str) -> str:
    if exe_path:
        desc = file_description(exe_path)
        if desc:
            return desc
    return Path(exe_name).stem.replace("_", " ").replace("-", " ").title()


# ---------- apps with a visible window right now ----------
_user32 = ctypes.windll.user32 if os.name == "nt" else None


def _window_pids() -> set[int]:
    pids = set()
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        if _user32.IsWindowVisible(hwnd) and _user32.GetWindowTextLengthW(hwnd) > 0 and not _cloaked(hwnd):
            pid = wintypes.DWORD()
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            pids.add(pid.value)
        return True

    _user32.EnumWindows(proto(cb), 0)
    return pids


def _cloaked(hwnd) -> bool:
    val = wintypes.DWORD()
    try:
        ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(val), ctypes.sizeof(val))  # DWMWA_CLOAKED
    except OSError:
        return False
    return bool(val.value)


def _proc_entry(pid: int, group: str) -> dict | None:
    try:
        p = psutil.Process(pid)
        name = p.name().lower()
        try:
            path = p.exe()
        except (psutil.AccessDenied, OSError):
            path = None
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None
    if name in PROTECTED or pid == os.getpid():
        return None
    return _entry(friendly_name(path, name), [name], group)


def open_apps() -> list[dict]:
    seen, out = set(), []
    for pid in _window_pids():
        e = _proc_entry(pid, "Open now")
        if e and e["exes"][0] not in seen and not _SKIP_OPEN.search(e["label"]):
            seen.add(e["exes"][0])
            out.append(e)
    return sorted(out, key=lambda e: e["label"].lower())


def foreground_app() -> dict | None:
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return None
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return _proc_entry(pid.value, "Picked")


# ---------- installed apps (Start Menu shortcuts) ----------
_PS = r"""
$sh = New-Object -ComObject WScript.Shell
$dirs = "$env:ProgramData\Microsoft\Windows\Start Menu\Programs", "$env:APPDATA\Microsoft\Windows\Start Menu\Programs"
@(Get-ChildItem $dirs -Recurse -Filter *.lnk -ErrorAction SilentlyContinue | ForEach-Object {
  @{ n = $_.BaseName; t = $sh.CreateShortcut($_.FullName).TargetPath }
}) | ConvertTo-Json -Compress
"""


def resolve_shortcut(path: str) -> str | None:
    ps = f"(New-Object -ComObject WScript.Shell).CreateShortcut('{path.replace(chr(39), chr(39) * 2)}').TargetPath"
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                             timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def installed_apps() -> list[dict]:
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", _PS], capture_output=True, text=True,
                             timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        items = json.loads(out.stdout or "[]")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return []
    if isinstance(items, dict):
        items = [items]
    seen, result = set(), []
    for it in items:
        target, name = it.get("t") or "", it.get("n") or ""
        exe = os.path.basename(target).lower()
        if not exe.endswith(".exe") or exe in PROTECTED or exe in seen or _SKIP_SHORTCUT.search(name):
            continue
        seen.add(exe)
        result.append(_entry(name, [exe], "Installed"))
    return sorted(result, key=lambda e: e["label"].lower())


def popular_apps() -> list[dict]:
    return [_entry(label, exes, "Popular games & apps") for label, exes in POPULAR]


def entry_for_file(path: str) -> dict | None:
    """Entry for an .exe or a shortcut (.lnk) the user browsed to."""
    if path.lower().endswith(".lnk"):
        target = resolve_shortcut(path)
        label = Path(path).stem
        if not target or not target.lower().endswith(".exe"):
            return None
        path = target
    else:
        label = None
    exe = os.path.basename(path).lower()
    if not exe.endswith(".exe") or exe in PROTECTED:
        return None
    return _entry(label or friendly_name(path, exe), [exe], "Picked")


def merge(*groups: list[dict], exclude: set[str] = frozenset()) -> list[dict]:
    """Combine groups, dropping exes already blocked or shown in an earlier group."""
    seen, out = set(exclude), []
    for group in groups:
        for e in group:
            exes = [x for x in e["exes"] if x not in seen]
            if exes:
                seen.update(exes)
                out.append({**e, "exes": exes})
    return out
