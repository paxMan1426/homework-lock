import time
from unittest import mock

import pyotp

from homework_lock import override
from homework_lock.app import MainWindow
from homework_lock.config import Config


def _code(cfg, offset_steps=0):
    return pyotp.TOTP(cfg.get("totp_secret")).at(time.time() + offset_steps * 30)


def test_setup_stores_only_hashes(tmp_path):
    cfg = Config(tmp_path / "c.json")
    uri, codes = override.setup(cfg)
    assert uri.startswith("otpauth://totp/") and "Homework%20Lock" in uri
    assert len(codes) == 5 and len(set(codes)) == 5
    text = (tmp_path / "c.json").read_text()
    for c in codes:
        assert c not in text and c.replace("-", "") not in text
    assert len(cfg.get("backup_code_hashes")) == 5


def test_totp_valid_once(tmp_path):
    cfg = Config(tmp_path / "c.json")
    override.setup(cfg)
    code = _code(cfg)
    assert override.verify_totp(cfg, code)
    assert not override.verify_totp(cfg, code)               # reuse rejected
    assert not override.verify_totp(cfg, _code(cfg, -1))     # older code rejected after newer used
    assert not override.verify_totp(Config(tmp_path / "c.json"), code)  # survives restart
    assert not override.verify_totp(cfg, "abc")


def test_totp_drift_window(tmp_path):
    cfg = Config(tmp_path / "c.json")
    override.setup(cfg)
    assert override.verify_totp(cfg, _code(cfg, -1))         # 30 s old still accepted
    assert not override.verify_totp(cfg, _code(cfg, -3))     # 90 s old is not


def test_backup_codes_single_use(tmp_path):
    cfg = Config(tmp_path / "c.json")
    _, codes = override.setup(cfg)
    assert override.verify(cfg, codes[0].upper())            # case / dash insensitive
    assert not override.verify(cfg, codes[0])
    assert override.verify(cfg, codes[1].replace("-", " "))
    assert len(cfg.get("backup_code_hashes")) == 3
    assert not override.verify(cfg, "zzzzz-zzzzz")


def test_resetup_invalidates_old_codes(tmp_path):
    cfg = Config(tmp_path / "c.json")
    _, old = override.setup(cfg)
    override.setup(cfg)
    assert not override.verify(cfg, old[0])


def test_window_override_flow(root, tmp_path):
    cfg = Config(tmp_path / "c.json")
    cfg.set_pin("1357")
    cfg.set(mode="parent", unlock_minutes=20)
    w = MainWindow(root, cfg, cloud_api=mock.Mock())
    try:
        assert w.home.code_btn not in w.home._shown_buttons
        with mock.patch("homework_lock.app.TotpDialog.show", return_value=True):
            w.setup_totp()
        assert override.is_set_up(cfg)
        assert w.home.code_btn in w.home._shown_buttons
        shown = w.totp_win.box.get("1.0", "end").split()
        assert len(shown) == 5 and shown == w.totp_win.codes
        w.totp_win.copy()
        assert root.clipboard_get().split() == shown
        w.totp_win.destroy()

        with mock.patch("homework_lock.app.ask_text", return_value=_code(cfg)):
            w.enter_parent_code()
        assert 19 * 60 < w.ctl.remaining() <= 20 * 60
        w.ctl.lock()
        with mock.patch("homework_lock.app.ask_text", return_value=_code(cfg)), \
             mock.patch("homework_lock.app.messagebox.showerror") as err:
            w.enter_parent_code()                            # same code again
            err.assert_called_once()
        assert w.ctl.is_locked()
        with mock.patch("homework_lock.app.ask_text", return_value=shown[2]):
            w.enter_parent_code()
        assert not w.ctl.is_locked()
    finally:
        root.after_cancel(w._tick_id)


def test_code_attempts_rate_limited(root, tmp_path):
    cfg = Config(tmp_path / "c.json")
    cfg.set_pin("1357")
    cfg.set(mode="parent")
    override.setup(cfg)
    w = MainWindow(root, cfg, cloud_api=mock.Mock())
    try:
        with mock.patch("homework_lock.app.ask_text", return_value="zzzzz-zzzzz") as ask, \
             mock.patch("homework_lock.app.messagebox.showerror"):
            for _ in range(7):
                w.enter_parent_code()
            assert ask.call_count == 5
    finally:
        root.after_cancel(w._tick_id)
