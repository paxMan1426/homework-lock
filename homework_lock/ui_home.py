"""Home page: lock status, countdown, phone unlock QR, parent actions."""
from __future__ import annotations

import random
import time
import webbrowser
from datetime import datetime

import customtkinter as ctk

from . import schedule
from .icons import icon
from .ui_common import (ACCENT, ACCENT_SOFT, ENTRY, GREEN, GREEN_SOFT, MUTED, RED, RED_SOFT, SUBTLE, Card, button,
                        font, label)

RESULT_SHOW_SECONDS = 15 * 60
SECRET_TAPS, SECRET_WINDOW = 7, 3.0  # student override: this many taps within this many seconds


def fmt_remaining(seconds: float) -> str:
    s = int(seconds + 0.999)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def greeting(now: datetime | None = None) -> str:
    now = now or datetime.now()
    part = "morning" if now.hour < 12 else "afternoon" if now.hour < 18 else "evening"
    return f"Good {part}  ·  {now:%A, %B} {now.day}"


class HomePage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self._shown_buttons = None
        self.qr_deadline = 0.0
        self.qr_shown_at = 0.0
        self.qr_url = ""

        self.title = label(self, "Home", 28, "bold")
        self.title.grid(row=0, column=0, sticky="w")
        self.subtitle = label(self, greeting(), 14, color=MUTED)
        self.subtitle.grid(row=1, column=0, sticky="w", pady=(0, 18))
        self._taps: list[float] = []

        # ---- status card: pill, big status / timer, detail, progress, actions ----
        card = Card(self)
        card.grid(row=2, column=0, sticky="ew")
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=30, pady=26)
        self.pill = ctk.CTkLabel(inner, text="", font=font(12, "bold"), corner_radius=13, height=28, padx=12,
                                 compound="left")
        self.pill.pack(anchor="w")
        self.big = label(inner, "", 44, "bold")
        self.big.pack(anchor="w", pady=(10, 0))
        self.detail = label(inner, "", 15, color=MUTED, wraplength=640)
        self.detail.pack(anchor="w")
        self.progress = ctk.CTkProgressBar(inner, height=10, corner_radius=5, progress_color=GREEN,
                                           fg_color=SUBTLE)
        self.actions = ctk.CTkFrame(inner, fg_color="transparent")
        self.actions.pack(anchor="w", pady=(20, 0))
        self.unlock_btn = button(self.actions, " Unlock with phone", app.show_qr, icon_name="camera",
                                 height=50, width=210, font=font(15, "bold"))
        self.pc_btn = button(self.actions, " Upload from PC", app.upload_from_pc, kind="secondary",
                             icon_name="upload", height=50, width=180)
        self.lock_btn = button(self.actions, "Lock now", app.lock_now, kind="secondary", icon_name="lock",
                               height=50, width=170)
        self.override_btn = button(self.actions, " Override", app.override_unlock, kind="secondary",
                                   icon_name="key", height=50, width=150)
        self.code_btn = button(self.actions, "Use parent code", app.enter_parent_code, kind="secondary",
                               icon_name="phone", height=50, width=180)

        # ---- phone QR card (only while waiting for a photo) ----
        self.qr_card = Card(self)
        self.qr_card.grid_columnconfigure(1, weight=1)
        self.qr_img = ctk.CTkLabel(self.qr_card, text="", fg_color="#FFFFFF", corner_radius=12)
        self.qr_img.grid(row=0, column=0, rowspan=2, padx=(26, 24), pady=24)
        steps = ctk.CTkFrame(self.qr_card, fg_color="transparent")
        steps.grid(row=0, column=1, sticky="nw", pady=(26, 0), padx=(0, 20))
        label(steps, "Scan this or open the link", 20, "bold").pack(anchor="w", pady=(0, 12))
        for n, text in enumerate(["Point your phone's camera at the code, or open the link",
                                  "Hold each page in front of the camera; flip when it says so",
                                  "Tap Done after the last page and wait a few seconds"], 1):
            row = ctk.CTkFrame(steps, fg_color="transparent")
            row.pack(anchor="w", pady=4)
            ctk.CTkLabel(row, text=str(n), width=26, height=26, corner_radius=13, fg_color=ACCENT,
                         text_color="#FFFFFF", font=font(12, "bold")).pack(side="left")
            label(row, text, 14).pack(side="left", padx=10)
        label(steps, "Your phone needs to be on the same Wi-Fi as this computer.", 13, color=MUTED).pack(
            anchor="w", pady=(12, 0))
        bottom = ctk.CTkFrame(self.qr_card, fg_color="transparent")
        bottom.grid(row=1, column=1, sticky="sw", pady=(0, 24))
        link_row = ctk.CTkFrame(bottom, fg_color="transparent")
        link_row.pack(anchor="w", pady=(0, 10))
        self.link_entry = ctk.CTkEntry(link_row, width=320, height=34, font=font(13), **ENTRY)
        self.link_entry.pack(side="left")
        self.copy_btn = button(link_row, "Copy", self.copy_link, kind="secondary", width=80, height=34)
        self.copy_btn.pack(side="left", padx=(8, 0))
        self.open_btn = button(link_row, "Open in browser", self.open_link, kind="secondary", width=140, height=34)
        self.qr_expiry = label(bottom, "", 13, color=MUTED, image=icon("clock", 14, MUTED), compound="left")
        self.qr_expiry.pack(anchor="w", pady=(0, 10))
        btns = ctk.CTkFrame(bottom, fg_color="transparent")
        btns.pack(anchor="w")
        button(btns, "New code", app.show_qr, kind="secondary", icon_name="refresh", width=130).pack(side="left")
        button(btns, "Cancel", self.hide_qr, kind="ghost", width=90).pack(side="left", padx=8)

        # ---- last result banner ----
        self.banner = ctk.CTkFrame(self, corner_radius=12)
        self.banner.grid_columnconfigure(1, weight=1)
        self.banner_icon = ctk.CTkLabel(self.banner, text="", image=icon("check", 15, GREEN), width=15)
        self.banner_icon.grid(row=0, column=0, sticky="nw", padx=(18, 0), pady=13)
        self.banner_text = label(self.banner, "", 14, wraplength=640)
        self.banner_text.grid(row=0, column=1, sticky="w", padx=(18, 4), pady=13)
        self.banner_close = ctk.CTkButton(self.banner, text="", width=30, height=30, corner_radius=8,
                                          fg_color="transparent", command=self.dismiss_result)
        self.banner_close.grid(row=0, column=2, sticky="ne", padx=(0, 8), pady=8)
        self.dismissed_at = None  # "at" of the result the user closed

        # ---- quick facts ----
        self.facts = ctk.CTkFrame(self, fg_color="transparent")
        self.facts.grid(row=5, column=0, sticky="ew", pady=(16, 0))
        self.fact_values = {}
        spots = [self.title, self.subtitle, self.pill, self.big, self.detail]
        for i, (key, title, ico, page) in enumerate([("apps", "Blocked apps", "apps", "apps"),
                                                     ("time", "Unlock time", "clock", "settings"),
                                                     ("mode", "Mode", "people", "settings")]):
            self.facts.grid_columnconfigure(i, weight=1, uniform="facts")
            f = Card(self.facts)
            f.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 12, 0))
            label(f, " " + title, 13, color=MUTED, image=icon(ico, 15, MUTED), compound="left").pack(
                anchor="w", padx=18, pady=(14, 0))
            self.fact_values[key] = label(f, "", 22, "bold")
            self.fact_values[key].pack(anchor="w", padx=18)
            spots.append(self.fact_values[key])
            ctk.CTkButton(f, text="Change", command=lambda p=page: app.navigate(p), fg_color="transparent",
                          hover_color=SUBTLE, text_color=ACCENT, font=font(13), width=10, height=28,
                          image=icon("chevron", 11, ACCENT), compound="right", anchor="w").pack(
                anchor="w", padx=10, pady=(0, 10))
        # Every spot listens, but only the one saved in config counts; it moves after each use.
        self.spots = spots
        for i, w in enumerate(spots):
            w.bind("<Button-1>", lambda e, i=i: self._secret_tap(i))

    def _spot(self) -> int:
        s = self.app.config.get("override_spot")
        return s if isinstance(s, int) and 0 <= s < len(self.spots) else 1

    def _secret_tap(self, spot: int | None = None):
        if self.app.parent_mode() or not self.app.ctl.is_locked():
            return
        if spot is not None and spot != self._spot():
            self._taps = []
            return
        now = time.time()
        self._taps = [t for t in self._taps if now - t < SECRET_WINDOW] + [now]
        if len(self._taps) >= SECRET_TAPS:
            self._taps = []
            self.app.override_unlock()
            if not self.app.ctl.is_locked():
                cur = self._spot()
                self.app.config.set(override_spot=random.choice([i for i in range(len(self.spots)) if i != cur]))

    # ---------- QR ----------
    def show_qr(self, image, deadline: float, url: str = ""):
        self.qr_url = url
        self.link_entry.configure(state="normal")
        self.link_entry.delete(0, "end")
        self.link_entry.insert(0, url)
        self.link_entry.configure(state="readonly")
        self.copy_btn.configure(text="Copy")
        # Opening it here picks files from the PC, so it's offered only when photo uploads are allowed.
        if self.app.config.get("allow_uploads"):
            self.open_btn.pack(side="left", padx=(8, 0))
        else:
            self.open_btn.pack_forget()
        self._qr_image = ctk.CTkImage(light_image=image, dark_image=image, size=(230, 230))
        self.qr_img.configure(image=self._qr_image)
        self.qr_deadline = deadline
        self.qr_shown_at = time.time()
        self.qr_card.grid(row=3, column=0, sticky="ew", pady=(16, 0))
        self.refresh()

    def copy_link(self):
        self.clipboard_clear()
        self.clipboard_append(self.qr_url)
        self.copy_btn.configure(text="Copied ✔")

    def open_link(self):
        webbrowser.open(self.qr_url)

    def dismiss_result(self):
        if self.app.last_result:
            self.dismissed_at = self.app.last_result.get("at")
        self.refresh()

    def hide_qr(self):
        self.qr_card.grid_remove()
        self.qr_deadline = 0.0
        self.refresh()

    @property
    def qr_visible(self) -> bool:
        return self.qr_deadline > 0

    # ---------- refresh (called every tick) ----------
    def refresh(self):
        app = self.app
        state = app.ctl.state()
        locked = state == schedule.LOCKED
        free = state == schedule.FREE
        parent = app.parent_mode()
        n = len(app.config.blocked_apps())
        result_since_qr = app.last_result and app.last_result.get("at", 0) >= self.qr_shown_at
        if self.qr_visible and (not locked or result_since_qr):
            self.qr_card.grid_remove()  # unlocked, or the one-time link was used up
            self.qr_deadline = 0.0
        qr = self.qr_visible

        self.subtitle.configure(text=greeting())
        if locked:
            self.pill.configure(text=" LOCKED", fg_color=RED_SOFT, text_color=RED, image=icon("lock", 13, RED))
            self.big.configure(text="Apps are blocked")
            self.detail.configure(text=(
                f"{n} app{'s' if n != 1 else ''} blocked. Finish your homework, then unlock with a photo."
                if n else "No apps are blocked yet. Add some under Blocked apps."))
            if app.checking:
                self.detail.configure(text="Checking your photos… this takes a few seconds.")
            self.progress.pack_forget()
        elif free:
            nxt = schedule.next_lock_start(app.config)
            self.pill.configure(text=" FREE TIME", fg_color=ACCENT_SOFT, text_color=ACCENT,
                                image=icon("clock", 13, ACCENT))
            if nxt and nxt.date() == schedule.now().date():
                self.big.configure(text=f"Free until {schedule.fmt_time(nxt.time())}")
                when = "then"
            else:
                self.big.configure(text="Free time")
                when = (f"Next lock: {schedule.FULL_DAY_NAMES[nxt.weekday()]} at {schedule.fmt_time(nxt.time())}."
                        if nxt else "No lock days are set.")
            self.detail.configure(text=(f"Apps lock at {schedule.fmt_time(schedule.lock_start(app.config))} on "
                                        f"{schedule.fmt_days(app.config.get('lock_days'))} and stay locked until "
                                        "your homework is approved." if when == "then" else when))
            self.progress.pack_forget()
        else:
            remaining = app.ctl.remaining()
            total = max(remaining, float(app.config.get("unlock_length") or remaining or 1))
            r = app.last_result or {}
            subject = r.get("subject") if r.get("approved") else ""
            self.pill.configure(text=" UNLOCKED", fg_color=GREEN_SOFT, text_color=GREEN,
                                image=icon("unlock", 13, GREEN))
            approved = f"Approved: {subject}. " if subject else ""
            if app.config.get("schedule_enabled"):  # unlocked until midnight, so no countdown
                self.big.configure(text="Apps are unlocked")
                self.detail.configure(text=approved + "Apps stay unlocked for the rest of the day.")
                self.progress.pack_forget()
            else:
                self.big.configure(text=fmt_remaining(remaining))
                self.detail.configure(text=approved + "Apps lock again when the timer ends.")
                self.progress.set(remaining / total)
                if not self.progress.winfo_manager():
                    self.progress.pack(fill="x", pady=(16, 0), after=self.detail)

        if qr or free or app.checking:
            wanted = []
        elif locked:
            wanted = [self.unlock_btn]
            if app.config.get("allow_uploads"):
                wanted.append(self.pc_btn)
            if parent:  # students get the hidden override instead
                wanted.append(self.override_btn)
            if parent and app.config.get("totp_secret"):
                wanted.append(self.code_btn)
        else:
            wanted = [self.lock_btn]
        if wanted != self._shown_buttons:
            for b in (self.unlock_btn, self.pc_btn, self.lock_btn, self.override_btn, self.code_btn):
                b.grid_forget()
            for i, b in enumerate(wanted):  # three to a row
                b.grid(row=i // 3, column=i % 3, sticky="w", padx=(0 if i % 3 == 0 else 10, 0),
                       pady=(0 if i < 3 else 10, 0))
            if wanted:
                self.actions.pack(anchor="w", pady=(20, 0))
            else:
                self.actions.pack_forget()
            self._shown_buttons = wanted

        if qr:
            left = self.qr_deadline - time.time()
            self.qr_expiry.configure(text=f" Code expires in {fmt_remaining(left)}" if left > 0
                                     else " This code expired. Click New code.")

        r = app.last_result
        if (r and not qr and r.get("at") != self.dismissed_at
                and time.time() - r.get("at", 0) < RESULT_SHOW_SECONDS):
            if r.get("approved"):
                self.banner.configure(fg_color=GREEN_SOFT)
                pages = r.get("page_count") or 1
                self.banner_icon.grid()
                self.banner_text.configure(text_color=GREEN,
                                           text=f"All {pages} page{'s' if pages != 1 else ''} approved" +
                                           (f" — {r['subject']}" if r.get("subject") else ""))
                self.banner_text.grid_configure(padx=(8, 4))
                color = GREEN
            else:
                self.banner.configure(fg_color=RED_SOFT)
                issues = [f"Page {p['page']}: {p['issue']}" for p in r.get("pages") or []
                          if not p.get("complete") and p.get("issue")]
                self.banner_icon.grid_remove()
                self.banner_text.configure(text_color=RED,
                                           text=f"Not approved: {r.get('reason', '')}" +
                                           ("\n" + "\n".join(issues[:3]) if issues else ""))
                self.banner_text.grid_configure(padx=(18, 4))
                color = RED
            self.banner_close.configure(image=icon("cancel", 13, color), hover_color=SUBTLE)
            if not self.banner.winfo_manager():
                self.banner.grid(row=4, column=0, sticky="ew", pady=(16, 0))
        elif self.banner.winfo_manager():
            self.banner.grid_remove()

        if qr and self.facts.winfo_manager():
            self.facts.grid_remove()
        elif not qr and not self.facts.winfo_manager():
            self.facts.grid()
        self.fact_values["apps"].configure(text=str(n))
        self.fact_values["time"].configure(text="Rest of day" if app.config.get("schedule_enabled") else
                                           f"{app.config.get('unlock_minutes')} min")
        self.fact_values["mode"].configure(text="Parent" if parent else "Student")
