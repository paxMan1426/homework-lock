"""Blocked apps page, with an inline "Add apps" checklist."""
from __future__ import annotations

import threading
from tkinter import filedialog, messagebox

import customtkinter as ctk

from . import apps as appfinder
from .config import PROTECTED, Config, normalize_app
from .ui_common import (ACCENT, ACCENT_SOFT, BORDER, CARD, CHECKBOX, ENTRY, MUTED, RED, SCROLL, Card, button,
                        font, label)

PICK_SECONDS = 5
CUSTOM_GROUP = "Type a program name"
SUBTITLE = "These apps close automatically while the computer is locked."
LOCKED_SUBTITLE = "Apps can't be removed while they're locked. Finish your homework first."
_installed_cache: list[dict] | None = None


def _group_blocked(config: Config) -> list[tuple[str, list[str]]]:
    groups: dict[str, list[str]] = {}
    for exe in sorted(config.blocked_apps()):
        groups.setdefault(config.app_label(exe), []).append(exe)
    return sorted(groups.items(), key=lambda kv: kv[0].lower())


class AppsPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.add_view: AddAppsView | None = None

        self.list_view = ctk.CTkFrame(self, fg_color="transparent")
        self.list_view.grid(row=0, column=0, sticky="nsew")
        self.list_view.grid_columnconfigure(0, weight=1)
        self.list_view.grid_rowconfigure(2, weight=1)
        label(self.list_view, "Blocked apps", 28, "bold").grid(row=0, column=0, sticky="w")
        self.subtitle = label(self.list_view, SUBTITLE, 14, color=MUTED)
        self.subtitle.grid(row=1, column=0, sticky="nw", pady=(0, 18))
        button(self.list_view, " Add apps", self.show_add, icon_name="add", width=150, height=44).grid(
            row=0, column=1, rowspan=2, sticky="e")
        self.rows = ctk.CTkScrollableFrame(self.list_view, fg_color="transparent", **SCROLL)
        self.rows.grid(row=2, column=0, columnspan=2, sticky="nsew")
        self.rows.grid_columnconfigure(0, weight=1)
        self.row_widgets: list[tuple[str, list[str], ctk.CTkFrame]] = []

    def can_remove(self) -> bool:
        """A student can't unblock apps while they're locked; parents (who passed the PIN to get here) can."""
        return self.app.parent_mode() or not self.app.ctl.is_locked()

    def refresh(self):
        if self.add_view is not None:
            return
        editable = self.can_remove()
        self.subtitle.configure(text=SUBTITLE if editable else LOCKED_SUBTITLE, text_color=MUTED if editable else RED)
        for w in self.rows.winfo_children():
            w.destroy()
        self.row_widgets = []
        groups = _group_blocked(self.app.config)
        if not groups:
            empty = Card(self.rows)
            empty.grid(row=0, column=0, sticky="ew", pady=40, padx=60)
            label(empty, "\U0001F3AE", 40, anchor="center").pack(pady=(28, 0))
            label(empty, "No apps blocked yet", 20, "bold", anchor="center").pack()
            label(empty, "Pick the games and apps that should stay closed until homework is done.", 14,
                  color=MUTED, anchor="center").pack(pady=(4, 16))
            button(empty, " Add apps", self.show_add, icon_name="add", width=160).pack(pady=(0, 28))
            return
        for i, (name, exes) in enumerate(groups):
            row = Card(self.rows)
            row.grid(row=i, column=0, sticky="ew", pady=4, padx=(0, 6))
            row.grid_columnconfigure(1, weight=1)
            initial = next((c for c in name if c.isalnum()), "?").upper()
            avatar = ctk.CTkFrame(row, width=40, height=40, corner_radius=20, fg_color=ACCENT_SOFT)
            avatar.grid(row=0, column=0, rowspan=2, padx=16, pady=12)
            avatar.grid_propagate(False)
            ctk.CTkLabel(avatar, text=initial, text_color=ACCENT, font=font(16, "bold"), width=20,
                         fg_color="transparent").place(relx=0.5, rely=0.5, anchor="center")
            label(row, name, 15, "bold").grid(row=0, column=1, sticky="sew", pady=(12, 0))
            label(row, ", ".join(exes), 12, color=MUTED).grid(row=1, column=1, sticky="new", pady=(0, 12))
            button(row, " Remove", lambda e=exes: self.remove(e), kind="danger", icon_name="delete", width=100, height=34,
                   state="normal" if editable else "disabled").grid(row=0, column=2, rowspan=2, padx=16)
            self.row_widgets.append((name, exes, row))

    def remove(self, exes):
        if not self.can_remove():
            self.refresh()
            return
        for exe in exes:
            self.app.config.remove_app(exe)
        self.refresh()

    def show_add(self):
        self.list_view.grid_remove()
        self.add_view = AddAppsView(self, self.app.config, on_close=self.close_add)
        self.add_view.grid(row=0, column=0, sticky="nsew")

    def close_add(self):
        if self.add_view is not None:
            self.add_view.destroy()
            self.add_view = None
        self.list_view.grid()
        self.refresh()


