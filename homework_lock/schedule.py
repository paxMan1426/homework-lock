"""When apps are locked.

Without a schedule, apps are always locked unless a homework photo was approved recently.
With a schedule ("lock from 3:00 PM on Mon-Fri"), apps are free before that time and on other days;
from the start time until midnight they're locked unless a photo was approved recently. Because this
is worked out from the clock, restarting the PC or the app doesn't get around it.
"""
from __future__ import annotations

from datetime import datetime, time as dtime, timedelta

from .config import Config

DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
FULL_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

FREE, LOCKED, UNLOCKED = "free", "locked", "unlocked"


def now() -> datetime:
    return datetime.now()


def parse_hhmm(text: str) -> dtime:
    try:
        h, m = (int(x) for x in str(text).split(":"))
        return dtime(h % 24, m % 60)
    except ValueError:
        return dtime(15, 0)


def fmt_time(t: dtime) -> str:
    h12 = t.hour % 12 or 12
    return f"{h12}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"


def fmt_days(days) -> str:
    days = sorted(set(days))
    if days == list(range(7)):
        return "every day"
    if days == list(range(5)):
        return "Mon–Fri"
    if days == [5, 6]:
        return "weekends"
    return ", ".join(DAY_NAMES[d] for d in days) or "no days"


def lock_start(config: Config) -> dtime:
    return parse_hhmm(config.get("lock_start"))


def in_lock_window(config: Config, now: datetime | None = None) -> bool:
    if not config.get("schedule_enabled"):
        return True
    now = now or datetime.now()
    return now.weekday() in config.get("lock_days") and now.time() >= lock_start(config)


def next_lock_start(config: Config, now: datetime | None = None) -> datetime | None:
    """The next time the lock window begins (only meaningful while outside it)."""
    if not config.get("schedule_enabled") or not config.get("lock_days"):
        return None
    now = now or datetime.now()
    start = lock_start(config)
    for i in range(8):
        day = (now + timedelta(days=i)).date()
        candidate = datetime.combine(day, start)
        if day.weekday() in config.get("lock_days") and candidate > now:
            return candidate
    return None


def unlock_end(config: Config, minutes: float, now: datetime | None = None) -> datetime:
    """When an unlock that starts now ends. With a schedule, homework is done for the day, so apps stay
    unlocked until midnight and the unlock time setting doesn't apply."""
    now = now or datetime.now()
    if config.get("schedule_enabled"):
        return datetime.combine(now.date() + timedelta(days=1), dtime(0, 0))
    return now + timedelta(minutes=float(minutes))


def state(config: Config, now: datetime | None = None) -> str:
    now = now or datetime.now()
    if not in_lock_window(config, now):
        return FREE
    if float(config.get("unlocked_until") or 0) > now.timestamp():
        return UNLOCKED
    return LOCKED


def is_locked(config: Config, now: datetime | None = None) -> bool:
    return state(config, now) == LOCKED


def describe(config: Config) -> str:
    if not config.get("schedule_enabled"):
        return "Apps are locked all the time until homework is approved."
    return (f"Apps are free until {fmt_time(lock_start(config))} on {fmt_days(config.get('lock_days'))}, "
            "then locked until homework is approved. Approved homework unlocks apps for the rest of the day.")
