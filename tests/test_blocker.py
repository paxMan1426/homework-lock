import shutil
import subprocess
import time
from pathlib import Path

import psutil

from homework_lock.blocker import Blocker
from homework_lock.config import Config


def _dummy_exe(tmp_path: Path) -> Path:
    exe = tmp_path / "hwlock_dummy.exe"
    shutil.copy(Path(r"C:\Windows\System32\ping.exe"), exe)
    return exe


def test_config_add_remove_and_protected(tmp_path):
    cfg = Config(tmp_path / "config.json")
    assert cfg.add_app("Steam")
    assert "steam.exe" in cfg.blocked_apps()
    assert not cfg.add_app("explorer.exe")
    assert not cfg.add_app("python.exe")
    cfg.remove_app("STEAM.EXE")
    assert cfg.blocked_apps() == set()
    # persisted
    cfg.add_app("game.exe")
    assert Config(tmp_path / "config.json").blocked_apps() == {"game.exe"}


def test_blocker_kills_when_locked(tmp_path):
    cfg = Config(tmp_path / "config.json")
    exe = _dummy_exe(tmp_path)
    cfg.add_app(exe.name)
    proc = subprocess.Popen([str(exe), "-n", "60", "127.0.0.1"], stdout=subprocess.DEVNULL)
    try:
        killed = Blocker(cfg, min_age=0).sweep()
        assert exe.name in killed
        proc.wait(timeout=5)
        assert not psutil.pid_exists(proc.pid) or proc.poll() is not None
    finally:
        if proc.poll() is None:
            proc.kill()


def test_blocker_leaves_apps_when_unlocked(tmp_path):
    cfg = Config(tmp_path / "config.json")
    exe = _dummy_exe(tmp_path)
    cfg.add_app(exe.name)
    cfg.set(unlocked_until=time.time() + 60)
    proc = subprocess.Popen([str(exe), "-n", "60", "127.0.0.1"], stdout=subprocess.DEVNULL)
    try:
        assert Blocker(cfg, min_age=0).sweep() == []
        assert proc.poll() is None
    finally:
        proc.kill()


def test_new_process_gets_grace_period(tmp_path):
    """Freshly launched apps are closed only after MIN_AGE, so Explorer shows no error dialog."""
    cfg = Config(tmp_path / "config.json")
    exe = _dummy_exe(tmp_path)
    cfg.add_app(exe.name)
    proc = subprocess.Popen([str(exe), "-n", "60", "127.0.0.1"], stdout=subprocess.DEVNULL)
    try:
        b = Blocker(cfg, min_age=1.0)
        assert b.sweep() == [] and proc.poll() is None
        time.sleep(1.1)
        assert exe.name in b.sweep()
    finally:
        if proc.poll() is None:
            proc.kill()


