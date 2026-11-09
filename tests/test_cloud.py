"""The cloud driver against a fake Soki API on localhost: auth, queued jobs, idempotency, login, errors."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from soki import books, browser, cli, cloud, config


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SOKI_HOME", str(tmp_path))
    monkeypatch.setenv("SOKI_AGENT", "1")            # never open a real browser from a test
    monkeypatch.delenv("SOKI_API_KEY", raising=False)
    monkeypatch.setattr(cloud, "POLL_SECONDS", 0.01)
    return tmp_path


class Fake:
    def __init__(self):
        self.calls, self.jobs, self.sent, self.logins = [], {}, {}, 0

    def handle(self, h, method):
        body = json.loads(h.rfile.read(int(h.headers.get("Content-Length") or 0)) or b"{}")
        self.calls.append((method, h.path, dict(h.headers), body))
        if h.headers.get("Authorization") != "Bearer good":
            return 401, {"ok": False}
        if (method, h.path) == ("GET", "/v1/me"):
            return 200, {"ok": True, "plan": "managed"}
        if (method, h.path) == ("POST", "/v1/accounts"):
            return 200, {"ok": True, "logged_in": False, "live_url": "https://live.example/abc"}
        if (method, h.path) == ("GET", "/v1/accounts/linkedin"):
            self.logins += 1
            return 200, {"ok": True, "logged_in": self.logins >= 2, "account": "Ada Lin"}
        if (method, h.path) == ("POST", "/v1/invites"):
            key = h.headers.get("Idempotency-Key")
            if key in self.sent:                     # asked twice: the first answer, never a second invite
                return 200, self.sent[key]
            self.jobs["j1"] = 0
            self.sent[key] = {"ok": True, "result": "queued", "job": "j1"}
            return 202, self.sent[key]
        if (method, h.path) == ("GET", "/v1/jobs/j1"):
            self.jobs["j1"] += 1
            return 200, ({"ok": True, "result": "running", "job": "j1"} if self.jobs["j1"] < 2
                         else {"ok": True, "result": "sent"})
        if (method, h.path) == ("POST", "/v1/messages"):
            return 429, {"ok": False}
        return 404, {"ok": False, "error": "no such call"}


@pytest.fixture
def api(monkeypatch):
    fake = Fake()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _do(self, method):
            code, out = fake.handle(self, method)
            raw = json.dumps(out).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            self._do("GET")

        def do_POST(self):
            self._do("POST")

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    cfg = config.load()
    cfg["browser"], cfg["cloud_url"] = "cloud", f"http://127.0.0.1:{srv.server_address[1]}/v1"
    config.save(cfg)
    config.save_secret("SOKI_API_KEY", "good")
    yield fake
    srv.shutdown()


def test_cloud_needs_a_key():
    cfg = config.load()
    cfg["browser"] = "cloud"
    with pytest.raises(SystemExit, match="Soki key"):
        browser.get(cfg)


def test_keys_file_keeps_both_keys():
    config.save_key("sk-model")
    config.save_secret("SOKI_API_KEY", "soki-1")
    config.save_key("sk-model-2")
    assert config.api_key() == "sk-model-2" and config.secret("SOKI_API_KEY") == "soki-1"


def test_config_set_cloud_key_goes_to_keys_not_config(capsys):
    cli.main(["config", "set", "cloud_key", "soki-xyz"])
    assert config.secret("SOKI_API_KEY") == "soki-xyz"
    p = config.config_path()
    assert not p.exists() or "soki-xyz" not in p.read_text()


def test_bad_key_is_a_plain_sentence(api):
    config.save_secret("SOKI_API_KEY", "bad")
    r = browser.get(config.load()).setup()
    assert r["ok"] is False and "not accepted" in r["error"]


def test_setup_and_login_through_the_live_page(api):
    drv = browser.get(config.load())
    assert drv.setup()["ok"]
    r = drv.login("linkedin")
    assert r == {"ok": True, "site": "linkedin", "detail": "logged in", "account": "Ada Lin"}
    assert drv.login("myspace")["ok"] is False


def test_invite_follows_the_job_and_never_sends_twice(api):
    drv = browser.get(config.load())
    r = drv.invite("https://www.linkedin.com/in/jane-doe/", "Hi Jane")
    assert r == {"ok": True, "result": "sent"}
    posts = [c for c in api.calls if c[:2] == ("POST", "/v1/invites")]
    assert posts[0][3] == {"url": "https://www.linkedin.com/in/jane-doe/", "note": "Hi Jane"}
    assert posts[0][2]["User-Agent"].startswith("soki/")
    # the same person under another spelling of the URL: same key, the first answer comes back
    drv.invite("linkedin.com/in/Jane-Doe", "Hi Jane")
    keys = {c[2]["Idempotency-Key"] for c in api.calls if c[:2] == ("POST", "/v1/invites")}
    assert len(keys) == 1


def test_invite_still_queued_is_not_a_send(api, monkeypatch):
    monkeypatch.setattr(cloud, "WAIT_SEND", 0)
    r = browser.get(config.load()).invite("https://www.linkedin.com/in/jane-doe/", "Hi Jane")
    assert r["ok"] is False and "will not go twice" in r["error"]


def test_server_limit_reads_as_a_sentence(api):
    r = browser.get(config.load()).message("https://www.linkedin.com/in/jane-doe/", "Thanks")
    assert r["ok"] is False and "limits" in r["error"]


def test_unreachable_api_is_a_sentence(api):
    cfg = config.load()
    cfg["cloud_url"] = "http://127.0.0.1:9/v1"
    config.save(cfg)
    r = browser.get(config.load()).status()
    assert r["ok"] is False and "could not reach Soki" in r["error"]


def test_send_through_cloud_records_the_invite(api):
    cfg = config.load()
    cfg["hours"] = [0, 24]
    config.save(cfg)
    pid, _ = books.add("linkedin.com/in/jane-doe", name="Jane Doe")
    books.save_draft(pid, "invite", "Hi Jane, your post on support queues stuck with me. Acme Help turns docs "
                                    "into a help bot. Ada")
    books.approve_draft(pid, "invite")
    books.set_status(pid, "approved")
    cli.main(["send"])
    assert books.get(pid)["status"] == "invited"
