"""First-run setup: who's using it (self or parent mode, with PIN and authenticator), then apps to block."""
from __future__ import annotations

from tkinter import messagebox

import customtkinter as ctk

from .ui_apps import AddAppsView
from .ui_common import MUTED, Card, button, font, label


class SetupPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.mode_step = ctk.CTkFrame(self, fg_color="transparent")
        self.mode_step.grid(row=0, column=0, sticky="nsew")
        label(self.mode_step, "Welcome to Homework Lock", 28, "bold").pack(anchor="w")
        label(self.mode_step, "Step 1 of 2 · Who is setting this up?", 14, color=MUTED).pack(anchor="w", pady=(0, 18))
        for title, text, parent in (
                ("Just me", "I want to lock my own games until my homework is done. I can change settings myself.",
                 False),
                ("I'm a parent", "Settings, quitting and unlocking need a parent PIN. You can also get unlock "
                                 "codes from an authenticator app on your phone.", True)):
            card = Card(self.mode_step)
            card.pack(fill="x", pady=(0, 12))
            label(card, title, 18, "bold").pack(anchor="w", padx=22, pady=(18, 2))
            label(card, text, 14, color=MUTED, wraplength=560).pack(anchor="w", padx=22)
            button(card, "Choose", lambda p=parent: self.choose(p), width=120, font=font(14, "bold")).pack(
                anchor="w", padx=22, pady=(12, 18))

    def choose(self, parent: bool):
        if parent:
            if not self.app.enable_parent_mode():  # asks for a new PIN
                return
            if messagebox.askyesno("Authenticator app", "Set up an authenticator app now? Its codes let you "
                                   "unlock from your phone. You can also do this later in Settings.",
                                   parent=self.app.root):
                self.app.setup_totp()
        else:
            self.app.config.set(mode="self")
        self.mode_step.grid_remove()
        label(self, "Step 2 of 2 · Pick the apps to block. You can change them later under Blocked apps.", 14,
              color=MUTED).grid(row=1, column=0, sticky="w", pady=(10, 0))
        AddAppsView(self, self.app.config, on_close=self.app.finish_setup).grid(row=0, column=0, sticky="nsew")

    def refresh(self):
        pass
