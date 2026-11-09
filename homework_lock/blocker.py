"""Background thread that kills blocked processes while locked.

A process is blocked when any of these hold:
- its name is on the blocked list
- it's a copy or renamed version of a blocked .exe (the .exe's built-in original file name gives it away)
- it's a game that runs under another name: Minecraft Java runs as java/javaw.exe, and Steam, Epic and
  Roblox games run as their own .exe from the launcher's game folders
- it was started by a blocked process (a game opened from a blocked launcher), except web browsers
"""
import os
import threading
import time

import psutil

from . import schedule
from .apps import friendly_name, version_string
from .config import PROTECTED, Config

# Killing a process in its first ~1.5 s makes Explorer show "Windows cannot access the specified
# device, path, or file" when the app was launched from a shortcut or the taskbar. Waiting until the
# process is a little older avoids that dialog (measured with Steam: 6/6 dialogs at 0.5 s, 0/12 at 2 s).
MIN_AGE = 2.0

# Blocking any of these also blocks the Minecraft Java game, which runs as java.exe / javaw.exe.
MINECRAFT = {"minecraftlauncher.exe", "minecraft.exe", "minecraft.windows.exe", "curseforge.exe",
             "prismlauncher.exe", "multimc.exe", "tlauncher.exe", "atlauncher.exe", "gdlauncher.exe"}
JAVA = {"java.exe", "javaw.exe"}
# Blocking a launcher also blocks the games installed through it.
GAME_FOLDERS = [
    ({"steam.exe"}, "\\steamapps\\common\\"),
    ({"epicgameslauncher.exe"}, "\\epic games\\"),
    ({"robloxplayerbeta.exe", "robloxstudiobeta.exe"}, "\\roblox\\versions\\"),
]
# A browser opened from a blocked app (a link clicked in Discord) may be needed for homework.
BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "opera_gx.exe", "iexplore.exe"}

# How a process was matched. When one sweep closes a launcher and its game, the notice names the game.
GAME, LISTED, CHILD = 0, 1, 2


class _Facts:
    """What's known about one process. Looked up once per process, not on every sweep."""
    __slots__ = ("path", "original", "minecraft")

    def __init__(self, proc: psutil.Process, name: str):
        try:
            exe = proc.exe()
        except (psutil.Error, OSError):
            exe = ""
        self.path = exe.lower()
        original = version_string(exe, "OriginalFilename") if exe else None
        self.original = (original or "").strip().lower()
        if self.original.endswith(".mui"):
            self.original = self.original[:-4]
        self.minecraft = False
        if name in JAVA:
            try:
                self.minecraft = "minecraft" in " ".join(proc.cmdline()).lower()
            except (psutil.Error, OSError):
                pass


class Blocker(threading.Thread):
    def __init__(self, config: Config, interval: float = 0.5, on_kill=None, min_age: float = MIN_AGE):
        super().__init__(daemon=True, name="Blocker")
        self.config = config
        self.interval = interval
        self.min_age = min_age
        self.on_kill = on_kill  # callback(blocked process name, used for the notice's app name)
        self._stop = threading.Event()
        self._facts: dict[tuple[int, float], _Facts] = {}

    def is_locked(self) -> bool:
        return schedule.is_locked(self.config)

    def _facts_for(self, proc, name, key) -> _Facts:
        facts = self._facts.get(key)
        if facts is None:
            facts = self._facts[key] = _Facts(proc, name)
        return facts

    def match(self, proc, name: str, key, blocked: set[str]) -> tuple[str, int] | None:
        """(name for the notice, GAME or LISTED) if this process is blocked, else None. The name is a
        blocked process name (shown with its label from the blocked list) or the game's own name."""
        if name in blocked:
            return name, LISTED
        facts = self._facts_for(proc, name, key)
        if facts.original and facts.original != name and facts.original in blocked:
            return facts.original, LISTED  # renamed copy
        if facts.minecraft and blocked & MINECRAFT:
            return "Minecraft", GAME  # not the launcher it was started from
        for launchers, folder in GAME_FOLDERS:
            if folder in facts.path and blocked & launchers:
                return friendly_name(facts.path, name), GAME  # the game's own name, e.g. "Terraria"
        return None

    def sweep(self) -> list[str]:
        """Kill every running blocked process once. Returns the blocked app name for each kill."""
        if not self.is_locked():
            return []
        blocked = self.config.blocked_apps() - PROTECTED
        if not blocked:
            return []
        me = os.getpid()
        procs, matched = {}, {}  # pid -> (proc, name, create_time); pid -> blocked app
        for proc in psutil.process_iter(["name", "pid", "ppid", "create_time"]):
            try:
                pid, name = proc.info["pid"], (proc.info["name"] or "").lower()
                created = proc.info["create_time"] or 0.0
                if pid == me or name in PROTECTED:
                    continue
                procs[pid] = (proc, name, created, proc.info["ppid"])
                app = self.match(proc, name, (pid, created), blocked)
                if app:
                    matched[pid] = app
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        # Children of blocked processes (a game started by a blocked launcher).
        for pid, (proc, name, created, ppid) in procs.items():
            if pid in matched or name in BROWSERS:
                continue
            child_created, parent, depth = created, ppid, 0
            while parent in procs and depth < 8:
                _, _, parent_created, grandparent = procs[parent]
                if parent_created > child_created:  # pid was reused; not really the parent
                    break
                if parent in matched:
                    matched[pid] = (matched[parent][0], CHILD)
                    break
                child_created, parent, depth = parent_created, grandparent, depth + 1
        alive = {(pid, created) for pid, (_, _, created, _) in procs.items()}
        self._facts = {k: v for k, v in self._facts.items() if k in alive}

        killed = []
        now = time.time()
        for pid, (app, how) in matched.items():
            proc, _, created, _ = procs[pid]
            if now - created < self.min_age:
                continue  # just launched; next sweep gets it
            try:
                proc.kill()
                killed.append((app, how))
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        if killed and self.on_kill:
            best = min(how for _, how in killed)  # the game rather than its launcher or helpers
            for app in dict.fromkeys(app for app, how in killed if how == best):
                self.on_kill(app)
        return [app for app, _ in killed]

    def run(self):
        while not self._stop.is_set():
            try:
                self.sweep()
            except Exception:  # never let the blocker thread die
                pass
            self._stop.wait(self.interval)

    def stop(self):
        self._stop.set()


def running_process_names() -> list[str]:
    """Distinct names of running user processes, minus protected ones."""
    names = set()
    for proc in psutil.process_iter(["name"]):
        name = (proc.info["name"] or "").lower()
        if name.endswith(".exe") and name not in PROTECTED:
            names.add(name)
    return sorted(names)
