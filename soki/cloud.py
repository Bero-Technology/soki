"""Soki Managed's browser, reached over HTTPS (config "browser": "cloud").

    soki config set cloud_key <your Soki key>      # from gosoki.com
    soki config set browser cloud

The browser runs on Soki's machines and is not in this package: this file only speaks the API (docs/CLOUD.md). Your
books, rules and caps stay on your machine and are checked here first, as for every driver; the API checks your plan
and its own caps again on its side, so a changed copy of this file can't send more than your plan allows.

Every send carries an idempotency key made from the person (and the text, for a message). Asking twice for the same
invite gets back the first answer, never a second invite.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

from . import __version__, books, config
from .browser import LOGIN_URLS, PROTOCOL, Driver

KEY = "SOKI_API_KEY"
POLL_SECONDS = 4.0
WAIT_SEND = 300          # an invite or message: how long to wait for the browser to finish it
WAIT_LOGIN = 600         # the person logging in through the live view
PENDING = ("queued", "running")
HTTP_ERRORS = {
    401: "the Soki key was not accepted: check it at gosoki.com, then `soki config set cloud_key <key>`",
    402: "your Soki plan doesn't cover this: see gosoki.com/#pricing",
    403: "your Soki key can't use this account",
    429: "Soki's own limits for this account are reached for now: try again later",
}


def _idem(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:32]


class Cloud(Driver):
    name = "cloud"

    def __init__(self, cfg: dict):
        self.base = (cfg.get("cloud_url") or config.DEFAULTS["cloud_url"]).rstrip("/")
        self.key = config.secret(KEY)
        if not self.key:
            raise SystemExit("browser cloud needs a Soki key: get one at gosoki.com, then "
                             "`soki config set cloud_key <key>`")

    def _call(self, method: str, path: str, body: dict | None = None, idem: str = "", timeout: int = 60) -> dict:
        headers = {"Authorization": f"Bearer {self.key}", "Accept": "application/json",
                   "User-Agent": f"soki/{__version__}", "Soki-Protocol": str(PROTOCOL)}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if idem:
            headers["Idempotency-Key"] = idem
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                out = json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                out = json.loads(e.read() or b"{}")
            except ValueError:
                out = {}
            msg = (out.get("error") if isinstance(out, dict) else "") or HTTP_ERRORS.get(e.code) or f"HTTP {e.code}"
            return {"ok": False, "error": msg, "status": e.code}
        except (urllib.error.URLError, OSError) as e:
            return {"ok": False, "error": f"could not reach Soki at {self.base}: {getattr(e, 'reason', e)}"}
        except ValueError:
            return {"ok": False, "error": "Soki answered with something that isn't JSON"}
        if not isinstance(out, dict) or "ok" not in out:
            return {"ok": False, "error": "Soki answered without a result"}
        return out

    def _settle(self, r: dict, wait: int) -> dict:
        """A send may come back queued: follow its job until it has a result, or say plainly that it's still going."""
        end = time.time() + wait
        while r.get("ok") and r.get("result") in PENDING and r.get("job"):
            if time.time() > end:
                return {"ok": False, "error": f"still {r['result']} on Soki's side (job {r['job']}). It will not go "
                                              "twice: `soki send` again later picks up its result"}
            time.sleep(POLL_SECONDS)
            r = self._call("GET", f"/jobs/{urllib.parse.quote(str(r['job']))}")
        return r

    def setup(self) -> dict:
        r = self._call("GET", "/me")
        if r.get("ok"):
            r.setdefault("detail", f"Soki Managed{' (' + r['plan'] + ')' if r.get('plan') else ''} is ready")
        return r

    def status(self) -> dict:
        r = self._call("GET", "/accounts/linkedin")
        return {**r, "driver": "cloud", "protocol": PROTOCOL}

    def login(self, site: str) -> dict:
        if site not in LOGIN_URLS:
            return {"ok": False, "error": f"unknown site {site!r} (one of {', '.join(LOGIN_URLS)})"}
        r = self._call("POST", "/accounts", {"site": site})
        if not r.get("ok") or r.get("logged_in"):
            return r
        live = r.get("live_url", "")
        if not live:
            return {"ok": False, "error": "Soki gave no login page for this account"}
        # The person logs in themselves, in our browser, through this page. Soki never sees or types a password.
        print(f"{site}: log in on this page, it shows the browser that will work for you: {live}", file=sys.stderr,
              flush=True)
        if not os.environ.get("SOKI_AGENT"):
            webbrowser.open(live)
        end = time.time() + WAIT_LOGIN
        while time.time() < end:
            time.sleep(POLL_SECONDS)
            s = self._call("GET", f"/accounts/{urllib.parse.quote(site)}")
            if not s.get("ok"):
                return s
            if s.get("logged_in"):
                return {"ok": True, "site": site, "detail": "logged in", "account": s.get("account", "")}
        return {"ok": False, "error": f"{site}: not logged in after 10 minutes (the page was {live})"}

    def profile(self, url: str) -> dict:
        return self._settle(self._call("POST", "/profiles", {"url": url}), WAIT_SEND)

    def invite(self, url: str, note: str) -> dict:
        pid = books.person_id(url)
        r = self._call("POST", "/invites", {"url": url, "note": note}, idem=_idem("invite", pid))
        return self._settle(r, WAIT_SEND)

    def message(self, url: str, text: str) -> dict:
        pid = books.person_id(url)
        r = self._call("POST", "/messages", {"url": url, "text": text}, idem=_idem("message", pid, text))
        return self._settle(r, WAIT_SEND)

    def inbox(self, since: str = "") -> dict:
        return self._call("GET", "/inbox" + (f"?since={urllib.parse.quote(since)}" if since else ""), timeout=300)
