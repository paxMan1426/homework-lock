"""Shared look: colors (light, dark), fonts, cards, buttons and small modal dialogs."""
from __future__ import annotations

import tkinter as tk

import customtkinter as ctk

BG = ("#F4F6FA", "#101216")
SIDEBAR = ("#FFFFFF", "#171A20")
CARD = ("#FFFFFF", "#1B1F26")
BORDER = ("#E4E8EF", "#2A2F38")
TEXT = ("#1B1F27", "#ECEEF2")
MUTED = ("#6B7280", "#98A1B0")
ACCENT = ("#3B6FF5", "#5B8CFF")
ACCENT_HOVER = ("#2E5DD8", "#4A7AEB")
ACCENT_SOFT = ("#EAF0FF", "#222B3D")
SUBTLE = ("#EEF1F6", "#252A33")
SUBTLE_HOVER = ("#E1E6EE", "#2F3541")
RED = ("#D43F3F", "#FF6B6B")
RED_SOFT = ("#FDEDED", "#35191C")
GREEN = ("#17955A", "#4CD38A")
GREEN_SOFT = ("#E5F6EE", "#14301F")
FAMILY = "Segoe UI"


def font(size=14, weight="normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=FAMILY, size=size, weight=weight)


def label(master, text="", size=14, weight="normal", color=TEXT, **kw) -> ctk.CTkLabel:
    kw.setdefault("anchor", "w")
    kw.setdefault("justify", "left")
    return ctk.CTkLabel(master, text=text, font=font(size, weight), text_color=color, **kw)


BUTTON_STYLES = {
    "primary": dict(fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color="#FFFFFF"),
    "secondary": dict(fg_color=SUBTLE, hover_color=SUBTLE_HOVER, text_color=TEXT),
    "ghost": dict(fg_color="transparent", hover_color=SUBTLE, text_color=TEXT),
    "danger": dict(fg_color="transparent", hover_color=RED_SOFT, text_color=RED),
}


def button(master, text, command=None, kind="primary", icon_name=None, **kw) -> ctk.CTkButton:
    opts = dict(height=40, corner_radius=10, font=font(14, "bold" if kind == "primary" else "normal"))
    opts.update(BUTTON_STYLES[kind])
    opts.update(kw)
    if icon_name:
        from .icons import icon
        opts.update(image=icon(icon_name, 16, opts["text_color"]), compound="left")
    return ctk.CTkButton(master, text=text, command=command, **opts)


# Stock widgets restyled to match the accent color.
SEGMENTED = dict(selected_color=ACCENT, selected_hover_color=ACCENT_HOVER, unselected_color=SUBTLE,
                 unselected_hover_color=SUBTLE_HOVER, fg_color=SUBTLE, text_color=(TEXT[0], TEXT[1]),
                 corner_radius=10, height=36)
SLIDER = dict(button_color=ACCENT, button_hover_color=ACCENT_HOVER, progress_color=ACCENT, fg_color=SUBTLE_HOVER)
CHECKBOX = dict(fg_color=ACCENT, hover_color=ACCENT_HOVER, border_color=MUTED, corner_radius=6, border_width=2,
                text_color=TEXT)
SWITCH = dict(progress_color=ACCENT, button_color="#FFFFFF", button_hover_color="#F0F0F0", fg_color=SUBTLE_HOVER,
              text_color=TEXT, switch_width=44, switch_height=22)
OPTION = dict(fg_color=SUBTLE, button_color=SUBTLE, button_hover_color=SUBTLE_HOVER, text_color=TEXT,
              dropdown_fg_color=CARD, dropdown_hover_color=SUBTLE, dropdown_text_color=TEXT, corner_radius=8,
              height=34)
SCROLL = dict(scrollbar_button_color=BORDER, scrollbar_button_hover_color=MUTED)
ENTRY = dict(fg_color=CARD, border_color=BORDER, text_color=TEXT, corner_radius=10, border_width=1)


class Card(ctk.CTkFrame):
    def __init__(self, master, **kw):
        kw.setdefault("fg_color", CARD)
        kw.setdefault("corner_radius", 14)
        kw.setdefault("border_width", 1)
        kw.setdefault("border_color", BORDER)
        super().__init__(master, **kw)


class Dialog(ctk.CTkToplevel):
    """Small modal window centered on the main window. show() blocks and returns self.result."""

    def __init__(self, master, title: str):
        super().__init__(master)
        self.title(title)
        self.resizable(False, False)
        self.configure(fg_color=BG)
        self.transient(master.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.bind("<Escape>", lambda e: self.cancel())
        self.result = None
        try:
            from .icons import app_icon_path
            self.iconbitmap(app_icon_path())
        except tk.TclError:
            pass
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(padx=28, pady=24, fill="both", expand=True)

    def show(self):
        self.update_idletasks()
        top = self.master.winfo_toplevel()
        x = top.winfo_rootx() + max(0, (top.winfo_width() - self.winfo_reqwidth()) // 2)
        y = top.winfo_rooty() + max(0, (top.winfo_height() - self.winfo_reqheight()) // 3)
        self.geometry(f"+{x}+{y}")
        self.lift()
        self.after(60, self._grab)
        self.wait_window()
        return self.result

    def _grab(self):
        try:
            self.grab_set()
            self.focus_force()
        except tk.TclError:
            pass

    def cancel(self):
        self.result = None
        self.destroy()


class PromptDialog(Dialog):
    def __init__(self, master, title, message, secret=False, placeholder=""):
        super().__init__(master, title)
        label(self.body, title, 18, "bold").pack(anchor="w")
        label(self.body, message, 14, color=MUTED, wraplength=320).pack(anchor="w", pady=(4, 14))
        self.entry = ctk.CTkEntry(self.body, width=320, height=42, font=font(16), **ENTRY,
                                  placeholder_text=placeholder or None, show="•" if secret else "")
        self.entry.pack(fill="x")
        self.entry.bind("<Return>", lambda e: self.ok())
        row = ctk.CTkFrame(self.body, fg_color="transparent")
        row.pack(fill="x", pady=(18, 0))
        button(row, "OK", self.ok, width=110).pack(side="right")
        button(row, "Cancel", self.cancel, kind="ghost", width=90).pack(side="right", padx=8)
        self.after(120, self.entry.focus_set)

    def ok(self):
        self.result = self.entry.get()
        self.destroy()


def ask_text(master, title, message, secret=False, placeholder="") -> str | None:
    return PromptDialog(master, title, message, secret, placeholder).show()


def _work_area() -> tuple[int, int, int, int]:
    """Screen area not covered by the taskbar, in physical pixels."""
    try:
        import ctypes
        from ctypes import wintypes
        r = wintypes.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)  # SPI_GETWORKAREA
        return r.left, r.top, r.right, r.bottom
    except (OSError, AttributeError):
        return 0, 0, 1280, 720


class Toast(ctk.CTkToplevel):
    """Small notice in the bottom-right corner that disappears on its own. Click it to act."""

    def __init__(self, master, title: str, message: str, on_click=None, ms: int = 6000):
        super().__init__(master)
        self.withdraw()
        self.title("Homework Lock notice")
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(fg_color=BORDER)
        self.on_click = on_click
        from .icons import icon
        card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=0)
        card.pack(fill="both", expand=True, padx=1, pady=1)
        ctk.CTkLabel(card, text="", image=icon("lock", 18, "#FFFFFF"), width=40, height=40, corner_radius=12,
                     fg_color=ACCENT).grid(row=0, column=0, rowspan=2, padx=(16, 12), pady=16, sticky="n")
        self.title_label = label(card, title, 15, "bold")
        self.title_label.grid(row=0, column=1, sticky="sw", padx=(0, 18), pady=(14, 0))
        self.message_label = label(card, message, 13, color=MUTED, wraplength=280)
        self.message_label.grid(row=1, column=1, sticky="nw", padx=(0, 18), pady=(0, 14))
        for w in (self, card, self.title_label, self.message_label):
            w.bind("<Button-1>", self._clicked)
        self.update_idletasks()
        left, top, right, bottom = _work_area()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        tk.Toplevel.geometry(self, f"+{right - w - 16}+{bottom - h - 16}")
        self.deiconify()
        self._round_corners()
        self.after(ms, self.close)

    def _round_corners(self):
        try:  # Windows 11 rounded corners for a borderless window
            import ctypes
            hwnd = int(self.wm_frame(), 16)
            pref = ctypes.c_int(2)  # DWMWCP_ROUND
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(pref), ctypes.sizeof(pref))
        except (OSError, ValueError, AttributeError, tk.TclError):
            pass

    def _clicked(self, _event=None):
        if self.on_click:
            self.on_click()
        self.close()

    def close(self):
        if self.winfo_exists():
            self.destroy()
