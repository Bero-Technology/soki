"""Optional driver: Soki drives a plain Chromium with Playwright (config "browser": "chromium").

    pip install 'soki[chromium]' && playwright install chromium

For someone whose agent has no browser of its own. It is honest automation: a site can tell (the automation flag, the
"controlled by automated test software" bar), so Soki holds its caps low in code (books.CHROMIUM_CAPS: 3 invites a
day, 15 a week) and it is never the default. The person logs in themselves in the window it opens; their session stays
in SOKI_HOME/chromium (one profile, their own, on their machine).
"""
from __future__ import annotations

import random
import re
import time

from . import config
from .browser import LOGIN_URLS, PROTOCOL, Driver

SIGNED_OUT = re.compile(r"/(login|authwall|checkpoint|uas/|signup)")


def _pause(lo: float = 1.5, hi: float = 4.0) -> None:
    time.sleep(random.uniform(lo, hi))


class Chromium(Driver):
    name = "chromium"

    def __init__(self):
        try:
            from playwright.sync_api import sync_playwright  # noqa: PLC0415
        except ImportError:
            raise SystemExit("the chromium browser needs Playwright: pip install 'soki[chromium]' && "
                             "playwright install chromium") from None
        self._sp = sync_playwright
        self._pw = self._ctx = None

    # one window, kept for the life of the command
    def _page(self):
        if self._ctx is None:
            self._pw = self._sp().start()
            kw = {"headless": False, "viewport": {"width": 1280, "height": 900}}
            last = None
            for channel in ("chrome", None):          # the Chrome already installed first: no download to go stale
                try:
                    self._ctx = self._pw.chromium.launch_persistent_context(
                        str(config.home() / "chromium"), **({"channel": channel} if channel else {}), **kw)
                    break
                except Exception as e:                # noqa: BLE001  (Playwright raises its own Error type)
                    last = e
            if self._ctx is None:
                self._pw.stop()
                self._pw = None
                raise SystemExit("could not start a browser: install Google Chrome, or run `playwright install "
                                 f"chromium` ({str(last).splitlines()[0][:160]})")
        return self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()

    def close(self) -> None:
        if self._ctx is not None:
            self._ctx.close()
            self._pw.stop()
            self._ctx = self._pw = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def _open(self, url: str):
        pg = self._page()
        pg.goto(url, wait_until="domcontentloaded", timeout=60000)
        _pause(2.5, 5)
        # a join wall can sit on the profile's own address: a password box on the page means signed out too
        if SIGNED_OUT.search(pg.url) or pg.locator("input[type=password]").count():
            raise PermissionError("LinkedIn is signed out in Soki's Chromium: `soki setup linkedin`")
        return pg

    def setup(self) -> dict:
        self._page()
        return {"ok": True, "detail": f"Chromium ready ({config.home() / 'chromium'})"}

    def login(self, site: str) -> dict:
        url = LOGIN_URLS.get(site)
        if not url:
            return {"ok": False, "error": f"unknown site {site!r} (one of {', '.join(LOGIN_URLS)})"}
        pg = self._page()
        pg.goto(url, wait_until="domcontentloaded")
        host = re.sub(r"^www\.", "", url.split("/")[2])
        end = time.time() + 600
        while time.time() < end:                      # the person logs in; we only watch the address
            time.sleep(3)
            u = pg.url
            if host in u and not SIGNED_OUT.search(u) and u.rstrip("/") != url.rstrip("/"):
                return {"ok": True, "site": site, "detail": "logged in"}
        return {"ok": False, "error": f"{site}: still on the login page after 10 minutes"}

    def status(self) -> dict:
        try:
            self._open("https://www.linkedin.com/feed/")
        except PermissionError:
            return {"ok": True, "driver": "chromium", "logged_in": False, "protocol": PROTOCOL}
        return {"ok": True, "driver": "chromium", "logged_in": True, "protocol": PROTOCOL}

    def profile(self, url: str) -> dict:
        try:
            pg = self._open(url)
        except PermissionError as e:
            return {"ok": False, "error": str(e)}
        name = re.sub(r"^\(\d+\)\s*", "", pg.title()).split(" | ")[0].strip()
        main = pg.locator("main").first
        txt = main.inner_text(timeout=15000) if main.count() else pg.inner_text("body")
        return {"ok": True, "name": name, "headline": "", "company": "", "about": txt[:2500], "recent": []}

    def _top_card_state(self, pg) -> str:
        top = pg.locator("main").first.inner_text(timeout=15000)[:1500]
        if re.search(r"·\s*1st\b", top):
            return "connected"
        if pg.get_by_role("button", name=re.compile(r"^Pending", re.I)).count():
            return "pending"
        return ""

    def _connect_button(self, pg):
        b = pg.get_by_role("button", name=re.compile(r"^Invite .+ to connect$"))
        if b.count():
            return b.first
        more = pg.locator("main").get_by_role("button", name=re.compile(r"^More( actions)?$"))
        if more.count():
            more.first.click()
            _pause(1, 2)
            for role in ("menuitem", "button"):
                m = pg.get_by_role(role, name=re.compile(r"^Invite .+ to connect$"))
                if m.count():
                    return m.first
            pg.keyboard.press("Escape")
        return None

    def invite(self, url: str, note: str) -> dict:
        try:
            pg = self._open(url)
        except PermissionError as e:
            return {"ok": False, "error": str(e)}
        st = self._top_card_state(pg)
        if st:
            return {"ok": True, "result": st, "detail": "nothing sent"}
        btn = self._connect_button(pg)
        if btn is None:
            return {"ok": True, "result": "unavailable", "detail": "no Connect for this person"}
        btn.click()
        _pause(1.5, 3)
        add = pg.get_by_role("button", name=re.compile(r"^Add a note$", re.I))
        if not add.count():
            pg.keyboard.press("Escape")
            return {"ok": True, "result": "unavailable", "detail": "no 'Add a note' (LinkedIn may want their email)"}
        add.first.click()
        _pause(1, 2)
        box = pg.get_by_role("textbox").last
        box.press_sequentially(note, delay=random.randint(35, 90))
        _pause(1, 2.5)
        if box.input_value().strip() != note.strip():   # never send a note that isn't exactly the approved one
            pg.keyboard.press("Escape")
            return {"ok": False, "error": "the typed note did not match the approved one; nothing sent"}
        pg.get_by_role("button", name=re.compile(r"^Send( invitation| now)?$", re.I)).first.click()
        _pause(2.5, 4)
        return {"ok": True, "result": "sent"}

    def message(self, url: str, text: str) -> dict:
        try:
            pg = self._open(url)
        except PermissionError as e:
            return {"ok": False, "error": str(e)}
        b = pg.locator("main").get_by_role("button", name=re.compile(r"^Message"))
        if not b.count():
            return {"ok": True, "result": "unavailable", "detail": "no Message button"}
        b.first.click()
        _pause(2, 3.5)
        box = pg.get_by_role("textbox", name=re.compile(r"write a message", re.I)).last
        for i, line in enumerate(text.split("\n")):
            if i:
                box.press("Shift+Enter")
            box.press_sequentially(line, delay=random.randint(35, 90))
        _pause(1, 2)
        pg.get_by_role("button", name=re.compile(r"^Send$")).last.click()
        _pause(2, 3)
        return {"ok": True, "result": "sent"}

    def inbox(self, since: str = "") -> dict:
        return {"ok": False, "error": "not in this driver yet: log replies with `soki heard`"}
