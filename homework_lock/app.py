"""Main window: sidebar navigation, lock state, phone unlock, parent controls, quit."""
from __future__ import annotations

import collections
import ctypes
import logging
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from . import cloud, override, schedule, startup, updater, watchdog
from .shortcuts import APP_ID, set_window_identity
from .blocker import Blocker
from .icons import app_icon_path, icon
from .cloud import MAX_PAGES, MAX_PHOTO_AGE, MAX_UPLOAD, SESSION_TTL, CloudError, qr_image
from .config import Config
from .paths import FROZEN, LOG_PATH
from .ui_apps import AppsPage
from .ui_common import (ACCENT, ACCENT_SOFT, BG, BORDER, GREEN, MUTED, RED, SIDEBAR, SUBTLE, TEXT, Dialog,
                        Toast, ask_text, button, font, label)
from .ui_home import HomePage, fmt_remaining  # noqa: F401 - fmt_remaining re-exported
from .ui_settings import SettingsPage
from .version import VERSION

TITLE = f"Homework Lock Beta v{VERSION}"
ADMIN_SECONDS = 5 * 60  # how long a correct PIN keeps settings open in parent mode
TOAST_REPEAT_SECONDS = 10  # don't repeat the "X is blocked" notice for the same app sooner than this
POLL_SECONDS = 2  # how often the app asks the online service for the phone scan's verdict


class AttemptLimiter:
    """After `limit` failures, refuse further tries for `cooldown` seconds."""

    def __init__(self, limit=5, cooldown=60):
        self.limit, self.cooldown = limit, cooldown
        self.failures, self.blocked_until = 0, 0.0

    def wait_seconds(self) -> int:
        return max(0, int(self.blocked_until - time.time() + 0.999))

    def record(self, ok: bool):
        if ok:
            self.failures = 0
            return
        self.failures += 1
        if self.failures >= self.limit:
            self.failures = 0
            self.blocked_until = time.time() + self.cooldown


class Controller:
    """Lock state. Thread-safe: the upload server calls unlock() from its own thread."""

    def __init__(self, config: Config):
        self.config = config

    def remaining(self) -> float:
        return max(0.0, float(self.config.get("unlocked_until") or 0) - time.time())

    def state(self) -> str:
        """schedule.FREE, schedule.LOCKED or schedule.UNLOCKED."""
        return schedule.state(self.config)

    def is_locked(self) -> bool:
        return self.state() == schedule.LOCKED

    def unlock(self, minutes: float | None = None):
        minutes = minutes if minutes is not None else self.config.get("unlock_minutes")
        start = datetime.now()
        seconds = (schedule.unlock_end(self.config, minutes, start) - start).total_seconds()
        self.config.set(unlocked_until=start.timestamp() + seconds, unlock_length=seconds)

    def lock(self):
        self.config.set(unlocked_until=0.0)


