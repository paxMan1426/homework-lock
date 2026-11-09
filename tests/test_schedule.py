import time
from datetime import datetime
from unittest import mock

import pytest

from homework_lock import schedule, startup
from homework_lock.app import MainWindow
from homework_lock.blocker import Blocker
from homework_lock.config import Config

# 2026-10-26 is a Monday, 2026-10-31 a Saturday
MON_2PM = datetime(2026, 10, 26, 14, 0)
MON_4PM = datetime(2026, 10, 26, 16, 0)
SAT_4PM = datetime(2026, 10, 31, 16, 0)


def _cfg(tmp_path, **kw):
    c = Config(tmp_path / "c.json")
    c.set(**kw)
    return c


def test_no_schedule_always_locked(tmp_path):
    c = _cfg(tmp_path)
    assert schedule.state(c, MON_2PM) == schedule.LOCKED
    assert schedule.state(c, SAT_4PM) == schedule.LOCKED


def test_schedule_free_before_start_locked_after(tmp_path):
    c = _cfg(tmp_path, schedule_enabled=True, lock_start="15:00", lock_days=[0, 1, 2, 3, 4])
    assert schedule.state(c, MON_2PM) == schedule.FREE
    assert schedule.state(c, datetime(2026, 10, 26, 15, 0)) == schedule.LOCKED   # exactly at start
    assert schedule.state(c, MON_4PM) == schedule.LOCKED
    assert schedule.state(c, datetime(2026, 10, 26, 23, 59)) == schedule.LOCKED  # stays locked all evening
    assert schedule.state(c, SAT_4PM) == schedule.FREE                           # not a lock day


def test_approved_photo_unlocks_inside_window(tmp_path):
    c = _cfg(tmp_path, schedule_enabled=True, lock_start="15:00", lock_days=[0])
    c.set(unlocked_until=MON_4PM.timestamp() + 600)
    assert schedule.state(c, MON_4PM) == schedule.UNLOCKED
    assert schedule.state(c, datetime(2026, 10, 26, 16, 11)) == schedule.LOCKED  # timer ran out


def test_unlock_with_schedule_lasts_until_midnight(tmp_path):
    c = _cfg(tmp_path, schedule_enabled=True, lock_start="15:00", lock_days=[0])
    assert schedule.unlock_end(c, 30, MON_4PM) == datetime(2026, 10, 27, 0, 0)  # unlock time ignored
    c.set(unlocked_until=schedule.unlock_end(c, 30, MON_4PM).timestamp())
    assert schedule.state(c, datetime(2026, 10, 26, 23, 59)) == schedule.UNLOCKED
    c.set(schedule_enabled=False)
    assert schedule.unlock_end(c, 30, MON_4PM) == datetime(2026, 10, 26, 16, 30)


def test_unlock_time_setting_disabled_with_schedule(window, test_run_value):
    w = window(schedule_enabled=True)
    w.ctl.unlock()
    w.navigate("settings")
    s = w.pages["settings"]
    assert s.slider.cget("state") == "disabled" and s.minutes_label.cget("text") == "Rest of day"
    assert w.home.fact_values["time"].cget("text") == "Rest of day"
    s.sched_switch.deselect()
    s.on_schedule_toggle()
    assert s.slider.cget("state") == "normal" and s.minutes_label.cget("text") == "30 min"
    assert w.home.fact_values["time"].cget("text") == "30 min"


def test_restart_does_not_unlock(tmp_path):
    c = _cfg(tmp_path, schedule_enabled=True, lock_start="15:00", lock_days=[0])
    assert schedule.is_locked(Config(tmp_path / "c.json"), MON_4PM)  # fresh load, same answer


def test_next_lock_start_and_text(tmp_path):
    c = _cfg(tmp_path, schedule_enabled=True, lock_start="15:30", lock_days=[0, 1, 2, 3, 4])
    assert schedule.next_lock_start(c, MON_2PM) == datetime(2026, 10, 26, 15, 30)
    assert schedule.next_lock_start(c, SAT_4PM) == datetime(2026, 11, 2, 15, 30)
    assert schedule.fmt_time(schedule.parse_hhmm("15:30")) == "3:30 PM"
    assert schedule.fmt_time(schedule.parse_hhmm("00:15")) == "12:15 AM"
    assert schedule.fmt_days([0, 1, 2, 3, 4]) == "Mon–Fri"
    assert "3:30 PM" in schedule.describe(c)


def test_blocker_follows_schedule(tmp_path):
    c = _cfg(tmp_path, schedule_enabled=True, lock_start="15:00", lock_days=[0])
    b = Blocker(c)
    with mock.patch("homework_lock.schedule.datetime") as dt:
        dt.now.return_value = MON_2PM
        dt.combine = datetime.combine
        assert not b.is_locked()
        dt.now.return_value = MON_4PM
        assert b.is_locked()


@pytest.fixture
def test_run_value(monkeypatch):
    monkeypatch.setattr(startup, "VALUE", "HomeworkLockTest")
    yield
    startup.disable()


