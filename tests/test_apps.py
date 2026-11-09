"""Discovery against the real machine (Windows APIs, Start Menu, running windows)."""
import os
import subprocess
import time

from homework_lock import apps
from homework_lock.config import PROTECTED


def test_file_description_real_exe():
    assert apps.file_description(r"C:\Windows\System32\ping.exe")  # "TCP/IP Ping Command"
    assert apps.file_description(r"C:\nope.exe") is None
    assert apps.friendly_name(None, "my_cool-game.exe") == "My Cool Game"


def test_installed_apps_resolve():
    found = apps.installed_apps()
    assert found, "expected some Start Menu apps"
    for e in found:
        assert e["exes"][0].endswith(".exe") and e["exes"][0] not in PROTECTED
        assert "uninstall" not in e["label"].lower()


def test_open_apps_sees_a_window():
    proc = subprocess.Popen(["mspaint.exe"])
    try:
        names = set()
        for _ in range(20):
            names = {x for e in apps.open_apps() for x in e["exes"]}
            if "mspaint.exe" in names:
                break
            time.sleep(0.5)
        assert "mspaint.exe" in names
        assert not names & PROTECTED
    finally:
        subprocess.run(["taskkill", "/IM", "mspaint.exe", "/F"], capture_output=True)


def test_entry_for_file_exe_and_shortcut():
    e = apps.entry_for_file(r"C:\Windows\System32\ping.exe")
    assert e["exes"] == ["ping.exe"]
    assert apps.entry_for_file(r"C:\Windows\explorer.exe") is None
    lnk_dir = os.path.expandvars(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs")
    for root, _, files in os.walk(lnk_dir):
        lnks = [f for f in files if f.endswith(".lnk")]
        for f in lnks:
            e = apps.entry_for_file(os.path.join(root, f))
            if e:
                assert e["exes"][0].endswith(".exe") and e["label"] == f[:-4]
                return


def test_merge_dedupes_and_excludes():
    a = [{"label": "A", "exes": ["a.exe", "b.exe"], "group": "g1"}]
    b = [{"label": "B", "exes": ["b.exe"], "group": "g2"}, {"label": "C", "exes": ["c.exe"], "group": "g2"}]
    out = apps.merge(a, b, exclude={"a.exe"})
    assert [(e["label"], e["exes"]) for e in out] == [("A", ["b.exe"]), ("C", ["c.exe"])]