def _copy(src: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(Path(src), dest)
    return dest


def _run(*args) -> subprocess.Popen:
    return subprocess.Popen([str(a) for a in args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _gone(proc: subprocess.Popen) -> bool:
    try:
        proc.wait(timeout=5)
        return True
    except subprocess.TimeoutExpired:
        proc.kill()
        return False


def test_renamed_copy_is_blocked(tmp_path):
    cfg = Config(tmp_path / "config.json")
    cfg.add_app("hwlock_original.exe")
    renamed = _copy(r"C:\Windows\System32\ping.exe", tmp_path / "totally_not_a_game.exe")
    proc = _run(renamed, "-n", "60", "127.0.0.1")
    b = Blocker(cfg, min_age=0)
    try:
        assert b.sweep() == []                        # different original name: left alone
        cfg.add_app("ping.exe")                       # its real (original) name is ping.exe
        assert "ping.exe" in b.sweep() and _gone(proc)
    finally:
        if proc.poll() is None:
            proc.kill()


def test_game_started_by_blocked_launcher_is_blocked(tmp_path):
    cfg = Config(tmp_path / "config.json")
    launcher = _copy(r"C:\Windows\System32\cmd.exe", tmp_path / "hwlock_launcher.exe")
    game = _copy(r"C:\Windows\System32\ping.exe", tmp_path / "hwlock_game.exe")
    cfg.add_app(launcher.name)
    proc = _run(launcher, "/c", game, "-n", "60", "127.0.0.1")
    try:
        time.sleep(0.5)
        children = psutil.Process(proc.pid).children()
        assert children and children[0].name().lower() == game.name
        killed = Blocker(cfg, min_age=0).sweep()
        assert killed.count(launcher.name) == 2       # the launcher and the game it started
        assert _gone(proc) and not children[0].is_running()
    finally:
        if proc.poll() is None:
            proc.kill()


def test_minecraft_java_game_is_blocked(tmp_path_factory):
    folder = tmp_path_factory.mktemp("jre")  # tmp_path would put this test's name (with "minecraft") in the path
    cfg = Config(folder / "config.json")
    cfg.add_app("minecraftlauncher.exe")
    java = _copy(r"C:\Windows\System32\cmd.exe", folder / "bin" / "javaw.exe")
    other = _run(java, "/c", "ping -n 60 127.0.0.1 & rem some.other.JavaApp")
    game = _run(java, "/c", "ping -n 60 127.0.0.1 & rem net.minecraft.client.main.Main")
    try:
        killed = Blocker(cfg, min_age=0).sweep()
        assert "Minecraft" in killed and _gone(game)  # named as the game, not the launcher
        assert other.poll() is None                   # other Java programs keep running
    finally:
        for p in (other, game):
            if p.poll() is None:
                p.kill()


def test_steam_games_are_blocked(tmp_path):
    cfg = Config(tmp_path / "config.json")
    cfg.add_app("steam.exe")
    game = _copy(r"C:\Windows\System32\ping.exe", tmp_path / "steamapps" / "common" / "Some Game" / "hwlock_sg.exe")
    proc = _run(game, "-n", "60", "127.0.0.1")
    try:
        # named after the game's own description (this stand-in "game" is a copy of ping.exe), not "Steam"
        assert Blocker(cfg, min_age=0).sweep() == ["TCP/IP Ping Command"] and _gone(proc)
    finally:
        if proc.poll() is None:
            proc.kill()


def test_notice_names_the_game_not_its_launcher(tmp_path_factory):
    """Launching Minecraft from CurseForge closes both; the notice says Minecraft."""
    folder = tmp_path_factory.mktemp("cf")
    cfg = Config(folder / "config.json")
    launcher = _copy(r"C:\Windows\System32\cmd.exe", folder / "curseforge.exe")
    cfg.add_app("curseforge.exe")
    cfg.add_app("minecraftlauncher.exe")
    java = _copy(r"C:\Windows\System32\cmd.exe", folder / "bin" / "javaw.exe")
    proc = _run(launcher, "/c", java, "/c", "ping -n 60 127.0.0.1 & rem net.minecraft.client.main.Main")
    seen = []
    try:
        time.sleep(0.7)
        killed = Blocker(cfg, min_age=0, on_kill=seen.append).sweep()
        assert "curseforge.exe" in killed and "Minecraft" in killed
        assert seen == ["Minecraft"]
    finally:
        if proc.poll() is None:
            proc.kill()


def test_blocker_thread_runs(tmp_path):
    cfg = Config(tmp_path / "config.json")
    exe = _dummy_exe(tmp_path)
    cfg.add_app(exe.name)
    seen = []
    b = Blocker(cfg, interval=0.2, on_kill=seen.append)
    b.start()
    proc = subprocess.Popen([str(exe), "-n", "60", "127.0.0.1"], stdout=subprocess.DEVNULL)
    try:
        proc.wait(timeout=8)
        time.sleep(0.1)
        assert exe.name in seen
    finally:
        b.stop()
        if proc.poll() is None:
            proc.kill()
