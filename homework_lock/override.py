"""Parent override: TOTP authenticator codes and one-time backup codes."""
from __future__ import annotations

import hmac
import secrets
import time
from datetime import datetime, timezone

import pyotp

from .config import Config, hash_secret, verify_secret

ISSUER = "Homework Lock"
BACKUP_COUNT = 5
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no look-alike characters


def _normalize_backup(code: str) -> str:
    return code.replace("-", "").replace(" ", "").strip().lower()


def new_backup_code() -> str:
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(10))
    return f"{raw[:5]}-{raw[5:]}"


def setup(config: Config) -> tuple[str, list[str]]:
    """Create a new TOTP secret and backup codes. Returns (provisioning_uri, backup_codes).
    The backup codes are only returned here; only their hashes are stored."""
    secret = pyotp.random_base32()
    codes = [new_backup_code() for _ in range(BACKUP_COUNT)]
    config.set(totp_secret=secret, totp_last_counter=None,
               backup_code_hashes=[hash_secret(_normalize_backup(c)) for c in codes])
    uri = pyotp.TOTP(secret).provisioning_uri(name="Parent", issuer_name=ISSUER)
    return uri, codes


def is_set_up(config: Config) -> bool:
    return bool(config.get("totp_secret"))


def verify_totp(config: Config, code: str, now: float | None = None) -> bool:
    secret = config.get("totp_secret")
    code = code.replace(" ", "").strip()
    if not secret or len(code) != 6 or not code.isdigit():
        return False
    totp = pyotp.TOTP(secret)
    current = totp.timecode(datetime.fromtimestamp(time.time() if now is None else now, tz=timezone.utc))
    last = config.get("totp_last_counter")
    for counter in (current - 1, current, current + 1):  # allow 30 s clock drift
        if hmac.compare_digest(totp.generate_otp(counter), code):
            if last is not None and counter <= last:
                return False  # this code (or an older one) was already used
            config.set(totp_last_counter=counter)
            return True
    return False


def verify_backup(config: Config, code: str) -> bool:
    code = _normalize_backup(code)
    if len(code) != 10:
        return False
    hashes = list(config.get("backup_code_hashes"))
    for h in hashes:
        if verify_secret(code, h):
            hashes.remove(h)
            config.set(backup_code_hashes=hashes)
            return True
    return False


def verify(config: Config, code: str) -> bool:
    """Accept either an authenticator code or an unused backup code."""
    return verify_totp(config, code) or verify_backup(config, code)