def test_start_automatically(test_run_value):
    assert not startup.is_enabled()
    xml = startup.task_xml()
    assert "<LogonTrigger>" in xml and "<Interval>PT1M</Interval>" in xml  # at sign-in and every minute
    assert "<DisallowStartIfOnBatteries>false" in xml and "<StopIfGoingOnBatteries>false" in xml
    assert "pythonw.exe" in xml and "-m homework_lock.autostart" in xml
    startup.enable()
    assert startup.is_enabled()
    startup.disable()
    assert not startup.is_enabled()


def test_autostart_starts_app_only_when_needed(tmp_path):
    from homework_lock import autostart
    c = _cfg(tmp_path, schedule_enabled=True, lock_start="15:00", lock_days=[0])
    with mock.patch("homework_lock.schedule.datetime") as dt, \
         mock.patch.object(autostart, "Config", return_value=c), \
         mock.patch.object(autostart, "launch") as launch, \
         mock.patch.object(autostart, "app_running", return_value=False) as running:
        dt.now.return_value = MON_2PM            # free time: nothing to block
        autostart.main()
        launch.assert_not_called()
        dt.now.return_value = MON_4PM            # lock started and the app isn't running
        autostart.main()
        launch.assert_called_once()
        running.return_value = True              # already running: leave it alone
        autostart.main()
        launch.assert_called_once()
        running.return_value = False
        c.set(unlocked_until=MON_4PM.timestamp() + 600)  # homework approved
        autostart.main()
        launch.assert_called_once()


@pytest.fixture
def window(root, tmp_path):
    made = []

    def make(**cfg):
        config = Config(tmp_path / "c.json")
        config.set(**cfg)
        w = MainWindow(root, config, cloud_api=mock.Mock())
        made.append(w)
        return w
    yield make
    for w in made:
        root.after_cancel(w._tick_id)


def _at(moment):
    p = mock.patch("homework_lock.schedule.datetime")
    dt = p.start()
    dt.now.return_value = moment
    dt.combine = datetime.combine
    return p


def test_home_shows_free_time_then_homework_notice(window):
    p = _at(MON_2PM)
    try:
        w = window(schedule_enabled=True, lock_start="15:00", lock_days=[0, 1, 2, 3, 4])
        w.root.after_cancel(w._tick_id)
        w.tick()
        assert w.home.big.cget("text") == "Free until 3:00 PM"
        assert "FREE" in w.home.pill.cget("text") and w.home._shown_buttons == []
        assert "Free time" in w.side_status.cget("text")
        p.stop()
        p = _at(MON_4PM)                     # school's out
        w.root.after_cancel(w._tick_id)
        w.tick()
        assert w.home.big.cget("text") == "Apps are blocked"
        assert w.toast is not None and w.toast.title_label.cget("text") == "Homework time"
    finally:
        p.stop()


def test_no_timer_when_schedule_on(window):
    p = _at(MON_4PM)
    try:
        w = window(schedule_enabled=True, lock_start="15:00", lock_days=[0])
        w.ctl.unlock()
        w.root.after_cancel(w._tick_id)
        w.tick()
        assert w.home.big.cget("text") == "Apps are unlocked"
        assert "rest of the day" in w.home.detail.cget("text")
        assert not w.home.progress.winfo_manager()
        assert w.side_status.cget("text") == "●  Unlocked"
    finally:
        p.stop()


def test_schedule_frozen_while_locked_in_student_mode(window):
    w = window(schedule_enabled=True, lock_start="15:00", lock_days=[0, 1, 2, 3, 4, 5, 6])
    p = _at(datetime(2026, 10, 26, 16, 0))
    try:
        w.navigate("settings")
        s = w.pages["settings"]
        assert s.sched_switch.cget("state") == "disabled" and s.hour_menu.cget("state") == "disabled"
        assert "can't be changed while apps are locked" in s.sched_desc.cget("text")
        s.sched_switch.deselect()
        s.on_schedule_toggle()
        s.on_day(0)
        s.hour_menu.set("11")
        s.on_time()
        assert w.config.get("schedule_enabled") and w.config.get("lock_days") == [0, 1, 2, 3, 4, 5, 6]
        assert w.config.get("lock_start") == "15:00"
    finally:
        p.stop()


def test_settings_schedule_controls(window, test_run_value):
    w = window()
    w.ctl.unlock(10)
    w.navigate("settings")
    s = w.pages["settings"]
    assert not s.sched_controls.winfo_manager()          # hidden while off
    s.sched_switch.select()
    s.on_schedule_toggle()
    assert w.config.get("schedule_enabled") and s.sched_controls.winfo_manager() == "grid"
    s.hour_menu.set("2")
    s.min_menu.set("45")
    s.ampm.set("PM")
    s.on_time()
    assert w.config.get("lock_start") == "14:45"
    s.on_day(4)                                           # untick Friday
    s.on_day(6)                                           # tick Sunday
    assert w.config.get("lock_days") == [0, 1, 2, 3, 6]
    assert "2:45 PM" in s.sched_desc.cget("text")
    assert s.uploads_switch.get() == 1                    # on by default
    s.uploads_switch.deselect()
    s.on_uploads()
    assert w.config.get("allow_uploads") is False
    s.startup_switch.select()
    s.on_startup()
    assert startup.is_enabled()
    s.startup_switch.deselect()
    s.on_startup()
    assert not startup.is_enabled()
