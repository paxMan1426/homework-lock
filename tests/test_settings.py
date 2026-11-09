"""Blocked apps page, Add apps view, and Settings page."""
from unittest import mock

import pytest

from homework_lock.app import MainWindow
from homework_lock.config import Config, verify_secret
from homework_lock.ui_apps import AddAppsView

OPEN = [{"label": "Google Chrome", "exes": ["chrome.exe"], "group": "Open now"},
        {"label": "Some Game", "exes": ["somegame.exe"], "group": "Open now"}]
INSTALLED = [{"label": "Kitten Space Agency", "exes": ["ksa.exe"], "group": "Installed"},
             {"label": "Chrome shortcut", "exes": ["chrome.exe"], "group": "Installed"}]


@pytest.fixture
def window(root, tmp_path):
    made = []

    def make(**cfg):
        config = Config(tmp_path / "c.json")
        if cfg:
            config.set(**cfg)
        w = MainWindow(root, config, cloud_api=mock.Mock())
        made.append(w)
        return w

    yield make
    for w in made:
        root.after_cancel(w._tick_id)


@pytest.fixture
def picker(root, tmp_path):
    cfg = Config(tmp_path / "c.json")
    with mock.patch("homework_lock.ui_apps.appfinder.open_apps", return_value=OPEN):
        p = AddAppsView(root, cfg, load_installed=False)
    p.installed = INSTALLED
    p.render()
    return p, cfg


def _entry(p, label):
    return next(e for e in p.visible if e["label"] == label)


def _set_search(p, text):
    p.search.delete(0, "end")
    p.search.insert(0, text)
    p.render()


def test_pin_is_salted_hash(tmp_path):
    cfg = Config(tmp_path / "c.json")
    cfg.set_pin("1234")
    stored = cfg.get("pin_hash")
    assert "1234" not in stored and "$" in stored
    assert cfg.check_pin("1234") and not cfg.check_pin("0000")
    other = Config(tmp_path / "d.json")
    other.set_pin("1234")
    assert other.get("pin_hash") != stored
    assert not verify_secret("x", None)


def test_picker_groups_and_dedupe(picker):
    p, _ = picker
    groups = list(dict.fromkeys(e["group"] for e in p.visible))
    assert groups == ["Open now", "Popular games & apps", "Installed"]
    labels = [e["label"] for e in p.visible]
    assert labels.count("Google Chrome") == 1 and "Chrome shortcut" not in labels
    assert "Roblox" in labels and "Kitten Space Agency" in labels


def test_picker_tick_and_block(picker):
    p, cfg = picker
    assert p.block_btn.cget("state") == "disabled"
    p.toggle(_entry(p, "Roblox"))
    p.toggle(_entry(p, "Some Game"))
    assert p.block_btn.cget("text") == "Block 2 apps"
    p.toggle(_entry(p, "Some Game"))
    # clicking the real checkbox works too
    row, cb = p._rows[("Installed", ("ksa.exe",), "Kitten Space Agency")]
    cb.toggle()
    assert cb.get() == 1
    p.commit()
    assert cfg.blocked_apps() == {"robloxplayerbeta.exe", "robloxstudiobeta.exe", "ksa.exe"}
    assert cfg.app_label("ksa.exe") == "Kitten Space Agency"


def test_picker_search_and_custom_name(picker):
    p, cfg = picker
    _set_search(p, "rob")
    assert p.visible[0]["label"] == "Roblox"
    _set_search(p, "mygame")
    assert [e["label"] for e in p.visible] == ['Block "mygame.exe"']
    p.toggle_first_match()
    _set_search(p, "explorer")
    assert not any("explorer.exe" in e["exes"] for e in p.visible)
    p.commit()
    assert cfg.blocked_apps() == {"mygame.exe"}


def test_window_pick_and_browse(picker):
    p, cfg = picker
    with mock.patch("homework_lock.ui_apps.appfinder.foreground_app",
                    return_value={"label": "Paint", "exes": ["mspaint.exe"], "group": "Picked"}):
        p._pick_countdown(0)
    assert p.visible[0]["group"] == "Picked" and ("mspaint.exe",) in p.checked
    with mock.patch("homework_lock.ui_apps.appfinder.foreground_app", return_value=None), \
         mock.patch("homework_lock.ui_apps.messagebox.showinfo") as info:
        p._pick_countdown(0)
        info.assert_called_once()
    with mock.patch("homework_lock.ui_apps.filedialog.askopenfilename", return_value=r"C:\Games\cool.exe"), \
         mock.patch("homework_lock.ui_apps.appfinder.entry_for_file",
                    return_value={"label": "Cool Game", "exes": ["cool.exe"], "group": "Picked"}):
        p.browse()
    p.commit()
    assert cfg.blocked_apps() == {"mspaint.exe", "cool.exe"}


