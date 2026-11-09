"""Talks to the Homework Lock online service (a Cloudflare Worker): scan sessions, photo checks, reports.

The phone scans on the Worker's web page; the Worker asks Claude and keeps only the verdict, which this app
polls for. No API key lives on this computer.
"""
from __future__ import annotations

import io
import json
import secrets
import urllib.error
import urllib.parse
import urllib.request

from PIL import Image, ImageOps

from .config import Config
from .paths import LOG_PATH
from .version import VERSION, WORKER_URL

SESSION_TTL = 5 * 60   # seconds a QR code works (the Worker enforces the same)
MAX_PAGES = 10
MAX_PHOTO_AGE = 24 * 3600
MAX_UPLOAD = 120 * 1024 * 1024  # all picked files together, before shrinking
PAGE_SIDE = 1568
TIMEOUT = 20
CHECK_TIMEOUT = 120  # a full check of many pages can take a while


class CloudError(Exception):
    """A message that can be shown to the user as is."""


def _request(method: str, path: str, body: bytes | None = None, content_type: str = "application/json",
             timeout: float = TIMEOUT) -> dict:
    req = urllib.request.Request(WORKER_URL + path, data=body, method=method,
                                 headers={"Content-Type": content_type, "User-Agent": f"HomeworkLock/{VERSION}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            data = json.loads(e.read())
        except ValueError:
            data = {}
        if e.code == 404 and "status" in data:
            return data
        raise CloudError(data.get("error") or f"The online service had a problem ({e.code}).") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise CloudError("Couldn't reach the online service. Check the internet connection.") from e


def _json(obj) -> bytes:
    return json.dumps(obj).encode()


def _multipart(fields: dict, files: list[tuple[str, str, bytes]]) -> tuple[bytes, str]:
    boundary = secrets.token_hex(16)
    out = io.BytesIO()
    for name, value in fields.items():
        out.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    for name, filename, data in files:
        out.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                  f"Content-Type: image/jpeg\r\n\r\n".encode())
        out.write(data + b"\r\n")
    out.write(f"--{boundary}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={boundary}"


def shrink(data: bytes) -> bytes:
    """A photo as a JPEG no bigger than the checker uses, so uploads are quick."""
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    except Exception as e:
        raise CloudError("One of the files isn't a readable photo.") from e
    img.thumbnail((PAGE_SIDE, PAGE_SIDE))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=85)
    return out.getvalue()


def new_session(config: Config) -> tuple[str, str]:
    """Start a phone scan. Returns (token, url for the QR code)."""
    r = _request("POST", "/api/session", _json({"install": config.install_id(),
                                                  "allow_uploads": bool(config.get("allow_uploads"))}))
    return r["token"], r["url"]


def poll(config: Config, token: str) -> dict:
    """{"status": "open" | "checking" | "done" | "expired", "result"?: verdict}"""
    q = urllib.parse.urlencode({"install": config.install_id()})
    return _request("GET", f"/api/session/{token}?{q}")


def check_photos(config: Config, pages: list[bytes]) -> dict:
    """Check photos picked on this PC. Returns the verdict {"approved", "reason", "subject", "pages"}."""
    files = [("photo", f"page{i}.jpg", shrink(p)) for i, p in enumerate(pages, 1)]
    body, ctype = _multipart({"install": config.install_id()}, files)
    return _request("POST", "/api/check", body, ctype, timeout=CHECK_TIMEOUT)


def last_log_lines(n: int = 50) -> str:
    try:
        return "\n".join(LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()[-n:])
    except OSError:
        return ""


def send_report(config: Config, description: str):
    """A problem report: the description, the app version and the last 50 log lines. No photos."""
    _request("POST", "/api/report", _json({"install": config.install_id(), "version": VERSION,
                                             "description": description, "log": last_log_lines()}))


def qr_image(text: str, box_size: int = 6):
    import qrcode
    qr = qrcode.QRCode(box_size=box_size, border=2)
    qr.add_data(text)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").get_image()
