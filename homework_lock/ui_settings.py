"""Settings page: unlock time, mode, PIN, authenticator, appearance. Changes apply right away."""
from __future__ import annotations

import customtkinter as ctk

from tkinter import messagebox

from . import schedule, startup
from .icons import icon
from .ui_common import (ACCENT, ACCENT_HOVER, ACCENT_SOFT, MUTED, OPTION, SCROLL, SEGMENTED, SLIDER, SUBTLE,
                        SUBTLE_HOVER, SWITCH, TEXT, Card, button, font, label)

MODE_TEXT = {
    "Student": "For students managing themselves. No PIN; quitting asks you to confirm first.",
    "Parent": "A PIN is needed to change settings, unlock early, or quit.",
}


class SettingsPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        label(self, "Settings", 28, "bold").grid(row=0, column=0, sticky="w")
        label(self, "Changes are saved automatically.", 14, color=MUTED).grid(row=1, column=0, sticky="w",
                                                                              pady=(0, 18))
        body = ctk.CTkScrollableFrame(self, fg_color="transparent", **SCROLL)
        body.grid(row=2, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=1)

        # ---- unlock time ----
        self.time_card, right = self._card(body, 0, "clock", "Unlock time", "")
        self.minutes_label = label(right, "", 18, "bold", color=ACCENT, anchor="e", width=120)
        self.minutes_label.pack(anchor="e")
        self.slider = ctk.CTkSlider(right, from_=5, to=180, number_of_steps=35, width=260, command=self.on_minutes,
                                    **SLIDER)
        self.slider.pack(anchor="e", pady=(6, 0))

        # ---- lock schedule ----
        c, right = self._card(body, 1, "lock", "Lock schedule", "")
        self.sched_desc = c.desc
        self.sched_switch = ctk.CTkSwitch(right, text="Lock after a set time", font=font(13),
                                          command=self.on_schedule_toggle, **SWITCH)
        self.sched_switch.pack(anchor="e")
        self.sched_controls = ctk.CTkFrame(c, fg_color="transparent")
        row = ctk.CTkFrame(self.sched_controls, fg_color="transparent")
        row.pack(anchor="w")
        label(row, "Lock starts at", 14).pack(side="left", padx=(0, 12))
        self.hour_menu = ctk.CTkOptionMenu(row, values=[str(h) for h in range(1, 13)], width=70,
                                           command=self.on_time, **OPTION)
        self.hour_menu.pack(side="left")
        label(row, ":", 16, "bold").pack(side="left", padx=4)
        self.min_menu = ctk.CTkOptionMenu(row, values=["00", "15", "30", "45"], width=70, command=self.on_time,
                                          **OPTION)
        self.min_menu.pack(side="left")
        self.ampm = ctk.CTkSegmentedButton(row, values=["AM", "PM"], command=self.on_time, font=font(13),
                                           width=100, **SEGMENTED)
        self.ampm.pack(side="left", padx=(10, 0))
        days_row = ctk.CTkFrame(self.sched_controls, fg_color="transparent")
        days_row.pack(anchor="w", pady=(12, 0))
        label(days_row, "On these days", 14).pack(side="left", padx=(0, 12))
        self.day_buttons = []
        for d, name in enumerate(schedule.DAY_NAMES):
            b = ctk.CTkButton(days_row, text=name, width=46, height=32, corner_radius=16, font=font(13),
                              command=lambda d=d: self.on_day(d))
            b.pack(side="left", padx=2)
            self.day_buttons.append(b)

        # ---- photo uploads ----
        c, right = self._card(body, 2, "camera", "Photo uploads",
                              "Let the phone pick existing photos from its gallery, not only take new ones. "
                              "Photos more than a day old are refused.")
        self.uploads_switch = ctk.CTkSwitch(right, text="", command=self.on_uploads, **SWITCH)
        self.uploads_switch.pack(anchor="e")

        # ---- mode ----
        c, right = self._card(body, 3, "people", "Mode", "")
        self.mode_desc = c.desc
        self.mode_seg = ctk.CTkSegmentedButton(right, values=["Student", "Parent"], command=self.on_mode,
                                               font=font(14), width=240, **SEGMENTED)
        self.mode_seg.pack(anchor="e")

        # ---- PIN ----
        c, right = self._card(body, 4, "key", "Parent PIN", "")
        self.pin_desc = c.desc
        self.pin_btn = button(right, "", self.on_pin, kind="secondary", width=160)
        self.pin_btn.pack(anchor="e")

        # ---- authenticator ----
        c, right = self._card(body, 5, "phone", "Parent authenticator", "")
        self.totp_desc = c.desc
        self.totp_btn = button(right, "", lambda: app.setup_totp(), kind="secondary", width=160)
        self.totp_btn.pack(anchor="e")

        # ---- start with Windows ----
        self.startup_card, right = self._card(body, 6, "power", "Start automatically", "")
        self.startup_switch = ctk.CTkSwitch(right, text="", command=self.on_startup, **SWITCH)
        self.startup_switch.pack(anchor="e")

        # ---- appearance ----
        c, right = self._card(body, 7, "theme", "Appearance", "Light, dark, or follow Windows.")
        self.theme_seg = ctk.CTkSegmentedButton(right, values=["System", "Light", "Dark"], command=self.on_theme,
                                                font=font(14), width=240, **SEGMENTED)
        self.theme_seg.pack(anchor="e")

    def _card(self, body, row, ico, title, desc):
        c = Card(body)
        c.grid(row=row, column=0, sticky="ew", pady=6, padx=(0, 6))
        c.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(c, text="", image=icon(ico, 18, ACCENT), width=40, height=40, corner_radius=12,
                     fg_color=ACCENT_SOFT).grid(row=0, column=0, rowspan=2, padx=(20, 0), pady=16)
        label(c, title, 16, "bold").grid(row=0, column=1, sticky="sw", padx=16, pady=(18, 0))
        c.desc = label(c, desc, 13, color=MUTED, wraplength=260)
        c.desc.grid(row=1, column=1, sticky="nw", padx=16, pady=(2, 18))
        right = ctk.CTkFrame(c, fg_color="transparent")
        right.grid(row=0, column=2, rowspan=2, sticky="e", padx=22, pady=14)
        return c, right

    def refresh(self):
        cfg = self.app.config
        minutes = int(cfg.get("unlock_minutes"))
        self.slider.set(minutes)
        self.minutes_label.configure(text=f"{minutes} min")
        mode = "Parent" if cfg.get("mode") == "parent" else "Student"
        self.mode_seg.set(mode)
        self.mode_desc.configure(text=MODE_TEXT[mode])
        has_pin = cfg.has_pin()
        self.pin_desc.configure(text="A PIN is set." if has_pin else "No PIN yet. Parent mode needs one.")
        self.pin_btn.configure(text="Change PIN" if has_pin else "Create PIN")
        has_totp = bool(cfg.get("totp_secret"))
        left = len(cfg.get("backup_code_hashes"))
        if has_totp:
            self.totp_desc.configure(text=f"Set up. Use a 6-digit code from your phone to unlock remotely. "
                                          f"{left} backup code{'s' if left != 1 else ''} left.")
        else:
            self.totp_desc.configure(text="Unlock with a code from an authenticator app on your phone, "
                                          "plus 5 one-time backup codes." +
                                          ("" if has_pin else " Create a PIN first."))
        self.totp_btn.configure(text="Replace" if has_totp else "Set up",
                                state="normal" if has_pin else "disabled")
        self.theme_seg.set((cfg.get("appearance") or "system").capitalize())
        self._refresh_schedule()
        self._refresh_startup()
        self.uploads_switch.select() if cfg.get("allow_uploads") else self.uploads_switch.deselect()

    def _frozen(self) -> bool:
        """In student mode, settings that would loosen the lock can't change while apps are locked."""
        return self.app.ctl.is_locked() and not self.app.parent_mode()

    def _refresh_startup(self):
        on = startup.is_enabled()
        self.startup_switch.select() if on else self.startup_switch.deselect()
        self.startup_switch.configure(state="disabled" if self._frozen() and on else "normal")
        self.startup_card.desc.configure(text=(
            "Starts Homework Lock by itself whenever apps should be locked: when you sign in, and within a "
            "minute of the lock starting, even if it was closed." +
            (" Can't be turned off while apps are locked." if self._frozen() and on else "")))

    def on_uploads(self):
        self.app.config.set(allow_uploads=bool(self.uploads_switch.get()))

    def _refresh_schedule(self):
        cfg = self.app.config
        on = bool(cfg.get("schedule_enabled"))
        self.sched_switch.select() if on else self.sched_switch.deselect()
        frozen = self._frozen()
        self.sched_desc.configure(text=schedule.describe(cfg) +
                                  (" The schedule can't be changed while apps are locked." if frozen else ""))
        for w in (self.sched_switch, self.hour_menu, self.min_menu, self.ampm, *self.day_buttons):
            w.configure(state="disabled" if frozen else "normal")
        # With a schedule, approved homework unlocks until midnight, so the unlock time doesn't apply.
        self.slider.configure(state="disabled" if on or frozen else "normal")
        self.minutes_label.configure(text="Rest of day" if on else f"{int(cfg.get('unlock_minutes'))} min")
        self.time_card.desc.configure(text="The lock schedule is on, so approved homework unlocks apps until "
                                           "midnight." if on else
                                      "How long apps stay unlocked after an approved photo.")
        if on:
            self.sched_controls.grid(row=2, column=1, columnspan=2, sticky="w", padx=16, pady=(0, 18))
        else:
            self.sched_controls.grid_remove()
        t = schedule.lock_start(cfg)
        self.hour_menu.set(str(t.hour % 12 or 12))
        self.min_menu.set(f"{t.minute - t.minute % 15:02d}")
        self.ampm.set("AM" if t.hour < 12 else "PM")
        days = cfg.get("lock_days")
        for d, b in enumerate(self.day_buttons):
            sel = d in days
            b.configure(fg_color=ACCENT if sel else SUBTLE, hover_color=ACCENT_HOVER if sel else SUBTLE_HOVER,
                        text_color="#FFFFFF" if sel else TEXT)

    # ---------- schedule / startup ----------
    def on_schedule_toggle(self):
        if self._frozen():
            self._refresh_schedule()
            return
        self.app.config.set(schedule_enabled=bool(self.sched_switch.get()))
        self._refresh_schedule()
        self.app.home.refresh()

    def on_time(self, _value=None):
        if self._frozen():
            self._refresh_schedule()
            return
        hour = int(self.hour_menu.get()) % 12 + (12 if self.ampm.get() == "PM" else 0)
        self.app.config.set(lock_start=f"{hour:02d}:{int(self.min_menu.get()):02d}")
        self._refresh_schedule()
        self.app.home.refresh()

    def on_day(self, d: int):
        if self._frozen():
            self._refresh_schedule()
            return
        days = set(self.app.config.get("lock_days"))
        days.symmetric_difference_update({d})
        self.app.config.set(lock_days=sorted(days))
        self._refresh_schedule()
        self.app.home.refresh()

    def on_startup(self):
        want = bool(self.startup_switch.get())
        if not want and self._frozen():
            self._refresh_startup()
            return
        try:
            startup.enable() if want else startup.disable()
            self.app.config.set(autostart=want)
        except OSError as e:
            messagebox.showerror("Start automatically", f"Couldn't change the startup setting: {e}",
                                 parent=self.winfo_toplevel())
        self._refresh_startup()

    # ---------- handlers ----------
    def on_minutes(self, value):
        if self._frozen() or self.app.config.get("schedule_enabled"):
            return
        minutes = int(round(value))
        self.minutes_label.configure(text=f"{minutes} min")
        if minutes != self.app.config.get("unlock_minutes"):
            self.app.config.set(unlock_minutes=minutes)

    def on_mode(self, value):
        if value == "Parent":
            self.app.enable_parent_mode()
        else:
            self.app.config.set(mode="self")
            self.app.refresh_mode()
        self.refresh()

    def on_pin(self):
        self.app.change_pin()
        self.refresh()

    def on_theme(self, value):
        self.app.config.set(appearance=value.lower())
        ctk.set_appearance_mode(value.lower())
