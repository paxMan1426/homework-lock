import os
import time
from unittest import mock

import pytest

from homework_lock.app import AttemptLimiter, Controller, MainWindow, fmt_remaining
from homework_lock.cloud import CloudError
from homework_lock.config import Config
from homework_lock.ui_common import PromptDialog
from homework_lock.ui_home import SECRET_TAPS


class FakeCloud:
    """Stands in for the online service."""

    def __init__(self, approved=True):
        self.approved = approved
        self.status = {"status": "open"}
        self.checked, self.reports = [], []

    def verdict(self):
        return {"approved": self.approved, "reason": "ok" if self.approved else "Too blurry.", "subject": "Science",
                "pages": [{"page": 1, "complete": self.approved, "issue": "" if self.approved else "Too blurry."}]}

    def new_session(self, config):
        return "tok123", "https://worker.test/s/tok123"

    def poll(self, config, token):
        return self.status

    def check_photos(self, config, pages):
        self.checked.append(list(pages))
        return self.verdict()

    def send_report(self, config, text):
        self.reports.append(text)


def tick(w, times=1):
    for _ in range(times):
        w.root.after_cancel(w._tick_id)
        w._next_poll = 0
        w.tick()


@pytest.fixture
def make_window(root, tmp_path):
    made = []

    def make(cloud=None, **cfg):
        config = Config(tmp_path / "c.json")
        if cfg:
            config.set(**cfg)
        w = MainWindow(root, config, cloud_api=cloud or FakeCloud(), blocker=mock.Mock())
        w.run_in_background = lambda fn: fn()  # no threads in tests: results arrive on the next tick
        made.append(w)
        return w

    yield make
    for w in made:
        root.after_cancel(w._tick_id)


def _phone_finishes(w):
    """The phone's verdict arrives: one tick polls, the next applies the answer."""
    w.cloud.status = {"status": "done", "result": w.cloud.verdict()}
    tick(w, 2)


def test_controller(tmp_path):
    ctl = Controller(Config(tmp_path / "c.json"))
    assert ctl.is_locked()
    ctl.unlock(2)
    assert not ctl.is_locked() and 119 < ctl.remaining() <= 120
    assert ctl.config.get("unlock_length") == 120
    ctl.lock()
    assert ctl.is_locked()
    assert fmt_remaining(65) == "01:05" and fmt_remaining(3725) == "1:02:05"


def test_photo_unlocks_then_relocks(root, make_window):
    w = make_window(unlock_minutes=1)
    w.show_qr()
    tick(w)
    assert w.home.qr_visible and w.home.qr_card.winfo_manager() == "grid"
    assert w.qr_url == "https://worker.test/s/tok123"
    assert w.home.link_entry.get() == w.qr_url        # the same link, for typing or copying
    w.home.copy_link()
    assert w.root.clipboard_get() == w.qr_url
    assert w.home.open_btn.winfo_manager() == "pack"   # uploads allowed by default
    with mock.patch("homework_lock.ui_home.webbrowser.open") as open_:
        w.home.open_link()
    open_.assert_called_once_with(w.qr_url)
    assert "Apps are blocked" == w.home.big.cget("text")
    w.cloud.status = {"status": "checking"}            # the phone tapped Done
    tick(w, 2)
    assert w.checking and "Checking" in w.home.detail.cget("text")
    _phone_finishes(w)
    assert not w.ctl.is_locked() and w.session is None
    tick(w)
    mm, ss = map(int, w.home.big.cget("text").split(":"))
    assert 50 <= mm * 60 + ss <= 60
    assert not w.home.qr_visible                       # QR hidden once unlocked
    assert "Science" in w.home.detail.cget("text")
    assert "Unlocked" in w.side_status.cget("text")
    assert 0.8 < w.home.progress.get() <= 1.0
    assert w.home._shown_buttons == [w.home.lock_btn]
    # time runs out -> locks again automatically
    w.config.set(unlocked_until=time.time() - 1)
    w.root.after_cancel(w._tick_id)
    w.tick()
    assert w.home.big.cget("text") == "Apps are blocked"
    w.blocker.sweep.assert_called()


def test_rejected_photo_shows_reason(root, make_window):
    w = make_window(cloud=FakeCloud(approved=False))
    w.show_qr()
    tick(w)
    _phone_finishes(w)
    assert w.ctl.is_locked()
    assert w.home.banner.winfo_manager() == "grid"
    assert "Too blurry" in w.home.banner_text.cget("text")
    w.home.banner_close.invoke()                       # the X closes the banner
    assert not w.home.banner.winfo_manager()


