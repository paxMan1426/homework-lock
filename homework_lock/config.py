"""Config storage (config.json) and secret hashing helpers."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
from pathlib import Path

from .paths import DATA_DIR

DEFAULT_PATH = Path(os.environ.get("HOMEWORK_LOCK_CONFIG", DATA_DIR / "config.json"))

DEFAULTS = {
    "mode": "self",               # "self" or "parent"
    "blocked_apps": [],           # lowercase process names, e.g. "steam.exe"
    "app_labels": {},             # process name -> friendly name shown in settings
    "unlock_minutes": 30,
    "pin_hash": None,             # "salt_hex$hash_hex"
    "totp_secret": None,
    "totp_last_counter": None,    # last accepted TOTP time-step, blocks reuse
    "backup_code_hashes": [],
    "used_image_hashes": [],
    "unlocked_until": 0.0,        # unix time; 0 = locked
    "unlock_length": 0.0,         # seconds the current unlock lasts (for the progress bar)
    "appearance": "system",       # "system", "light" or "dark"
    "schedule_enabled": False,    # False: always locked. True: free until lock_start on lock_days
    "lock_start": "15:00",        # 24-hour "HH:MM"
    "lock_days": [0, 1, 2, 3, 4], # Monday = 0
    "allow_uploads": True,        # phone may pick existing photos, not only take new ones
    "autostart": True,            # scheduled task that starts the app whenever apps should be locked
    "setup_done": False,          # first-run setup finished
    "install_id": None,           # random ID the online service uses for daily limits (no personal info)
}

# Never allow these to be blocked: killing them would break Windows or this app.
PROTECTED = {
    "system", "system idle process", "registry", "smss.exe", "csrss.exe", "wininit.exe",
    "winlogon.exe", "services.exe", "lsass.exe", "svchost.exe", "explorer.exe", "dwm.exe",
    "python.exe", "pythonw.exe", "py.exe", "pyw.exe", "taskmgr.exe", "conhost.exe",
    "fontdrvhost.exe", "sihost.exe", "ctfmon.exe", "runtimebroker.exe", "searchhost.exe",
    "startmenuexperiencehost.exe", "shellexperiencehost.exe", "homeworklock.exe",
}

PBKDF2_ROUNDS = 200_000


def hash_secret(secret: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode(), salt, PBKDF2_ROUNDS)
    return f"{salt.hex()}${digest.hex()}"


def verify_secret(secret: str, stored: str | None) -> bool:
    if not stored or "$" not in stored:
        return False
    salt_hex, digest_hex = stored.split("$", 1)
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode(), bytes.fromhex(salt_hex), PBKDF2_ROUNDS)
    return hmac.compare_digest(digest.hex(), digest_hex)


def normalize_app(name: str) -> str:
    name = name.strip().lower()
    if name and not name.endswith(".exe"):
        name += ".exe"
    return name


class Config:
    """Thread-safe wrapper around config.json."""

    def __init__(self, path: Path | str = DEFAULT_PATH):
        self.path = Path(path)
        self._lock = threading.RLock()
        self.data = dict(DEFAULTS)
        if self.path.exists():
            try:
                saved = json.loads(self.path.read_text(encoding="utf-8"))
                saved.setdefault("setup_done", True)  # set up before first-run setup existed
                self.data.update(saved)
            except (json.JSONDecodeError, OSError):
                pass  # corrupt file: fall back to defaults

    def get(self, key):
        with self._lock:
            return self.data.get(key, DEFAULTS.get(key))

    def set(self, **values):
        with self._lock:
            self.data.update(values)
            self.save()

    def save(self):
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)

    # --- blocked apps ---
    def blocked_apps(self) -> set[str]:
        return set(self.get("blocked_apps"))

    def add_app(self, name: str, label: str | None = None) -> bool:
        name = normalize_app(name)
        if not name or name in PROTECTED:
            return False
        with self._lock:
            apps = self.blocked_apps()
            apps.add(name)
            labels = dict(self.get("app_labels"))
            if label:
                labels[name] = label
            self.set(blocked_apps=sorted(apps), app_labels=labels)
        return True

    def remove_app(self, name: str):
        name = normalize_app(name)
        with self._lock:
            apps = self.blocked_apps()
            apps.discard(name)
            labels = dict(self.get("app_labels"))
            labels.pop(name, None)
            self.set(blocked_apps=sorted(apps), app_labels=labels)

    def app_label(self, name: str) -> str:
        return self.get("app_labels").get(name) or name

    # --- PIN ---
    def set_pin(self, pin: str):
        self.set(pin_hash=hash_secret(pin))

    def check_pin(self, pin: str) -> bool:
        return verify_secret(pin, self.get("pin_hash"))

    def has_pin(self) -> bool:
        return bool(self.get("pin_hash"))

    def install_id(self) -> str:
        with self._lock:
            if not self.get("install_id"):
                self.set(install_id=secrets.token_urlsafe(18))
            return self.get("install_id")

    # --- used photo hashes ---
    def image_used(self, h: str) -> bool:
        return h in self.get("used_image_hashes")

    def mark_image_used(self, h: str):
        with self._lock:
            hashes = list(self.get("used_image_hashes"))
            if h not in hashes:
                hashes.append(h)
            self.set(used_image_hashes=hashes)
