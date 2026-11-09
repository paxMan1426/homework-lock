"""Shortcuts and taskbar identity.

- Desktop + Start Menu shortcuts that start the app without a console window, with the app icon.
- Every shortcut and the main window share one AppUserModelID, so a pinned icon and the running window are
  the same taskbar button.
- The window carries its own relaunch command/name/icon, so "Pin to taskbar" on the running window pins
  Homework Lock instead of a bare "Python" (pythonw.exe with no script, which does nothing when clicked).

Run:  python -m homework_lock.shortcuts
"""
from __future__ import annotations

import os
from pathlib import Path

from .icons import app_icon_path
from .paths import ROOT, launch_command, pythonw  # noqa: F401 - ROOT and pythonw re-exported

NAME = "Homework Lock"
APP_ID = "HomeworkLock.App"
DESCRIPTION = "Block apps until homework is done"


def _quoted(args) -> str:
    return " ".join(f'"{a}"' for a in args)


def launch_args() -> str:
    return _quoted(launch_command()[1:])


def shortcut_dirs() -> list[Path]:
    desktop = Path(os.environ["USERPROFILE"]) / "Desktop"
    onedrive_desktop = Path(os.environ["OneDrive"]) / "Desktop" if os.environ.get("OneDrive") else None
    if onedrive_desktop and onedrive_desktop.exists():
        desktop = onedrive_desktop  # Desktop is redirected to OneDrive on many PCs
    start_menu = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    return [desktop, start_menu]


def _pv(text: str):
    import pythoncom
    from win32com.propsys import propsys
    return propsys.PROPVARIANTType(text, pythoncom.VT_LPWSTR)


def write_shortcut(path: Path) -> Path:
    """Create or overwrite a .lnk that starts Homework Lock, with its icon and AppUserModelID."""
    import pythoncom
    from win32com.propsys import propsys, pscon
    from win32com.shell import shell

    link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER,
                                      shell.IID_IShellLink)
    link.SetPath(launch_command()[0])
    link.SetArguments(launch_args())
    link.SetWorkingDirectory(str(ROOT))
    link.SetIconLocation(app_icon_path(), 0)
    link.SetDescription(DESCRIPTION)
    store = link.QueryInterface(propsys.IID_IPropertyStore)
    store.SetValue(pscon.PKEY_AppUserModel_ID, _pv(APP_ID))
    store.Commit()
    link.QueryInterface(pythoncom.IID_IPersistFile).Save(str(path), 0)
    return path


def set_window_identity(hwnd: int):
    """Tell the taskbar what to pin for this window: our command, name and icon."""
    from win32com.propsys import propsys, pscon
    store = propsys.SHGetPropertyStoreForWindow(hwnd, propsys.IID_IPropertyStore)
    store.SetValue(pscon.PKEY_AppUserModel_RelaunchCommand, _pv(_quoted(launch_command())))
    store.SetValue(pscon.PKEY_AppUserModel_RelaunchDisplayNameResource, _pv(NAME))
    store.SetValue(pscon.PKEY_AppUserModel_RelaunchIconResource, _pv(app_icon_path() + ",0"))
    store.SetValue(pscon.PKEY_AppUserModel_ID, _pv(APP_ID))  # set last: relaunch values need it
    store.Commit()


def taskbar_pins() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Internet Explorer" / "Quick Launch" / "User Pinned" / "TaskBar"


def find_broken_pins(folder: Path | None = None) -> list[Path]:
    """Taskbar pins made from the running window before it had a relaunch command: they start pythonw.exe
    with no arguments, so clicking them does nothing (or shows "Windows cannot find '\\\\'")."""
    import pythoncom
    from win32com.shell import shell
    folder = folder or taskbar_pins()
    broken = []
    for lnk in sorted(folder.glob("*.lnk")) if folder.exists() else []:
        link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None, pythoncom.CLSCTX_INPROC_SERVER,
                                          shell.IID_IShellLink)
        try:
            link.QueryInterface(pythoncom.IID_IPersistFile).Load(str(lnk))
            target = link.GetPath(shell.SLGP_RAWPATH)[0]
            args = link.GetArguments()
        except pythoncom.com_error:
            continue
        if Path(target).name.lower() == "pythonw.exe" and not args.strip():
            broken.append(lnk)
    return broken


def unpin(lnk: Path) -> bool:
    """Unpin through the shell's own "Unpin from taskbar" verb. (Rewriting a pinned .lnk in place does NOT
    work: the taskbar keeps its own copy of the pin, and the result fails with "Windows cannot find '\\\\'".)"""
    import win32com.client
    item = win32com.client.Dispatch("Shell.Application").Namespace(str(lnk.parent)).ParseName(lnk.name)
    if item is None:
        return False
    for verb in item.Verbs():
        if verb.Name.replace("&", "") == "Unpin from taskbar":
            verb.DoIt()
            return True
    return False


def main():
    for folder in shortcut_dirs():
        print("Created", write_shortcut(folder / f"{NAME}.lnk"))
    for lnk in find_broken_pins():
        if unpin(lnk):
            print(f"Removed a broken taskbar pin ({lnk.stem}).")
    print('To pin Homework Lock: right-click it in the Start Menu (or its taskbar button) -> "Pin to taskbar".')


if __name__ == "__main__":
    main()
