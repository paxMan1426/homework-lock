# Homework Lock

A Windows desktop app that blocks chosen apps until you prove your homework is done by taking a photo of it with your phone. The photo is checked by Claude (`claude-haiku-5-5`).

## Installing the beta (friends)

Download `HomeworkLock.zip` from the latest GitHub release, right-click it → **Extract All**, open the folder and run `HomeworkLock.exe`. Windows SmartScreen may say "Windows protected your PC" because the app isn't code-signed: click **More info → Run anyway**. A first-run screen asks who's setting it up (just me, or a parent with a PIN and optional authenticator) and which apps to block. The app updates itself: when a newer release is out, it downloads it, swaps it in and restarts. Settings and the log live in `%APPDATA%\HomeworkLock`, so updates keep them.

Photos are checked by an online service (a Cloudflare Worker in `worker/`), so the phone doesn't need to be on the same Wi-Fi, and no API key is on the PC. Each install gets 10 homework checks a day. **Report a problem** in the sidebar sends a description, the app version and the last 50 log lines (no photos).

## Setup (development)

```powershell
pip install -r requirements.txt
python -m homework_lock.shortcuts      # adds "Homework Lock" to the Desktop and Start Menu
```

`homework_lock/version.py` holds the version, the Worker URL and the GitHub repo. `worker/` is the online service (`npm install`, then `npx wrangler deploy`; see `worker/wrangler.toml`). `python release.py patch "What changed"` bumps the version, runs the tests, builds `dist/HomeworkLock.zip` with PyInstaller, updates `CHANGELOG.md` and publishes a GitHub release. `python release.py --build-only` just builds.

Start it from the **Homework Lock** shortcut. To pin it to the taskbar, right-click the running app's taskbar button → **Pin to taskbar**, or right-click the Start Menu entry. The shortcuts and the window share one app ID and icon, so the pin opens Homework Lock. Running `python -m homework_lock.shortcuts` again also unpins old broken pins: ones made before this fix start a bare `pythonw.exe` and fail with "Windows cannot find '\\'". Windows doesn't let programs pin themselves, so pin it again by hand afterwards. It runs with `pythonw`, so no console window opens, and it has its own taskbar icon. Starting it a second time brings the open window to the front instead of running two copies. Errors go to `homework_lock.log`. For debugging with a console, use `python main.py`.

## Using it

Everything happens in one window with three pages in the sidebar:

- **Home**: shows whether you're locked or unlocked, the countdown, and the unlock button
- **Blocked apps**: lists the apps that get blocked, with buttons to add and remove them
- **Settings**: unlock time, Student/Parent mode, parent PIN, authenticator, and light/dark appearance. Changes save automatically.

1. Go to **Blocked apps** → **Add apps**, tick the apps you want, and click **Block**. The list shows:
   - **Open now**: apps that have a window open right now
   - **Popular games & apps**: Roblox, Minecraft, Fortnite, Steam, Discord and more, already set up (some games use more than one process, and all of them get blocked)
   - **Installed**: everything in your Start Menu

   You can also type in the search box to filter. If nothing matches, the typed name is offered as a program name. **Click on an app to block it** gives you 5 seconds to click the app's window. **Browse for a program** accepts an `.exe` or a shortcut. System apps such as Explorer and Python can't be blocked.
   While apps are locked, a student can still add apps but can't remove them: the **Remove** buttons are greyed out until homework is approved or free time starts. In parent mode, the PIN allows removing apps at any time.
2. Set how many minutes an unlock lasts. (With the lock schedule on, an unlock lasts until midnight instead.)
3. While the app is locked, a blocked app closes about 2 seconds after it opens, and a small notice in the corner says it's blocked. Clicking the notice opens Homework Lock. The short delay is deliberate: if an app is closed in its first moments, Windows shows a confusing "Windows cannot access the specified device, path, or file" error.
4. On **Home**, click **Unlock with phone** and scan the QR code with your phone. The link is also shown under the code: type it into the phone's browser, click **Copy** to send it to yourself, or click **Open in browser** to upload photos from this PC. **Open in browser** is hidden when photo uploads are turned off, because a PC has no phone camera. Add a photo of **every** page, in order. A new page slot appears after each photo, and the **×** on a photo removes it. You don't enter a page count: Claude works out from the photos how many pages the homework has and says which ones are missing (for example "It looks like your homework has 4 pages, but you sent 2 photos (missing: pages 3 and 4)"). Add an optional note. Each page has a **Camera** button and an **Upload** button for existing photos. **Upload several pages at once** fills the pages in order. Gallery photos more than a day old are refused, when the phone reports the photo's date (many Android phones do; iPhones often report the upload time instead). Parents can turn uploads off under Settings → Photo uploads, which leaves camera only. **Submit** stays disabled until there's at least one photo. The link works once and expires after 5 minutes. The PC asks the online service for the verdict every 2 seconds, so Home updates on its own.
   **Upload from PC** on Home does the same check without a phone. Pick one photo per page; pages are checked in file-name order, and photos more than a day old (by file date) are refused. It's hidden when photo uploads are turned off.
5. If every page is approved, a countdown with a progress bar starts. When it ends, the apps lock again. If anything fails, the phone and Home show the reason and which page has the problem.

### How "every page" is checked