def test_scan_cant_start_offline(root, make_window):
    w = make_window()
    w.cloud.new_session = mock.Mock(side_effect=CloudError("Couldn't reach the online service."))
    with mock.patch("homework_lock.app.messagebox.showerror") as err:
        w.show_qr()
        tick(w)
    assert "Couldn't reach" in err.call_args[0][1]
    assert not w.home.qr_visible


def test_report_a_problem(root, make_window):
    w = make_window()
    with mock.patch("homework_lock.app.ReportDialog") as dialog, \
         mock.patch("homework_lock.app.messagebox.showinfo") as info:
        dialog.return_value.show.return_value = "The camera page is blank"
        w.report_problem()
        tick(w)
    assert w.cloud.reports == ["The camera page is blank"]
    info.assert_called_once()


def test_title_shows_beta_version(root, make_window):
    from homework_lock.version import VERSION
    w = make_window()
    assert w.root.title() == f"Homework Lock Beta v{VERSION}"


def test_student_cannot_quit_while_locked(root, make_window):
    w = make_window()
    assert w.ctl.is_locked()
    with mock.patch("homework_lock.app.messagebox.showinfo") as info, \
         mock.patch("homework_lock.app.messagebox.askyesno") as ask, \
         mock.patch.object(w, "shutdown") as down:
        w.request_quit()
        info.assert_called_once()
        assert "can't be closed" in info.call_args[0][1]
        ask.assert_not_called()
        down.assert_not_called()


def test_student_can_quit_after_homework_with_confirm(root, make_window):
    w = make_window()
    w.ctl.unlock(10)
    with mock.patch("homework_lock.app.messagebox.askyesno", return_value=False) as ask, \
         mock.patch.object(w, "shutdown") as down:
        w.request_quit()
        ask.assert_called_once()
        down.assert_not_called()
    with mock.patch("homework_lock.app.messagebox.askyesno", return_value=True), \
         mock.patch.object(w, "shutdown") as down:
        w.request_quit()
        down.assert_called_once()


def test_close_button_minimizes(root, make_window):
    w = make_window()
    with mock.patch.object(w.root, "iconify") as icon, mock.patch.object(w, "shutdown") as down:
        w.root.protocol("WM_DELETE_WINDOW")  # handler is registered
        w.minimize()
        icon.assert_called_once()
        down.assert_not_called()


def test_close_button_closes_when_unlocked(root, make_window):
    w = make_window()
    w.ctl.unlock(10)
    with mock.patch.object(w.root, "iconify") as icon, mock.patch.object(w, "shutdown") as down:
        w.minimize()
        down.assert_called_once()
        icon.assert_not_called()


def test_quit_stops_guard_and_guard_is_restarted(root, make_window):
    w = make_window()
    w.guarded = True
    with mock.patch("homework_lock.app.watchdog.find_guards", return_value=[]), \
         mock.patch("homework_lock.app.watchdog.start_guard") as start:
        w.check_guard()
        start.assert_called_once()                   # guard was ended -> started again
    with mock.patch("homework_lock.app.watchdog.stop_guards") as stop, \
         mock.patch.object(w.root, "destroy"), mock.patch.object(w.blocker, "stop"):
        w.shutdown()
        stop.assert_called_once()                    # normal quit: nothing restarts the app
    assert w.guarded is False


def test_parent_mode_pin_gates(root, make_window):
    w = make_window()
    w.config.set_pin("2468")
    w.config.set(mode="parent")
    w.home.refresh()
    assert w.home.override_btn in w.home._shown_buttons
    with mock.patch("homework_lock.app.ask_text", return_value="0000"), \
         mock.patch("homework_lock.app.messagebox.showerror"), \
         mock.patch.object(w, "shutdown") as down:
        w.request_quit()
        w.override_unlock()
        w.navigate("settings")
        down.assert_not_called()
    assert w.ctl.is_locked() and w.current == "home"
    with mock.patch("homework_lock.app.ask_text", return_value="2468") as ask:
        w.override_unlock()
        assert not w.ctl.is_locked()
        w.navigate("settings")
        assert w.current == "settings"
        w.navigate("apps")                 # PIN still fresh: no second prompt
        assert ask.call_count == 2
        w.navigate("home")
        w.navigate("apps")                 # leaving to Home requires it again
        assert ask.call_count == 3


