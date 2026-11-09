"""Crisp, theme-aware icons drawn from the Windows icon font (Segoe Fluent Icons / MDL2 Assets)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFont

APP_ICON = Path(__file__).resolve().parent / "assets" / "homework_lock.ico"
APP_COLOR = "#3B6FF5"

FONT_PATHS = [r"C:\Windows\Fonts\SegoeIcons.ttf", r"C:\Windows\Fonts\segmdl2.ttf"]

GLYPHS = {
    "home": "\uE80F", "apps": "\uE71D", "settings": "\uE713", "power": "\uE7E8", "lock": "\uE72E",
    "unlock": "\uE785", "camera": "\uE722", "search": "\uE721", "back": "\uE72B", "add": "\uE710",
    "mouse": "\uE962", "folder": "\uE838", "delete": "\uE74D", "clock": "\uE823", "people": "\uE716",
    "shield": "\uEA18", "check": "\uE73E", "cancel": "\uE711", "refresh": "\uE72C", "key": "\uE8D7",
    "phone": "\uE8EA", "theme": "\uE790", "chevron": "\uE76C", "upload": "\uE898", "feedback": "\uED15",
}


@lru_cache(maxsize=None)
def _font(px: int):
    for path in FONT_PATHS:
        try:
            return ImageFont.truetype(path, px)
        except OSError:
            continue
    return None


@lru_cache(maxsize=None)
def _render(name: str, px: int, color: str) -> Image.Image | None:
    f = _font(px)
    if f is None:
        return None
    img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((px / 2, px / 2), GLYPHS[name], font=f, fill=color, anchor="mm")
    return img


def app_icon_path() -> str:
    """The window/taskbar/shortcut icon: a white lock on a blue rounded square. Created on first use."""
    if not APP_ICON.exists():
        APP_ICON.parent.mkdir(parents=True, exist_ok=True)
        px = 256
        img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((8, 8, px - 8, px - 8), radius=56, fill=APP_COLOR)
        f = _font(150)
        if f is not None:
            d.text((px / 2, px / 2 + 4), GLYPHS["lock"], font=f, fill="#FFFFFF", anchor="mm")
        img.save(APP_ICON, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return str(APP_ICON)


@lru_cache(maxsize=None)
def icon(name: str, size: int = 18, color: str | tuple[str, str] = ("#1B1F27", "#ECEEF2")) -> ctk.CTkImage | None:
    light, dark = (color, color) if isinstance(color, str) else color
    px = size * 2  # draw at 2x so it stays sharp on high-DPI screens
    li, di = _render(name, px, light), _render(name, px, dark)
    if li is None:
        return None
    return ctk.CTkImage(light_image=li, dark_image=di, size=(size, size))