All pages go to Claude in one request, and it gives a verdict for each page. Apps unlock only if **all** of these hold, and the code enforces it even when the model says "approved":

- every page shows real, completed work: no blank pages and no unanswered questions
- nothing suggests pages are missing, such as "Page 2 of 4" labels, gaps in problem numbers between pages, a last page that stops mid-problem or says "turn over", or references to questions that weren't sent
- if a staple shows in any photo, the homework counts as at least 3 pages, so fewer than 3 photos is rejected
- no page is a photo of a screen, unrelated, or unreadable, and no two photos show the same page
- one photo may show more than one page, such as an open workbook; every page in it is checked

Limits: Claude can only judge what's in the photos. If a teacher assigned pages that have no visible "page X of Y" label or numbering, and the student leaves them out, nothing in the photos gives that away. Re-used photos are caught only as exact file copies. A new photo of an old page can't be told apart from a different page by image matching, because pages of one worksheet look too alike. Photos and camera frames are kept only in the online service's memory for the one request and discarded after the check; only the verdict text and file hashes are saved.

## Schedule and startup

- **Lock schedule** (Settings): turn on **Lock after a set time**, pick a start time (for example 3:00 PM), and pick the days. Before that time, and on days that aren't picked, apps are free. From that time until midnight they stay locked until a photo is approved. With the schedule on, an approved photo (or a parent unlock) unlocks apps for the rest of the day, until midnight, and the **Unlock time** setting is greyed out. Because the lock is worked out from the clock, restarting the PC or the app doesn't unlock anything. When the lock starts, a "Homework time" notice appears. With the schedule off, apps are locked all the time until a photo is approved.
- **Start automatically** (Settings, on by default): a per-user scheduled task named `HomeworkLock` (no admin rights needed) runs `homework_lock/autostart.py` when you sign in and then every minute. That script exits right away if Homework Lock is already running or nothing needs blocking (free time, or unlocked). Otherwise it starts Homework Lock minimized. So the app comes back within about a minute of a lock starting, even after it was closed once homework was done, after both processes were ended in Task Manager, or after the PC wakes from sleep. The task also runs on battery. If the task is deleted, Homework Lock adds it again the next time it starts. In student mode it can't be turned off while apps are locked. In parent mode, Settings needs the PIN.
- **No changing the rules while locked**: in student mode, the lock schedule, its time and days, and the unlock time are greyed out while apps are locked. You can change them after homework is approved or during free time.

## Closing it

- The window's **X** (and Alt+F4) closes the app once apps are unlocked or during free time. While apps are locked, or in parent mode, it only minimizes to the taskbar.
- **Quit** while apps are locked: a student can't quit. The app says to finish the homework first. After homework is approved, or during free time, a student can quit after confirming. In parent mode, the PIN always allows quitting.
- **Task Manager → End task:** a small guard process (`homework_lock/watchdog.py`, a separate `pythonw.exe`) starts Homework Lock again within about a second. The app also restarts the guard if the guard is ended. A normal Quit stops the guard first. To stop it during development, end the guard and then the app.

## Modes

**Override** on Home unlocks every app right away, for the usual unlock time. In parent mode it's a button that needs the PIN. In student mode it's hidden.

- **Self mode** (students): no PIN. Quitting is blocked while apps are locked, and asks for confirmation otherwise.
- **Parent mode**: switch to it in Settings. If no PIN exists yet, you'll be asked to create one. After that, the PIN is needed to open Blocked apps or Settings, unlock early, or quit. A correct PIN keeps those pages open for 5 minutes, or until you go back to Home. Five wrong tries lock entry for 60 seconds.

### Parent override (authenticator)

In Settings, choose **Parent authenticator → Set up**. Scan the QR code with an authenticator app such as Google Authenticator or Microsoft Authenticator, then write down the 5 backup codes. They are shown only once.

To unlock, click **Use parent code** on Home and enter either the current 6-digit code or a backup code. Each authenticator code works once, and each backup code works once. Running setup again replaces all old codes.

## Files

- `config.json`: settings (next to the code when run from source, in `%APPDATA%\HomeworkLock` for the packaged app). It stores only salted PBKDF2 hashes of the PIN and backup codes. The TOTP secret is stored as-is, because it has to be. Set `HOMEWORK_LOCK_CONFIG` to use a different location. It's in `.gitignore`: never publish it.
- `homework_lock/`: the logic lives in `blocker.py`, `apps.py`, `cloud.py` (online service), `updater.py` and `override.py`. The UI (CustomTkinter) lives in `app.py`, `ui_home.py`, `ui_apps.py`, `ui_settings.py`, `ui_setup.py`, `ui_common.py` and `icons.py`.
- `worker/`: the Cloudflare Worker: phone page, Claude checks, rate limits, problem reports.
- `tests/`: run with `python -m pytest tests`.

## Limits

This is a deterrent, not a security product. A determined user can still end both processes at the same moment (for example `taskkill /F /IM pythonw.exe`; the auto-start task brings it back within a minute), delete the `HomeworkLock` task in Task Scheduler and then end both processes, change the PC's clock or time zone, rename an app's `.exe`, edit `config.json`, or sign in to another Windows account. For stronger protection, run it under a parent's account and give the student a standard (non-admin) Windows account.