class TotpDialog(Dialog):
    def __init__(self, master, uri: str, secret: str, codes: list[str]):
        super().__init__(master, "Set up parent authenticator")
        self.codes = codes
        label(self.body, "Scan with your authenticator app", 20, "bold").pack(anchor="w")
        label(self.body, "Google Authenticator, Microsoft Authenticator, Authy, 1Password and others work.",
              13, color=MUTED, wraplength=420).pack(anchor="w", pady=(2, 12))
        img = qr_image(uri, box_size=6)
        self._img = ctk.CTkImage(light_image=img, dark_image=img, size=(210, 210))
        ctk.CTkLabel(self.body, image=self._img, text="", fg_color="#FFFFFF", corner_radius=12).pack()
        label(self.body, "Can't scan? Enter this key instead:", 13, color=MUTED).pack(anchor="w", pady=(12, 2))
        key = ctk.CTkEntry(self.body, height=36, font=ctk.CTkFont(family="Consolas", size=14))
        key.insert(0, secret)
        key.configure(state="readonly")
        key.pack(fill="x")
        label(self.body, "Backup codes", 16, "bold").pack(anchor="w", pady=(16, 0))
        label(self.body, "Each code works once. They won't be shown again, so write them down or copy them "
                         "somewhere safe.", 13, color=MUTED, wraplength=420).pack(anchor="w", pady=(2, 8))
        self.box = ctk.CTkTextbox(self.body, height=140, width=420, corner_radius=10,
                                  font=ctk.CTkFont(family="Consolas", size=17))
        self.box.insert("1.0", "\n".join(codes))
        self.box.configure(state="disabled")
        self.box.pack(fill="x")
        row = ctk.CTkFrame(self.body, fg_color="transparent")
        row.pack(fill="x", pady=(16, 0))
        button(row, "I've saved them", self.done, width=150).pack(side="right")
        self.copy_btn = button(row, "Copy codes", self.copy, kind="secondary", width=120)
        self.copy_btn.pack(side="right", padx=8)

    def copy(self):
        self.clipboard_clear()
        self.clipboard_append("\n".join(self.codes))
        self.copy_btn.configure(text="Copied ✔")

    def done(self):
        self.result = True
        self.destroy()

    def cancel(self):
        if messagebox.askyesno("Close?", "Have you saved the backup codes? They won't be shown again.",
                               parent=self):
            self.done()


class ReportDialog(Dialog):
    def __init__(self, master):
        super().__init__(master, "Report a problem")
        label(self.body, "Report a problem", 20, "bold").pack(anchor="w")
        label(self.body, "Say what happened and what you expected. The app version and its recent log are "
                         "sent with it. No photos or personal info.", 13, color=MUTED, wraplength=420).pack(
            anchor="w", pady=(2, 12))
        self.box = ctk.CTkTextbox(self.body, height=150, width=420, corner_radius=10, font=font(14))
        self.box.pack(fill="x")
        row = ctk.CTkFrame(self.body, fg_color="transparent")
        row.pack(fill="x", pady=(16, 0))
        button(row, "Send", self.ok, width=110).pack(side="right")
        button(row, "Cancel", self.cancel, kind="ghost", width=90).pack(side="right", padx=8)
        self.after(120, self.box.focus_set)

    def ok(self):
        self.result = self.box.get("1.0", "end").strip()
        self.destroy()