def test_apps_page_list_add_remove(window):
    w = window()
    w.ctl.unlock(10)
    w.navigate("apps")
    page = w.pages["apps"]
    assert page.row_widgets == []  # empty state
    w.config.add_app("robloxplayerbeta.exe", "Roblox")
    w.config.add_app("robloxstudiobeta.exe", "Roblox")
    w.config.add_app("game.exe")
    page.refresh()
    assert [(n, e) for n, e, _ in page.row_widgets] == [
        ("game.exe", ["game.exe"]), ("Roblox", ["robloxplayerbeta.exe", "robloxstudiobeta.exe"])]
    page.remove(page.row_widgets[1][1])
    assert w.config.blocked_apps() == {"game.exe"}
    with mock.patch("homework_lock.ui_apps.appfinder.open_apps", return_value=[]), \
         mock.patch("homework_lock.ui_apps.appfinder.installed_apps", return_value=[]):
        page.show_add()
    assert page.add_view is not None and not page.list_view.winfo_manager()
    page.add_view.close()
    assert page.add_view is None and page.list_view.winfo_manager() == "grid"


def test_student_cant_remove_apps_while_locked(window):
    w = window()
    w.config.add_app("game.exe")
    w.navigate("apps")
    page = w.pages["apps"]
    button = page.row_widgets[0][2].winfo_children()[-1]
    assert button.cget("state") == "disabled"
    page.remove(["game.exe"])
    assert w.config.blocked_apps() == {"game.exe"}
    w.config.add_app("other.exe")                     # adding more is still fine
    assert w.config.blocked_apps() == {"game.exe", "other.exe"}

    w.ctl.unlock(10)
    w.tick()                                          # the page follows the lock state
    w.root.after_cancel(w._tick_id)
    assert page.row_widgets[0][2].winfo_children()[-1].cget("state") == "normal"
    page.remove(["game.exe"])
    assert w.config.blocked_apps() == {"other.exe"}


def test_parent_can_remove_apps_while_locked(window):
    w = window(mode="parent")
    w.config.add_app("game.exe")
    w.admin_until = float("inf")                      # PIN already entered
    w.navigate("apps")
    w.pages["apps"].remove(["game.exe"])
    assert w.config.blocked_apps() == set()


def test_settings_page(window):
    w = window()
    w.navigate("settings")
    s = w.pages["settings"]
    s.on_minutes(45)
    assert w.config.get("unlock_minutes") == 30       # can't be changed while apps are locked
    w.ctl.unlock(10)
    s.refresh()
    s.on_minutes(45)
    assert w.config.get("unlock_minutes") == 45
    assert s.totp_btn.cget("state") == "disabled"  # needs a PIN first
    # switching to Parent without a PIN walks through creating one
    with mock.patch("homework_lock.app.messagebox.showinfo"), \
         mock.patch("homework_lock.app.ask_text", side_effect=["4321", "4321"]):
        s.on_mode("Parent")
    assert w.config.get("mode") == "parent" and w.config.check_pin("4321")
    assert s.mode_seg.get() == "Parent" and s.totp_btn.cget("state") == "normal"
    # cancelling PIN creation keeps Student mode
    w.config.set(mode="self", pin_hash=None)
    with mock.patch("homework_lock.app.messagebox.showinfo"), \
         mock.patch("homework_lock.app.ask_text", return_value=None):
        s.on_mode("Parent")
    assert w.config.get("mode") == "self" and s.mode_seg.get() == "Student"
    with mock.patch("homework_lock.ui_settings.ctk.set_appearance_mode") as theme:
        s.on_theme("Dark")
        theme.assert_called_with("dark")
    assert w.config.get("appearance") == "dark"


def test_bad_pin_rejected(window):
    w = window()
    with mock.patch("homework_lock.app.ask_text", return_value="12"), \
         mock.patch("homework_lock.app.messagebox.showerror") as err:
        assert not w.change_pin()
        err.assert_called_once()
    with mock.patch("homework_lock.app.ask_text", side_effect=["1234", "9999"]), \
         mock.patch("homework_lock.app.messagebox.showerror"):
        assert not w.change_pin()
    assert not w.config.has_pin()