def test_blocked_notice(root, make_window):
    w = make_window()
    w.config.add_app("steam.exe", "Steam")
    w.notify_blocked("steam.exe")          # from the blocker thread
    w.notify_blocked("steam.exe")          # Steam often restarts itself: only one notice
    w.root.after_cancel(w._tick_id)
    w.tick()
    assert w.toast is not None and w.toast.winfo_exists()
    assert w.toast.title_label.cget("text") == "Steam is blocked"
    first = w.toast
    w.notify_blocked("steam.exe")
    w.root.after_cancel(w._tick_id)
    w.tick()
    assert w.toast is first                # throttled
    assert first.on_click == w.bring_to_front
    first.on_click = front = mock.Mock()
    first._clicked()
    front.assert_called_once()
    assert not first.winfo_exists()


def test_prompt_dialog(root):
    d = PromptDialog(root, "Parent PIN", "Enter PIN", secret=True)
    assert d.entry.cget("show") == "•"

    def type_and_ok():
        d.entry.insert(0, "1234")
        d.ok()
    root.after(200, type_and_ok)
    assert d.show() == "1234"
    d2 = PromptDialog(root, "x", "y")
    root.after(200, d2.cancel)
    assert d2.show() is None


def test_attempt_limiter():
    lim = AttemptLimiter(limit=3, cooldown=60)
    for _ in range(3):
        assert lim.wait_seconds() == 0
        lim.record(False)
    assert lim.wait_seconds() > 50


def test_no_open_in_browser_when_uploads_are_off(root, make_window):
    w = make_window(allow_uploads=False)
    w.show_qr()
    tick(w)
    assert w.home.link_entry.get() == w.qr_url
    assert not w.home.open_btn.winfo_manager()         # camera only: the PC has no phone camera


def test_override_button_student_and_parent(root, make_window):
    w = make_window()
    w.home.refresh()
    assert w.home.override_btn not in w.home._shown_buttons   # student mode: hidden
    with mock.patch("homework_lock.app.ask_text") as ask:
        for _ in range(SECRET_TAPS - 1):
            w.home._secret_tap()
        assert w.ctl.is_locked()
        w.home._secret_tap()
    ask.assert_not_called()
    assert not w.ctl.is_locked()

    w = make_window(mode="parent")
    w.config.set_pin("2468")
    w.ctl.lock()
    w.home.refresh()
    assert w.home.override_btn in w.home._shown_buttons
    with mock.patch("homework_lock.app.ask_text", return_value=None):  # cancelled: stays locked
        w.override_unlock()
    assert w.ctl.is_locked()
    with mock.patch("homework_lock.app.ask_text", return_value="2468"):
        w.override_unlock()
    assert not w.ctl.is_locked()


def test_upload_from_pc(root, make_window, tmp_path):
    w = make_window()
    w.home.refresh()
    assert w.home.pc_btn in w.home._shown_buttons
    files = [tmp_path / "page2.jpg", tmp_path / "page1.jpg"]
    for f in files:
        f.write_bytes(f.name.encode())
    with mock.patch("homework_lock.app.filedialog.askopenfilenames", return_value=[str(f) for f in files]), \
         mock.patch("homework_lock.app.messagebox.askyesno", return_value=True):
        w.upload_from_pc()
    for _ in range(50):
        if not w.checking:
            break
        time.sleep(0.05)
    assert w.cloud.checked == [[b"page1.jpg", b"page2.jpg"]]  # file-name order, one photo per page
    assert not w.ctl.is_locked() and w.last_result["page_count"] == 2


def test_pc_photo_limits(tmp_path):
    from homework_lock.app import pc_photo_problem
    new, old = tmp_path / "new.jpg", tmp_path / "old.jpg"
    new.write_bytes(b"x")
    old.write_bytes(b"x")
    os.utime(old, (time.time() - 2 * 86400,) * 2)
    assert pc_photo_problem([str(new)]) is None
    assert "more than a day old" in pc_photo_problem([str(new), str(old)])
    assert "Pick 1 to" in pc_photo_problem([])


def test_pc_upload_hidden_when_uploads_off(root, make_window):
    w = make_window(allow_uploads=False)
    w.home.refresh()
    assert w.home.pc_btn not in w.home._shown_buttons
