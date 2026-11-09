"""Beta pieces: the online-service client, auto-update, first-run setup."""
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import pytest
from PIL import Image

from homework_lock import cloud, updater
from homework_lock.app import MainWindow
from homework_lock.config import Config


class FakeWorker(BaseHTTPRequestHandler):
    seen = []

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.seen.append(("GET", self.path, b""))
        self._send(404, {"status": "expired"})

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.seen.append(("POST", self.path, body))
        if self.path == "/api/session":
            self._send(200, {"token": "t1", "url": "https://w/s/t1", "expires_in": 300})
        elif self.path == "/api/check":
            self._send(200, {"approved": True, "reason": "ok", "subject": "Math", "pages": []})
        else:
            self._send(429, {"error": "Too many reports today."})

    def log_message(self, *a):
        pass


@pytest.fixture
def worker():
    FakeWorker.seen = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeWorker)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    with mock.patch.object(cloud, "WORKER_URL", f"http://127.0.0.1:{srv.server_port}"):
        yield FakeWorker.seen
    srv.shutdown()


def _jpeg(size=(3000, 2000)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, "white").save(out, format="PNG")
    return out.getvalue()


def test_cloud_client(worker, tmp_path):
    cfg = Config(tmp_path / "c.json")
    assert cloud.new_session(cfg) == ("t1", "https://w/s/t1")
    sent = json.loads(worker[-1][2])
    assert sent["install"] == cfg.install_id() and len(sent["install"]) >= 16   # same random ID every time
    assert cloud.poll(cfg, "t1") == {"status": "expired"}
    assert cloud.check_photos(cfg, [_jpeg()])["subject"] == "Math"
    body = worker[-1][2]
    assert b"image/jpeg" in body and body.count(b"\xff\xd8") == 1                 # sent as one shrunk JPEG
    assert len(body) < 200_000
    with pytest.raises(cloud.CloudError, match="Too many reports"):
        cloud.send_report(cfg, "broken")
    assert "broken" in json.loads(worker[-1][2])["description"]


def test_cloud_offline(tmp_path):
    with mock.patch.object(cloud, "WORKER_URL", "http://127.0.0.1:9"):
        with pytest.raises(cloud.CloudError, match="Couldn't reach"):
            cloud.new_session(Config(tmp_path / "c.json"))


def test_report_log_is_last_50_lines(tmp_path):
    log = tmp_path / "x.log"
    log.write_text("\n".join(f"line {i}" for i in range(80)), encoding="utf-8")
    with mock.patch.object(cloud, "LOG_PATH", log):
        lines = cloud.last_log_lines().splitlines()
    assert len(lines) == 50 and lines[0] == "line 30" and lines[-1] == "line 79"


def test_update_check():
    assert updater.parse_version("v1.10.0") > updater.parse_version("1.9.3")
    release = {"tag_name": "v99.0.0", "assets": [{"name": "HomeworkLock.zip", "browser_download_url": "https://x/z"}]}
    resp = mock.MagicMock()
    resp.__enter__.return_value.read.return_value = json.dumps(release).encode()
    with mock.patch.object(updater, "GITHUB_REPO", "me/homework-lock"), \
         mock.patch.object(updater, "_get", return_value=resp):
        assert updater.latest_update() == ("99.0.0", "https://x/z")
        release["tag_name"] = "v0.0.1"
        resp.__enter__.return_value.read.return_value = json.dumps(release).encode()
        assert updater.latest_update() is None
    with mock.patch.object(updater, "GITHUB_REPO", "YOUR-GITHUB-NAME/homework-lock"):
        assert updater.latest_update() is None      # repo not filled in yet: never checks


def test_setup_flag(tmp_path):
    assert Config(tmp_path / "new.json").get("setup_done") is False
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"mode": "self"}), encoding="utf-8")
    assert Config(old).get("setup_done") is True     # existing users skip first-run setup


def test_first_run_setup(root, tmp_path):
    cfg = Config(tmp_path / "c.json")
    w = MainWindow(root, cfg, cloud_api=mock.Mock(), blocker=mock.Mock())
    try:
        w.start_setup()
        assert w.current == "setup"
        page = w.pages["setup"]
        with mock.patch("homework_lock.app.ask_text", side_effect=["2468", "2468"]), \
             mock.patch("homework_lock.app.messagebox.showinfo"), \
             mock.patch("homework_lock.ui_setup.messagebox.askyesno", return_value=False):
            page.choose(parent=True)
        assert cfg.get("mode") == "parent" and cfg.check_pin("2468")
        w.finish_setup()
        assert cfg.get("setup_done") is True and w.current == "home" and "setup" not in w.pages
    finally:
        root.after_cancel(w._tick_id)


def test_frozen_commands():
    from homework_lock import paths, startup
    with mock.patch.object(paths, "FROZEN", True), mock.patch.object(startup, "FROZEN", True), \
         mock.patch("sys.executable", r"C:\Apps\HomeworkLock\HomeworkLock.exe"):
        assert paths.launch_command("--startup") == [r"C:\Apps\HomeworkLock\HomeworkLock.exe", "--startup"]
        assert startup.task_action() == (r"C:\Apps\HomeworkLock\HomeworkLock.exe", "--autostart")