class AddAppsView(ctk.CTkFrame):
    """Checklist of open, popular and installed apps, with search, window picking and browsing."""

    def __init__(self, master, config: Config, on_close=None, load_installed=True):
        super().__init__(master, fg_color="transparent")
        self.config_store = config
        self.on_close = on_close
        self.checked: dict[tuple, dict] = {}
        self.picked: list[dict] = []
        self.visible: list[dict] = []
        self._rows: dict[tuple, tuple[ctk.CTkFrame, ctk.CTkCheckBox]] = {}
        self._headers: dict[str, ctk.CTkLabel] = {}
        self._search_job = None
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew")
        button(head, " Back", self.close, kind="ghost", icon_name="back", width=80, height=34).pack(side="left")
        title = ctk.CTkFrame(self, fg_color="transparent")
        title.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        label(title, "Add apps to block", 28, "bold").pack(anchor="w")
        label(title, "Tick the apps that should stay closed until homework is done.", 14, color=MUTED).pack(
            anchor="w")

        self.search = ctk.CTkEntry(self, height=42, font=font(14), **ENTRY,
                                   placeholder_text="Search, or type a program name like game.exe")
        self.search.grid(row=2, column=0, sticky="ew", pady=(10, 12))
        self.search.bind("<KeyRelease>", self._on_search)
        self.search.bind("<Return>", lambda e: self.toggle_first_match())

        self.list = ctk.CTkScrollableFrame(self, fg_color=CARD, corner_radius=14, border_width=1,
                                           border_color=BORDER, **SCROLL)
        self.list.grid(row=3, column=0, sticky="nsew")
        self.list.grid_columnconfigure(0, weight=1)
        self.loading = label(self.list, "Finding installed apps...", 13, color=MUTED)
        self.empty = label(self.list, "Nothing found. Try another search.", 14, color=MUTED)

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        self.pick_btn = button(bar, " Click on an app to block it", self.start_window_pick,
                               kind="secondary", icon_name="mouse", width=230)
        self.pick_btn.pack(side="left")
        button(bar, " Browse...", self.browse, kind="secondary", icon_name="folder", width=120).pack(side="left", padx=8)
        self.block_btn = button(bar, "Block 0 apps", self.commit, width=150)
        self.block_btn.pack(side="right")
        button(bar, "Cancel", self.close, kind="ghost", width=90).pack(side="right", padx=8)

        self.open_now = appfinder.open_apps()
        self.popular = appfinder.popular_apps()
        self.installed = _installed_cache
        self.render()
        if self.installed is None and load_installed:
            threading.Thread(target=self._load_installed, daemon=True).start()
            self.after(200, self._poll_installed)

    # ---------- data ----------
    def _load_installed(self):
        global _installed_cache
        _installed_cache = appfinder.installed_apps()

    def _poll_installed(self):
        if not self.winfo_exists():
            return
        if _installed_cache is None:
            self.after(200, self._poll_installed)
        else:
            self.installed = _installed_cache
            self.render()

    def query(self) -> str:
        return self.search.get().strip().lower()

    def entries(self) -> list[dict]:
        blocked = self.config_store.blocked_apps()
        items = appfinder.merge(self.picked, self.open_now, self.popular, self.installed or [], exclude=blocked)
        q = self.query()
        if q:
            items = [e for e in items if q in e["label"].lower() or any(q in x for x in e["exes"])]
            custom = normalize_app(q)
            known = {x for e in items for x in e["exes"]}
            if (custom not in known and custom not in blocked and custom not in PROTECTED
                    and all(c.isalnum() or c in " ._-()" for c in custom)):
                items.append({"label": f'Block "{custom}"', "exes": [custom], "group": CUSTOM_GROUP})
        return items

    @staticmethod
    def key(entry) -> tuple:
        return tuple(entry["exes"])

    # ---------- view ----------
    def _header(self, group: str) -> ctk.CTkLabel:
        if group not in self._headers:
            self._headers[group] = label(self.list, group.upper(), 12, "bold", color=MUTED)
        return self._headers[group]

    def _row(self, e: dict):
        cache_key = (e["group"], self.key(e), e["label"])
        if cache_key not in self._rows:
            row = ctk.CTkFrame(self.list, fg_color="transparent")
            row.grid_columnconfigure(0, weight=1)
            cb = ctk.CTkCheckBox(row, text="  " + e["label"], font=font(14), **CHECKBOX,
                                 command=lambda e=e: self._toggle_entry(e))
            cb.grid(row=0, column=0, sticky="w", padx=14, pady=7)
            extra = f" +{len(e['exes']) - 1}" if len(e["exes"]) > 1 else ""
            label(row, e["exes"][0] + extra, 12, color=MUTED).grid(row=0, column=1, sticky="e", padx=14)
            self._rows[cache_key] = (row, cb)
        row, cb = self._rows[cache_key]
        cb.select() if self.key(e) in self.checked else cb.deselect()
        return row

    def render(self):
        for w in self.list.winfo_children():
            w.grid_forget()
        self.visible = self.entries()
        r, group = 0, None
        for e in self.visible:
            if e["group"] != group:
                group = e["group"]
                self._header(group).grid(row=r, column=0, sticky="w", padx=16, pady=(14 if r else 10, 2))
                r += 1
            self._row(e).grid(row=r, column=0, sticky="ew")
            r += 1
        if self.installed is None and not self.query():
            self.loading.grid(row=r, column=0, sticky="w", padx=16, pady=12)
        elif not self.visible:
            self.empty.grid(row=r, column=0, sticky="w", padx=16, pady=16)
        self._update_count()

    def _update_count(self):
        n = len(self.checked)
        self.block_btn.configure(text=f"Block {n} app{'s' if n != 1 else ''}",
                                 state="normal" if n else "disabled")

    def _on_search(self, event=None):
        if event is not None and event.keysym == "Return":
            return
        if self._search_job:
            self.after_cancel(self._search_job)
        self._search_job = self.after(120, self.render)

    def _toggle_entry(self, e):
        k = self.key(e)
        if k in self.checked:
            del self.checked[k]
        else:
            self.checked[k] = e
        self._update_count()

    def toggle(self, e):
        """Toggle an entry from code (keeps the checkbox in sync)."""
        self._toggle_entry(e)
        self._row(e)

    def toggle_first_match(self):
        if self._search_job:
            self.after_cancel(self._search_job)
            self._search_job = None
            self.render()
        if self.visible:
            self.toggle(self.visible[0])

    def add_picked(self, entry: dict):
        entry = {**entry, "group": "Picked"}
        if self.key(entry) not in {self.key(p) for p in self.picked}:
            self.picked.append(entry)
        self.checked[self.key(entry)] = entry
        self.search.delete(0, "end")
        self.render()

    # ---------- window picking ----------
    def start_window_pick(self):
        self.pick_btn.configure(state="disabled")
        self._pick_countdown(PICK_SECONDS)

    def _pick_countdown(self, n):
        if not self.winfo_exists():
            return
        if n > 0:
            self.pick_btn.configure(text=f"Now click on the app's window... {n}")
            self.after(1000, self._pick_countdown, n - 1)
            return
        entry = appfinder.foreground_app()
        self.pick_btn.configure(text=" Click on an app to block it", state="normal")
        top = self.winfo_toplevel()
        top.lift()
        top.focus_force()
        if entry is None:
            messagebox.showinfo("No app caught",
                                "Click this button, then click on the window of the app you want to block "
                                f"within {PICK_SECONDS} seconds.", parent=top)
        else:
            self.add_picked(entry)

    # ---------- browsing ----------
    def browse(self):
        path = filedialog.askopenfilename(
            parent=self.winfo_toplevel(), title="Choose a program or shortcut",
            filetypes=[("Programs and shortcuts", "*.exe *.lnk"), ("All files", "*.*")])
        if not path:
            return
        entry = appfinder.entry_for_file(path)
        if entry is None:
            messagebox.showwarning("Can't block that", "Pick a program (.exe) or a shortcut to one. "
                                   "System programs can't be blocked.", parent=self.winfo_toplevel())
        else:
            self.add_picked(entry)

    # ---------- save ----------
    def commit(self):
        for e in self.checked.values():
            name = None if e["group"] == CUSTOM_GROUP else e["label"]
            for exe in e["exes"]:
                self.config_store.add_app(exe, name)
        self.close()

    def close(self):
        if self.on_close:
            self.on_close()
