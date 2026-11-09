"""Shortcuts, taskbar identity and the restart guard, checked against real Windows APIs."""
import shutil
import subprocess
import time
from pathlib import Path

import psutil
import pythoncom
from win32com.propsys import propsys, pscon
from win32com.shell import shell

from homework_lock import shortcuts, watchdog
from homework_lock.icons import app_icon_path


def _load(path):
    link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER,
                                      shell.IID_IShellLink)
    link.QueryInterface(pythoncom.IID_IPersistFile).Load(str(path))
    store = link.QueryInterface(propsys.IID_IPropertyStore)
    return {"target": link.GetPath(shell.SLGP_RAWPATH)[0], "args": link.GetArguments(),
            "icon": link.GetIconLocation(), "aumid": store.GetValue(pscon.PKEY_AppUserModel_ID).GetValue()}


def test_shortcut_has_command_icon_and_app_id(tmp_path):
    lnk = shortcuts.write_shortcut(tmp_path / "Homework Lock.lnk")
    info = _load(lnk)
    assert info["target"].lower().endswith("pythonw.exe")
    assert info["args"].endswith('main.pyw"')
    assert info["icon"][0] == app_icon_path() and Path(info["icon"][0]).exists()
    assert info["aumid"] == shortcuts.APP_ID


def test_find_broken_pythonw_pin_without_touching_files(tmp_path):
    exe = shortcuts.pythonw()
    for name, args in (("Python.lnk", ""), ("Other.lnk", '"C:\\some\\script.pyw"')):
        link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER,
                                          shell.IID_IShellLink)
        link.SetPath(exe)
        link.SetArguments(args)
        link.QueryInterface(pythoncom.IID_IPersistFile).Save(str(tmp_path / name), 0)
    before = (tmp_path / "Python.lnk").read_bytes()
    assert [p.name for p in shortcuts.find_broken_pins(tmp_path)] == ["Python.lnk"]
    assert (tmp_path / "Python.lnk").read_bytes() == before   # never rewritten in place
    assert not shortcuts.unpin(tmp_path / "Other.lnk")        # not a taskbar pin: nothing to unpin


def test_window_identity(root):
    root.update_idletasks()
    hwnd = int(root.wm_frame(), 16)
    shortcuts.set_window_identity(hwnd)
    store = propsys.SHGetPropertyStoreForWindow(hwnd, propsys.IID_IPropertyStore)
    assert store.GetValue(pscon.PKEY_AppUserModel_ID).GetValue() == shortcuts.APP_ID
    assert "main.pyw" in store.GetValue(pscon.PKEY_AppUserModel_RelaunchCommand).GetValue()
    assert store.GetValue(pscon.PKEY_AppUserModel_RelaunchDisplayNameResource).GetValue() == "Homework Lock"
    assert store.GetValue(pscon.PKEY_AppUserModel_RelaunchIconResource).GetValue().startswith(app_icon_path())


def _dummy(tmp_path):
    exe = tmp_path / "hwl_dummy.exe"
    shutil.copy(r"C:\Windows\System32\ping.exe", exe)
    return subprocess.Popen([str(exe), "-n", "60", "127.0.0.1"], stdout=subprocess.DEVNULL)


def test_watch_relaunches_when_app_is_killed(tmp_path):
    proc = _dummy(tmp_path)
    p = psutil.Process(proc.pid)
    relaunched = []
    import threading
    t = threading.Thread(target=watchdog.watch, args=(p.pid, p.create_time(), lambda: relaunched.append(1), 0.1))
    t.start()
    time.sleep(0.4)
    assert not relaunched
    proc.kill()                                    # like "End task" in Task Manager
    t.join(timeout=5)
    assert relaunched == [1]


def test_guard_process_start_find_stop(tmp_path):
    proc = _dummy(tmp_path)
    try:
        watchdog.start_guard(proc.pid)
        guards = []
        for _ in range(40):
            guards = watchdog.find_guards(proc.pid)
            if guards:
                break
            time.sleep(0.25)
        assert len(guards) == 1
        assert guards[0].name().lower() == "pythonw.exe"
        assert guards[0].ppid() != psutil.Process().pid    # runs on its own, not as our child
        watchdog.stop_guards(proc.pid)                     # stop it BEFORE ending the dummy app
        time.sleep(0.5)
        assert watchdog.find_guards(proc.pid) == []
    finally:
        watchdog.stop_guards(proc.pid)
        proc.kill()
