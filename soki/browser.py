"""How Soki reaches LinkedIn. Drivers, one contract (docs/BROWSER.md). config "browser":

    auto          (default) agent when an agent drives Soki (soki mcp), manual in a terminal
    agent         the person's own agent sends from its own browser; Soki keeps the books and says yes or no first
    chromium      optional: Soki drives a plain Chromium with Playwright. Easy for a site to spot as automation, so its
                  caps are held low in code (books.CHROMIUM_CAPS)

    manual        free and open: Soki opens the profile in your own browser, puts the note on your clipboard, and you
                  press Connect and Send yourself. You confirm, Soki records it. Nothing is automated.
    <a path>      any executable that speaks the soki-browser protocol: `<exe> <command> [args]` prints one JSON object.
                  You can write your own.

Soki decides (books.can_invite / can_message) BEFORE it calls a driver. A driver only does what it is told, once.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import webbrowser

PROTOCOL = 1
LOGIN_URLS = {"linkedin": "https://www.linkedin.com/login", "xiaohongshu": "https://www.xiaohongshu.com/explore",
              "rednote": "https://www.rednote.com/explore", "instagram": "https://www.instagram.com/accounts/login/",
              "x": "https://x.com/i/flow/login", "tiktok": "https://www.tiktok.com/login"}


class Driver:
    name = "?"

    def status(self) -> dict: ...
    def setup(self) -> dict: ...
    def login(self, site: str) -> dict: ...
    def profile(self, url: str) -> dict: ...
    def invite(self, url: str, note: str) -> dict: ...
    def message(self, url: str, text: str) -> dict: ...
    def inbox(self, since: str = "") -> dict: ...


def _ask(q: str) -> bool:
    try:
        return input(q + " [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _clip(text: str) -> bool:
    for cmd in (["pbcopy"], ["wl-copy"], ["xclip", "-selection", "clipboard"], ["clip"]):
        if shutil.which(cmd[0]):
            subprocess.run(cmd, input=text.encode(), check=False)
            return True
    return False


class Manual(Driver):
    """You are the browser. Honest by design: Soki records a send only when you say it went."""
    name = "manual"

    def status(self) -> dict:
        return {"ok": True, "driver": "manual", "logged_in": None, "protocol": PROTOCOL}

    def setup(self) -> dict:
        return {"ok": True, "detail": "the manual driver uses your own browser: nothing to set up"}

    def login(self, site: str) -> dict:
        url = LOGIN_URLS.get(site)
        if not url:
            return {"ok": False, "error": f"unknown site {site!r} (one of {', '.join(LOGIN_URLS)})"}
        webbrowser.open(url)
        return {"ok": True, "site": site, "detail": "opened in your own browser; log in there"}

    def profile(self, url: str) -> dict:
        return {"ok": False, "error": "the manual driver cannot read profiles; add name/headline with `soki add`"}

    def _hand_over(self, url: str, text: str, what: str) -> dict:
        copied = _clip(text)
        webbrowser.open(url)
        if os.environ.get("SOKI_AGENT"):        # an agent is driving: stdin is not a person, so never ask there
            return {"ok": True, "result": "handed_over",
                    "detail": f"opened their profile{' and copied the text' if copied else ''}; the person presses "
                              f"Send, then record it with `soki sent <who>`"}
        print(f"\n--- {what} ---\n{text}\n---")
        print("Copied to your clipboard." if copied else "Copy the text above.")
        if _ask(f"Opened {url}\nDid you send it?"):
            return {"ok": True, "result": "sent", "detail": "confirmed by you"}
        return {"ok": True, "result": "not_sent", "detail": "you did not confirm"}

    def invite(self, url: str, note: str) -> dict:
        return self._hand_over(url, note, "connection note (press Connect, then Add a note)")

    def message(self, url: str, text: str) -> dict:
        return self._hand_over(url, text, "message")

    def inbox(self, since: str = "") -> dict:
        return {"ok": False, "error": "the manual driver cannot read your inbox; log replies with `soki heard`"}


class External(Driver):
    def __init__(self, exe: str):
        self.exe = shutil.which(exe) or exe
        self.name = exe

    def _run(self, *args: str, timeout: int = 300) -> dict:
        try:
            r = subprocess.run([self.exe, *args], capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            raise SystemExit(f"browser driver not found: {self.exe}") from None
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"{args[0]} took longer than {timeout}s"}
        try:
            out = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
        except (json.JSONDecodeError, IndexError):
            out = {}
        if not isinstance(out, dict) or "ok" not in out:
            return {"ok": False, "error": f"driver gave no JSON (exit {r.returncode}): "
                                          f"{(r.stderr or r.stdout).strip()[-300:]}"}
        return out

    def _with_file(self, cmd: str, url: str, flag: str, text: str) -> dict:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=True) as f:
            f.write(text)
            f.flush()
            return self._run(cmd, url, flag, f.name)

    def status(self) -> dict:
        return self._run("status", timeout=120)

    def setup(self) -> dict:
        return self._run("setup", timeout=120)

    def login(self, site: str) -> dict:
        return self._run("login", site, timeout=900)          # waits for you to log in (up to 10 minutes)

    def profile(self, url: str) -> dict:
        return self._run("profile", url)

    def invite(self, url: str, note: str) -> dict:
        return self._with_file("invite", url, "--note-file", note)

    def message(self, url: str, text: str) -> dict:
        return self._with_file("message", url, "--text-file", text)

    def inbox(self, since: str = "") -> dict:
        return self._run("inbox", *(["--since", since] if since else []), timeout=900)


class Agent(Driver):
    """The person's own agent sends from its own browser (Claude in Chrome, ChatGPT's agent mode, …), in the person's
    everyday Chrome with their own login. Soki opens nothing: `send` lists who is cleared to go, the agent sends each
    one by hand, asking `soki check <who>` right before Send and `soki sent <who>` right after."""
    name = "agent"

    def status(self) -> dict:
        return {"ok": True, "driver": "agent", "logged_in": None, "protocol": PROTOCOL,
                "detail": "your agent uses its own browser"}

    def setup(self) -> dict:
        return {"ok": True, "detail": "your agent uses its own browser: nothing to set up"}

    def login(self, site: str) -> dict:
        url = LOGIN_URLS.get(site)
        if not url:
            return {"ok": False, "error": f"unknown site {site!r} (one of {', '.join(LOGIN_URLS)})"}
        return {"ok": True, "site": site, "detail": f"open {url} in your own browser and log in there"}

    def profile(self, url: str) -> dict:
        return {"ok": False, "error": "read the profile in your own browser, then `soki add` what you saw"}

    def _todo(self, what: str) -> dict:
        return {"ok": True, "result": "handed_over",
                "detail": f"send it from your own browser ({what}), checking `soki check <who>` just before Send "
                          "and recording it with `soki sent <who>` right after"}

    def invite(self, url: str, note: str) -> dict:
        return self._todo("Connect, Add a note, the approved note word for word")

    def message(self, url: str, text: str) -> dict:
        return self._todo("Message, the approved text word for word")

    def inbox(self, since: str = "") -> dict:
        return {"ok": False, "error": "read the inbox in your own browser; log each reply with `soki heard`"}


def get(cfg: dict) -> Driver:
    b = (cfg.get("browser") or "auto").strip()
    if b == "auto":
        b = "agent" if os.environ.get("SOKI_AGENT") else "manual"
    if b == "agent":
        return Agent()
    if b == "manual":
        return Manual()
    if b == "chromium":
        from .chromium import Chromium  # noqa: PLC0415  (optional: pip install 'soki[chromium]')
        return Chromium()
    return External(b)
