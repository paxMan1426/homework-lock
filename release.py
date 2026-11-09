"""One-command release: bump the version, test, build, write the changelog, publish on GitHub.

    python release.py patch "Faster scanning; close button on warnings"   (";" starts a new changelog line)
    python release.py minor            (changelog taken from the commit messages since the last release)
    python release.py 1.0.0 "First public beta"
    python release.py --build-only     (just build dist/HomeworkLock.zip to try it out; nothing is published)

Needs: a clean git checkout pushed to GitHub, and the GitHub CLI signed in (gh auth login).
Friends' apps see the new release the next time they start and update themselves.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VERSION_FILE = ROOT / "homework_lock" / "version.py"
CHANGELOG = ROOT / "CHANGELOG.md"
DIST = ROOT / "dist"
APP_DIR = DIST / "HomeworkLock"
ZIP = DIST / "HomeworkLock.zip"


def run(*cmd, capture=False) -> str:
    print("$", " ".join(cmd))
    r = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=capture)
    if r.returncode:
        sys.exit(f"Failed: {' '.join(cmd)}\n{r.stderr if capture else ''}")
    return (r.stdout or "").strip()


def current_version() -> str:
    return re.search(r'^VERSION = "([\d.]+)"', VERSION_FILE.read_text(encoding="utf-8"), re.M).group(1)


def bumped(version: str, how: str) -> str:
    if re.fullmatch(r"\d+\.\d+\.\d+", how):
        return how
    major, minor, patch = (int(x) for x in version.split("."))
    if how == "major":
        return f"{major + 1}.0.0"
    if how == "minor":
        return f"{major}.{minor + 1}.0"
    if how == "patch":
        return f"{major}.{minor}.{patch + 1}"
    sys.exit(f"Use patch, minor, major or a version like 1.2.3, not {how!r}.")


def set_version(v: str):
    text = VERSION_FILE.read_text(encoding="utf-8")
    VERSION_FILE.write_text(re.sub(r'^VERSION = ".*"', f'VERSION = "{v}"', text, flags=re.M), encoding="utf-8")


def build():
    shutil.rmtree(APP_DIR, ignore_errors=True)
    ZIP.unlink(missing_ok=True)
    run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--windowed",
        "--name", "HomeworkLock", "--icon", "homework_lock/assets/homework_lock.ico",
        "--add-data", "homework_lock/assets;homework_lock/assets", "--collect-data", "customtkinter",
        "--distpath", str(DIST), "--workpath", str(ROOT / "build"), "main.pyw")
    shutil.make_archive(str(ZIP.with_suffix("")), "zip", APP_DIR)  # the folder's contents at the zip's top
    print(f"Built {ZIP} ({ZIP.stat().st_size / 1e6:.0f} MB)")


def write_changelog(v: str, notes: str):
    old = CHANGELOG.read_text(encoding="utf-8") if CHANGELOG.exists() else "# Changelog\n"
    head, _, rest = old.partition("\n")
    entry = f"\n## v{v} ({date.today():%Y-%m-%d})\n\n{notes}\n"
    CHANGELOG.write_text(f"{head}\n{entry}{rest}", encoding="utf-8")


def notes_from_git() -> str:
    last = subprocess.run(["git", "describe", "--tags", "--abbrev=0"], cwd=ROOT, text=True,
                          capture_output=True).stdout.strip()
    log = run("git", "log", "--pretty=- %s", f"{last}..HEAD" if last else "HEAD", capture=True)
    return log or "- Small fixes"


def main():
    args = sys.argv[1:]
    if args == ["--build-only"]:
        build()
        return
    if not args:
        sys.exit(__doc__)
    from homework_lock.version import GITHUB_REPO, WORKER_URL
    if "YOUR-" in GITHUB_REPO or "YOUR-" in WORKER_URL:
        sys.exit("Fill in WORKER_URL and GITHUB_REPO in homework_lock/version.py first.")
    if run("git", "status", "--porcelain", capture=True):
        sys.exit("Commit or stash your changes first, so the release matches what's on GitHub.")
    old = current_version()
    v = bumped(old, args[0])
    notes = "\n".join(f"- {line.strip()}" for line in args[1].split(";")) if len(args) > 1 else notes_from_git()

    set_version(v)
    try:
        run(sys.executable, "-m", "pytest", "-q")
        build()
    except SystemExit:
        set_version(old)  # nothing was published: put the version back
        raise
    write_changelog(v, notes)
    run("git", "add", str(VERSION_FILE), str(CHANGELOG))
    run("git", "commit", "-m", f"Release v{v}")
    run("git", "tag", f"v{v}")
    run("git", "push")
    run("git", "push", "origin", f"v{v}")
    run("gh", "release", "create", f"v{v}", str(ZIP), "--repo", GITHUB_REPO,
        "--title", f"Homework Lock v{v} (beta)", "--notes", notes)
    print(f"\nPublished v{v}. Friends get it the next time Homework Lock starts.")


if __name__ == "__main__":
    main()