class MainWindow:
    TICK_MS = 250
    NAV = [("home", "Home", "home"), ("apps", "Blocked apps", "apps"), ("settings", "Settings", "settings")]

    def __init__(self, root: ctk.CTk, config: Config, cloud_api=None, blocker: Blocker | None = None):
        self.root = root
        self.config = config
        self.ctl = Controller(config)
        self.cloud = cloud_api or cloud  # the online service; tests pass a fake
        self.blocker = blocker
        self.session: str | None = None  # phone scan being waited on
        self._polling = False
        self._next_poll = 0.0
        self._starting_session = False
        self._ui_calls = collections.deque()  # results from background threads, applied on the next tick
        self.pin_limiter = AttemptLimiter()
        self.code_limiter = AttemptLimiter()
        self.admin_until = 0.0
        self.last_result: dict | None = None
        self.current = None
        self.checking = False  # photos from the PC are being checked
        self._was_locked = self.ctl.is_locked()
        self._last_state = self.ctl.state()
        self._blocked_events = collections.deque()  # filled by the blocker thread
        self._toast_times: dict[str, float] = {}
        self.toast: Toast | None = None

        root.title(TITLE)
        try:
            root.iconbitmap(app_icon_path())
        except Exception:
            pass
        root.geometry("1000x680")
        root.minsize(900, 620)
        root.configure(fg_color=BG)
        root.protocol("WM_DELETE_WINDOW", self.minimize)
        self.guarded = False  # True when a watchdog guard restarts the app if it's ended from Task Manager
        self._ticks = 0
        root.grid_columnconfigure(1, weight=1)
        root.grid_rowconfigure(0, weight=1)

        # ---- sidebar ----
        side = ctk.CTkFrame(root, fg_color=SIDEBAR, corner_radius=0, width=230, border_width=0)
        side.grid(row=0, column=0, sticky="nsw")
        side.grid_propagate(False)
        side.grid_columnconfigure(0, weight=1)
        side.grid_rowconfigure(5, weight=1)
        brand = ctk.CTkFrame(side, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=20, pady=(26, 22))
        ctk.CTkLabel(brand, text="", image=icon("lock", 20, "#FFFFFF"), width=40, height=40, corner_radius=11,
                     fg_color=ACCENT).pack(side="left")
        label(brand, "Homework\nLock", 16, "bold").pack(side="left", padx=12)
        self.nav_buttons = {}
        self.nav_icons = {}
        for i, (key, text, ico) in enumerate(self.NAV, start=1):
            self.nav_icons[key] = (icon(ico, 18, TEXT), icon(ico, 18, ACCENT))
            b = ctk.CTkButton(side, text="  " + text, anchor="w", height=44, corner_radius=10, font=font(15),
                              fg_color="transparent", hover_color=SUBTLE, text_color=TEXT,
                              image=self.nav_icons[key][0], compound="left",
                              command=lambda k=key: self.navigate(k))
            b.grid(row=i, column=0, sticky="ew", padx=12, pady=2)
            self.nav_buttons[key] = b

        status = ctk.CTkFrame(side, fg_color="transparent")
        status.grid(row=6, column=0, sticky="ew", padx=20, pady=(0, 6))
        self.side_status = label(status, "", 14, "bold")
        self.side_status.pack(anchor="w")
        self.side_mode = label(status, "", 13, color=MUTED)
        self.side_mode.pack(anchor="w")
        ctk.CTkFrame(side, height=1, fg_color=BORDER).grid(row=7, column=0, sticky="ew", padx=20, pady=10)
        button(side, "  Report a problem", self.report_problem, kind="ghost", anchor="w", font=font(14),
               text_color=MUTED, icon_name="feedback").grid(row=8, column=0, sticky="ew", padx=12)
        button(side, "  Quit", self.request_quit, kind="ghost", anchor="w", font=font(14), text_color=MUTED,
               icon_name="power").grid(row=9, column=0, sticky="ew", padx=12, pady=(0, 18))

        # ---- pages ----
        content = ctk.CTkFrame(root, fg_color="transparent")
        content.grid(row=0, column=1, sticky="nsew", padx=36, pady=30)
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(0, weight=1)
        self.pages = {"home": HomePage(content, self), "apps": AppsPage(content, self),
                      "settings": SettingsPage(content, self)}
        self.home: HomePage = self.pages["home"]
        self.navigate("home")
        self.tick()

    # ---------- helpers ----------
    def parent_mode(self) -> bool:
        return self.config.get("mode") == "parent"

    def ask_pin(self, why: str) -> bool:
        """True if not in parent mode, or the right PIN is entered."""
        if not self.parent_mode():
            return True
        wait = self.pin_limiter.wait_seconds()
        if wait:
            messagebox.showerror("Locked out", f"Too many wrong PINs. Try again in {wait} seconds.", parent=self.root)
            return False
        pin = ask_text(self.root, "Parent PIN", f"Enter the parent PIN to {why}.", secret=True)
        if pin is None:
            return False
        ok = self.config.check_pin(pin)
        self.pin_limiter.record(ok)
        if not ok:
            messagebox.showerror("Wrong PIN", "That PIN is not correct.", parent=self.root)
        return ok

    def navigate(self, name: str):
        if name in ("apps", "settings") and self.parent_mode() and time.time() >= self.admin_until:
            if not self.ask_pin("open " + ("Blocked apps" if name == "apps" else "Settings")):
                return
            self.admin_until = time.time() + ADMIN_SECONDS
        if name == "home":
            self.admin_until = 0.0  # leaving the parent pages needs the PIN again
        for key, page in self.pages.items():
            if key == name:
                page.grid(row=0, column=0, sticky="nsew")
            else:
                page.grid_remove()
            active = key == name
            if key in self.nav_buttons:
                self.nav_buttons[key].configure(fg_color=ACCENT_SOFT if active else "transparent",
                                                text_color=ACCENT if active else TEXT,
                                                image=self.nav_icons[key][1 if active else 0])
        self.current = name
        self.pages[name].refresh()

    # ---------- first-run setup ----------
    def start_setup(self):
        from .ui_setup import SetupPage
        self.pages["setup"] = SetupPage(self.home.master, self)
        self.navigate("setup")

    def finish_setup(self):
        self.config.set(setup_done=True)
        page = self.pages.pop("setup", None)
        self.navigate("home")
        if page is not None:
            page.destroy()

    # ---------- background work ----------
    def run_in_background(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    def later(self, fn):
        """From a background thread: run fn on the UI thread at the next tick."""
        self._ui_calls.append(fn)

    def refresh_mode(self):
        self.home.refresh()

    # ---------- countdown ----------
    def tick(self):
        state = self.ctl.state()
        locked = state == schedule.LOCKED
        if locked:
            self.side_status.configure(text="●  Locked", text_color=RED)
        elif state == schedule.FREE:
            self.side_status.configure(text="●  Free time", text_color=ACCENT)
        elif self.config.get("schedule_enabled"):
            self.side_status.configure(text="●  Unlocked", text_color=GREEN)
        else:
            self.side_status.configure(text=f"●  Unlocked · {fmt_remaining(self.ctl.remaining())}",
                                       text_color=GREEN)
        self.side_mode.configure(text="Parent mode" if self.parent_mode() else "Student mode")
        self.home.refresh()
        if locked and not self._was_locked:
            self.on_relocked()
            if self._last_state == schedule.FREE:
                self.toast = Toast(self.root, "Homework time",
                                   "Your apps are blocked until your homework is approved. Click to open.",
                                   on_click=self.bring_to_front)
        if locked != self._was_locked and self.current in ("apps", "settings"):
            self.pages[self.current].refresh()  # Remove buttons and schedule controls follow the lock
        self._was_locked = locked
        self._last_state = state
        while self._blocked_events:
            self.show_blocked_notice(self._blocked_events.popleft())
        while self._ui_calls:
            self._ui_calls.popleft()()
        if self.session:
            self.poll_session()
        self._ticks += 1
        if self.guarded and self._ticks % 12 == 0:  # about every 3 s
            self.check_guard()
        self._tick_id = self.root.after(self.TICK_MS, self.tick)

    def on_relocked(self):
        if self.blocker:
            self.blocker.sweep()
        self.root.bell()

    # ---------- "app is blocked" notice ----------
    def notify_blocked(self, exe: str):
        """Called from the blocker thread; the notice is shown on the next tick."""
        self._blocked_events.append(exe)

    def show_blocked_notice(self, exe: str):
        name = self.config.app_label(exe)
        now = time.time()
        if now - self._toast_times.get(name, 0) < TOAST_REPEAT_SECONDS:
            return
        self._toast_times[name] = now
        if self.toast is not None and self.toast.winfo_exists():
            self.toast.close()
        self.toast = Toast(self.root, f"{name} is blocked",
                           "Finish your homework, then unlock it with a photo. Click here to open Homework Lock.",
                           on_click=self.bring_to_front)

    def bring_to_front(self):
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(200, lambda: self.root.attributes("-topmost", False))
        self.root.focus_force()
        self.navigate("home")

    # ---------- photo checks ----------
    def record_result(self, result: dict, page_count: int):
        self.last_result = {**result, "page_count": page_count, "at": time.time()}
        if result.get("approved"):
            self.ctl.unlock()

    def handle_photo(self, pages: list[bytes]) -> dict:
        """Photos picked on this PC, one per homework page. Runs on a background thread."""
        result = self.cloud.check_photos(self.config, pages)
        self.record_result(result, len(pages))
        return result

    def show_qr(self):
        """Unlock with phone: start a scan session online and show its QR code."""
        if self._starting_session:
            return
        self._starting_session = True

        def start():
            try:
                token, url = self.cloud.new_session(self.config)
                self.later(lambda: self._session_started(token, url))
            except CloudError as e:
                msg = str(e)
                self.later(lambda: messagebox.showerror("Can't start a scan", msg, parent=self.root))
            finally:
                self._starting_session = False
        self.run_in_background(start)

    def _session_started(self, token: str, url: str):
        self.session, self.qr_url = token, url
        self.checking = False
        self._next_poll = time.time() + POLL_SECONDS
        self.last_result = None  # a new attempt replaces the old verdict
        self.navigate("home")
        self.home.show_qr(qr_image(url, box_size=8), time.time() + SESSION_TTL, url)

    def poll_session(self):
        """Ask the online service whether the phone scan has a verdict yet (every POLL_SECONDS)."""
        if self._polling or time.time() < self._next_poll:
            return
        self._polling = True
        token = self.session

        def poll():
            try:
                r = self.cloud.poll(self.config, token)
            except CloudError:
                r = {}  # offline for a moment: try again next time
            finally:
                self._next_poll = time.time() + POLL_SECONDS
                self._polling = False
            self.later(lambda: self._poll_answer(token, r))
        self.run_in_background(poll)

    def _poll_answer(self, token: str, r: dict):
        if token != self.session:
            return  # a newer QR code replaced this one
        status = r.get("status")
        if status == "checking":
            self.checking = True
        elif status in ("done", "expired"):
            self.session, self.checking = None, False
            if status == "done":
                result = r.get("result") or {}
                self.record_result(result, len(result.get("pages") or []) or 1)
        self.home.refresh()

    def upload_from_pc(self):
        """Upload from PC button: pick one photo per page and check them like photos from the phone."""
        if self.checking:
            return
        if not self.config.get("allow_uploads"):
            messagebox.showinfo("Uploads are off", "A parent turned off photo uploads. Use your phone's camera "
                                "instead.", parent=self.root)
            return
        paths = filedialog.askopenfilenames(
            parent=self.root, title="Pick a photo of every homework page",
            filetypes=[("Photos", "*.jpg *.jpeg *.png *.webp *.bmp *.gif"), ("All files", "*.*")])
        if not paths:
            return
        paths = sorted(paths, key=lambda p: Path(p).name.lower())  # pages go in file-name order
        problem = pc_photo_problem(paths)
        if problem:
            messagebox.showerror("Can't use these photos", problem, parent=self.root)
            return
        pages = [Path(p).read_bytes() for p in paths]
        self.checking = True
        self.last_result = None
        self.home.refresh()
        threading.Thread(target=self._check_pc_photos, args=(pages,), daemon=True, name="PcUpload").start()

    def _check_pc_photos(self, pages: list[bytes]):
        try:
            self.handle_photo(pages)
        except Exception as e:
            if not isinstance(e, CloudError):
                logging.exception("PC upload check failed")
            self.last_result = {"approved": False, "reason": f"Could not check the photos: {e}",
                                "page_count": len(pages), "at": time.time()}
        finally:
            pages.clear()
            self.checking = False

    # ---------- actions ----------
    def override_unlock(self):
        """Override button: unlocks every app right away. Students just click; parent mode needs the PIN."""
        if self.ask_pin("unlock all apps"):
            self.ctl.unlock()
            self.home.refresh()

    def lock_now(self):
        self.ctl.lock()

    def enter_parent_code(self):
        wait = self.code_limiter.wait_seconds()
        if wait:
            messagebox.showerror("Locked out", f"Too many wrong codes. Try again in {wait} seconds.",
                                 parent=self.root)
            return
        code = ask_text(self.root, "Parent code", "Enter the 6-digit code from your authenticator app, "
                        "or one of your backup codes.", placeholder="123456")
        if code is None:
            return
        ok = override.verify(self.config, code)
        self.code_limiter.record(ok)
        if ok:
            self.ctl.unlock()
        else:
            messagebox.showerror("Not accepted", "That code is wrong, expired, or was already used.",
                                 parent=self.root)

    def change_pin(self) -> bool:
        pin = ask_text(self.root, "Parent PIN", "Choose a PIN of at least 4 digits.", secret=True)
        if pin is None:
            return False
        if len(pin) < 4 or not pin.isdigit():
            messagebox.showerror("PIN", "The PIN must be at least 4 digits.", parent=self.root)
            return False
        if ask_text(self.root, "Parent PIN", "Type the same PIN again.", secret=True) != pin:
            messagebox.showerror("PIN", "The PINs didn't match. Please try again.", parent=self.root)
            return False
        self.config.set_pin(pin)
        return True

    def enable_parent_mode(self) -> bool:
        if not self.config.has_pin():
            messagebox.showinfo("Parent mode", "First, create a parent PIN.", parent=self.root)
            if not self.change_pin():
                return False
        self.config.set(mode="parent")
        self.admin_until = time.time() + ADMIN_SECONDS
        self.refresh_mode()
        return True

    def setup_totp(self):
        if not self.config.has_pin():
            messagebox.showerror("Authenticator", "Create a parent PIN first.", parent=self.root)
            return
        if override.is_set_up(self.config) and not messagebox.askyesno(
                "Replace authenticator?", "Your current authenticator codes and backup codes will stop working.",
                parent=self.root):
            return
        uri, codes = override.setup(self.config)
        self.totp_win = TotpDialog(self.root, uri, self.config.get("totp_secret"), codes)
        self.totp_win.show()
        self.refresh_mode()

    def minimize(self):
        """The window's X button. It closes the app once apps are unlocked or it's free time. While apps are
        locked, or in parent mode, it keeps running in the taskbar instead."""
        if self.ctl.is_locked() or self.parent_mode():
            self.root.iconify()
        else:
            self.shutdown()

    def request_quit(self):
        """Quit button. A student can't quit while apps are locked; a parent PIN always can."""
        if self.parent_mode():
            if not self.ask_pin("quit"):
                return
        elif self.ctl.is_locked():
            messagebox.showinfo("Finish your homework first",
                                "Homework Lock can't be closed while your apps are locked.\n\n"
                                "Upload photos of every page of your homework to unlock. After that you can "
                                "close it.", parent=self.root)
            return
        elif not messagebox.askyesno("Quit Homework Lock?",
                                     "Quitting stops blocking your apps.\nAre you sure you want to quit?",
                                     parent=self.root):
            return
        self.shutdown()

    def report_problem(self):
        text = ReportDialog(self.root).show()
        if not text:
            return

        def send():
            try:
                self.cloud.send_report(self.config, text)
                self.later(lambda: messagebox.showinfo("Thanks!", "Your report was sent.", parent=self.root))
            except CloudError as e:
                msg = str(e)
                self.later(lambda: messagebox.showerror("Not sent", msg, parent=self.root))
        self.run_in_background(send)

    # ---------- updates ----------
    def check_for_update(self):
        """Packaged app only: if GitHub has a newer release, download it, swap it in and restart."""
        def check():
            try:
                found = updater.latest_update()
                if not found:
                    return
                version, url = found
                self.later(lambda: Toast(self.root, "Update available",
                                         f"Downloading Homework Lock {version}. It restarts by itself.",
                                         on_click=self.bring_to_front))
                new_dir = updater.download(url)
                self.later(lambda: self.install_update(new_dir))
            except Exception:
                logging.exception("update check failed")
        self.run_in_background(check)

    def install_update(self, new_dir: Path):
        try:
            updater.start_finisher(new_dir)  # waits for this app to exit, then copies itself over it
        except OSError:
            logging.exception("could not start the update")
            return
        self.root.after(0, self.shutdown)  # not mid-tick; shutdown also stops the guard

    def check_guard(self):
        if self.guarded and not watchdog.find_guards():
            watchdog.start_guard()

    def shutdown(self):
        if self.guarded:
            self.guarded = False
            watchdog.stop_guards()  # a normal quit must not be "restarted"
        if self.blocker:
            self.blocker.stop()
        self.root.after_cancel(self._tick_id)
        self.root.destroy()


_instance_mutex = None


def pc_photo_problem(paths) -> str | None:
    """Same limits as the phone page: a page count in range, not too large, and no photos over a day old."""
    if not 1 <= len(paths) <= MAX_PAGES:
        return f"Pick 1 to {MAX_PAGES} photos, one for each page."
    now = time.time()
    total = 0
    for p in paths:
        st = Path(p).stat()
        total += st.st_size
        if now - st.st_mtime > MAX_PHOTO_AGE:
            return f"{Path(p).name} is more than a day old. Use a new photo of today's homework."
    if total > MAX_UPLOAD:
        return "Those photos are too large."
    return None


def _already_running() -> bool:
    """Single-instance check. If another copy is running, bring its window forward."""
    global _instance_mutex
    k32, user32 = ctypes.windll.kernel32, ctypes.windll.user32
    _instance_mutex = k32.CreateMutexW(None, False, "Local\\HomeworkLock.SingleInstance")
    if k32.GetLastError() != 183:  # ERROR_ALREADY_EXISTS
        return False
    hwnd = user32.FindWindowW(None, TITLE)
    if hwnd:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
    return True


def _quiet_process():
    """No console: when started with pythonw there is no stderr, so log to a file instead."""
    if sys.stderr is None or sys.stdout is None:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        log = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log
    try:  # own taskbar entry and icon instead of Python's
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (OSError, AttributeError):
        pass


def _sync_autostart(config: Config):
    """Put the auto-start task back if it was deleted (it's on unless turned off in Settings). The packaged
    app rewrites it every start, so it still points at the exe if the folder was moved."""
    try:
        if config.get("autostart") and (FROZEN or not startup.is_enabled()):
            startup.enable()
    except OSError:
        logging.exception("could not set up auto-start")


def main():
    _quiet_process()
    if _already_running():
        return
    config = Config()
    ctk.set_appearance_mode(config.get("appearance") or "system")
    ctk.set_default_color_theme("blue")
    root = ctk.CTk()
    holder = {}
    blocker = Blocker(config, on_kill=lambda exe: holder["win"].notify_blocked(exe) if "win" in holder else None)
    blocker.start()
    win = holder["win"] = MainWindow(root, config, blocker=blocker)
    if not config.get("setup_done"):
        win.start_setup()
    if FROZEN:
        updater.remove_leftovers()
        win.check_for_update()
    root.update_idletasks()
    try:  # so pinning the running window pins Homework Lock, with its icon
        set_window_identity(int(root.wm_frame(), 16))
    except Exception:
        logging.exception("could not set taskbar identity")
    win.guarded = True
    win.check_guard()
    threading.Thread(target=_sync_autostart, args=(config,), daemon=True, name="Autostart").start()
    if startup.STARTUP_FLAG in sys.argv:
        root.after(300, root.iconify)  # started with Windows: run quietly in the taskbar
    elif watchdog.RESTARTED_FLAG in sys.argv:
        root.after(800, lambda: Toast(root, "Homework Lock is still on",
                                      "It can't be closed until your homework is done.",
                                      on_click=win.bring_to_front))
    root.mainloop()
