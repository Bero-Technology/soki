"""The books: one SQLite file on the user's machine (SOKI_HOME/books.db). Nobody else holds a copy.

    people   one row per person, keyed by their canonical LinkedIn slug (one person is one record, whatever URL
             spelling came in). status is where they are:
                 found → approved → invited → connected → replied → meeting
                 skipped (you said no) · stopped (they said stop: never contacted again, by anything)
    touches  append only: every invite, message and inbound reply, with when and whether it went out
    drafts   what the model wrote for someone, and whether you approved it

The rules that keep an account safe are answered here, from the records, never from a counter a process could forget:
    can_invite(pid, cfg)   '' or why not: never twice, not stopped/skipped, under today's and this week's caps,
                           inside your hours, and not too soon after the last send
    can_message(pid, cfg)  the same for a message to someone already connected
    import_rows(rows)      people from another CRM or an earlier tool, with what already happened to them. Their old
                           invites count for never-twice but not for this account's caps (channel 'imported')
"""
from __future__ import annotations

import datetime as dt
import re
import sqlite3
import urllib.parse
from contextlib import contextmanager

from . import config

STATUSES = ("found", "approved", "invited", "connected", "replied", "meeting", "skipped", "stopped")
RANK = {s: i for i, s in enumerate(STATUSES[:6])}

SCHEMA = """
create table if not exists people (
    id text primary key, url text not null, name text default '', headline text default '', company text default '',
    about text default '', notes text default '', source text default '', status text not null default 'found',
    fit integer, fit_why text default '', created_at text not null, updated_at text not null);
create table if not exists touches (
    id integer primary key autoincrement, ts text not null, person_id text not null, channel text not null,
    action text not null, direction text not null, text text default '', ok integer not null, detail text default '');
create table if not exists drafts (
    id integer primary key autoincrement, person_id text not null, kind text not null, text text not null,
    approved integer not null default 0, created_at text not null);
create index if not exists touches_person on touches(person_id);
create index if not exists drafts_person on drafts(person_id);
"""


def now() -> dt.datetime:
    return dt.datetime.now().astimezone()


def iso(t: dt.datetime | None = None) -> str:
    return (t or now()).isoformat(timespec="seconds")


@contextmanager
def conn():
    c = sqlite3.connect(config.home() / "books.db")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    try:
        yield c
        c.commit()
    finally:
        c.close()


def person_id(url: str) -> str:
    """linkedin.com/in/<slug> in any spelling (www., country subdomain, trailing slash, query, %-encoding) → slug."""
    u = url.strip()
    if "://" not in u:
        u = "https://" + u
    p = urllib.parse.urlparse(u)
    m = re.match(r"/in/([^/?#]+)", p.path)
    if not (p.netloc.lower().endswith("linkedin.com") and m):
        raise ValueError(f"not a LinkedIn profile URL: {url}")
    return urllib.parse.unquote(m.group(1)).lower()


def canonical_url(pid: str) -> str:
    return f"https://www.linkedin.com/in/{urllib.parse.quote(pid)}/"


def add(url: str, **fields) -> tuple[str, bool]:
    """(id, created). An existing person keeps their status; empty fields are filled, nothing is overwritten."""
    pid = person_id(url)
    cols = ("name", "headline", "company", "about", "notes", "source")
    vals = {k: (fields.get(k) or "").strip() for k in cols}
    with conn() as c:
        row = c.execute("select * from people where id=?", (pid,)).fetchone()
        if row:
            fill = {k: v for k, v in vals.items() if v and not row[k]}
            if fill:
                c.execute(f"update people set {', '.join(f'{k}=?' for k in fill)}, updated_at=? where id=?",
                          (*fill.values(), iso(), pid))
            return pid, False
        c.execute(f"insert into people (id, url, {', '.join(cols)}, status, created_at, updated_at) "
                  f"values (?, ?, {', '.join('?' * len(cols))}, 'found', ?, ?)",
                  (pid, canonical_url(pid), *vals.values(), iso(), iso()))
        return pid, True


def get(pid: str) -> sqlite3.Row:
    with conn() as c:
        row = c.execute("select * from people where id=?", (pid,)).fetchone()
    if not row:
        raise SystemExit(f"no one called {pid!r} in the books (`soki list`)")
    return row


def find(ref: str) -> sqlite3.Row:
    """A person by id, URL, or a unique piece of their name."""
    try:
        return get(person_id(ref) if "linkedin.com" in ref else ref)
    except SystemExit:
        with conn() as c:
            rows = c.execute("select * from people where name like ?", (f"%{ref}%",)).fetchall()
        if len(rows) == 1:
            return rows[0]
        raise SystemExit(f"{ref!r} matches {len(rows)} people; use their id") from None


def people(status: str | None = None) -> list[sqlite3.Row]:
    with conn() as c:
        if status:
            return c.execute("select * from people where status=? order by updated_at", (status,)).fetchall()
        return c.execute("select * from people order by updated_at").fetchall()


def update(pid: str, **fields) -> None:
    if "status" in fields and fields["status"] not in STATUSES:
        raise ValueError(f"unknown status {fields['status']!r}")
    with conn() as c:
        c.execute(f"update people set {', '.join(f'{k}=?' for k in fields)}, updated_at=? where id=?",
                  (*fields.values(), iso(), pid))


def set_status(pid: str, status: str) -> None:
    """Moves forward only (a late 'connected' never undoes a 'replied'); skipped and stopped always win, and stopped
    is final."""
    cur = get(pid)["status"]
    if cur == "stopped":
        return
    if status in ("skipped", "stopped") or cur == "skipped" or RANK.get(status, -1) > RANK.get(cur, -1):
        update(pid, status=status)


def touch(pid: str, action: str, *, direction: str = "out", text: str = "", ok: bool = True, detail: str = "",
          channel: str = "linkedin", ts: str = "") -> None:
    with conn() as c:
        c.execute("insert into touches (ts, person_id, channel, action, direction, text, ok, detail) "
                  "values (?, ?, ?, ?, ?, ?, ?, ?)", (ts or iso(), pid, channel, action, direction, text, int(ok), detail))


def touches(pid: str | None = None) -> list[sqlite3.Row]:
    with conn() as c:
        if pid:
            return c.execute("select * from touches where person_id=? order by id", (pid,)).fetchall()
        return c.execute("select * from touches order by id").fetchall()


def save_draft(pid: str, kind: str, text: str) -> int:
    with conn() as c:
        return c.execute("insert into drafts (person_id, kind, text, created_at) values (?, ?, ?, ?)",
                         (pid, kind, text, iso())).lastrowid


def draft(pid: str, kind: str = "invite") -> sqlite3.Row | None:
    with conn() as c:
        return c.execute("select * from drafts where person_id=? and kind=? order by id desc limit 1",
                         (pid, kind)).fetchone()


def approve_draft(pid: str, kind: str = "invite") -> None:
    d = draft(pid, kind)
    if not d:
        raise SystemExit(f"{pid} has no {kind} draft yet (`soki draft {pid}`)")
    with conn() as c:
        c.execute("update drafts set approved=1 where id=?", (d["id"],))


def _sent(action: str, since: dt.datetime) -> int:
    with conn() as c:
        return c.execute("select count(*) from touches where action=? and direction='out' and ok=1 and ts>=? "
                         "and channel='linkedin'", (action, iso(since))).fetchone()[0]


def _last_send() -> dt.datetime | None:
    with conn() as c:
        r = c.execute("select ts from touches where direction='out' and ok=1 and channel='linkedin' "
                      "order by id desc limit 1").fetchone()
    return dt.datetime.fromisoformat(r[0]) if r else None


def _day_start(t: dt.datetime) -> dt.datetime:
    return t.replace(hour=0, minute=0, second=0, microsecond=0)


CHROMIUM_CAPS = {"invites_per_day": 3, "invites_per_week": 15, "messages_per_day": 5}


def effective_caps(cfg: dict) -> dict:
    """A plain automated Chromium is easy for a site to spot, so with it the caps are held low whatever config says."""
    caps = dict(cfg["caps"])
    if (cfg.get("browser") or "") == "chromium":
        for k, v in CHROMIUM_CAPS.items():
            caps[k] = min(caps[k], v)
    return caps


def caps_left(cfg: dict, t: dt.datetime | None = None) -> dict:
    t = t or now()
    caps = effective_caps(cfg)
    day, week = _day_start(t), _day_start(t) - dt.timedelta(days=6)
    return {"invites_today": caps["invites_per_day"] - _sent("invite", day),
            "invites_week": caps["invites_per_week"] - _sent("invite", week),
            "messages_today": caps["messages_per_day"] - _sent("message", day)}


def _pace(cfg: dict, t: dt.datetime) -> str:
    a, b = cfg["hours"]
    if not a <= t.hour < b:
        return f"outside your hours ({a}:00 to {b}:00)"
    last = _last_send()
    gap = effective_caps(cfg)["min_gap_seconds"]
    if last and (t - last).total_seconds() < gap:
        return f"the last send was {int((t - last).total_seconds())}s ago; wait at least {gap}s between sends"
    return ""


def can_invite(pid: str, cfg: dict, t: dt.datetime | None = None) -> str:
    t = t or now()
    p = get(pid)
    if p["status"] in ("stopped", "skipped"):
        return f"{p['status']}"
    if any(x["action"] == "invite" and x["direction"] == "out" and x["ok"] for x in touches(pid)):
        return "already invited once (never twice)"
    if RANK.get(p["status"], 0) >= RANK["invited"]:
        return f"already {p['status']}"
    left = caps_left(cfg, t)
    if left["invites_today"] <= 0:
        return "today's invite cap is used up"
    if left["invites_week"] <= 0:
        return "this week's invite cap is used up"
    return _pace(cfg, t)


def can_message(pid: str, cfg: dict, t: dt.datetime | None = None) -> str:
    t = t or now()
    p = get(pid)
    if p["status"] == "stopped":
        return "stopped (they asked not to be contacted)"
    if RANK.get(p["status"], 0) < RANK["connected"]:
        return f"not connected yet ({p['status']})"
    if caps_left(cfg, t)["messages_today"] <= 0:
        return "today's message cap is used up"
    return _pace(cfg, t)


IMPORT_STATUS = {"found": "found", "new": "found", "approved": "approved", "queued": "approved", "invited": "invited",
                 "pending": "invited", "contacted": "invited", "connected": "connected", "accepted": "connected",
                 "replied": "replied", "engaged": "replied", "meeting": "meeting", "booked": "meeting",
                 "skipped": "skipped", "rejected": "skipped", "aborted": "skipped", "dead": "skipped",
                 "stopped": "stopped", "do_not_contact": "stopped", "unsubscribed": "stopped"}
FIT_WORDS = {"high": 8, "medium": 6, "low": 3}


def import_rows(rows: list[dict]) -> dict:
    """Each row: url (a LinkedIn profile) and any of name, headline, company, about, notes, source, status, fit
    (0-10 or high/medium/low), why, note (the invite note sent), invited_at, messages ([{direction: in|out, text, ts}]).
    Safe to run again: a person already here keeps their record; only what is missing is added."""
    n = {"added": 0, "updated": 0, "skipped": 0}
    for r in rows:
        url = (r.get("url") or r.get("linkedin_url") or "").strip()
        try:
            pid, created = add(url, **{k: r.get(k) for k in ("name", "headline", "company", "about", "notes",
                                                               "source")})
        except ValueError:
            n["skipped"] += 1
            continue
        n["added" if created else "updated"] += 1
        fit = r.get("fit")
        fit = FIT_WORDS.get(str(fit).lower(), fit) if fit is not None else None
        if isinstance(fit, (int, float)) and 0 <= fit <= 10 and get(pid)["fit"] is None:
            update(pid, fit=int(fit), fit_why=str(r.get("why") or "")[:300])
        old = {(t["action"], t["direction"], t["text"]) for t in touches(pid)}
        sent_invite = r.get("invited_at") or (r.get("note") and IMPORT_STATUS.get(str(r.get("status"))) in
                                              ("invited", "connected", "replied", "meeting"))
        if sent_invite and not any(a == "invite" for a, _, _ in old):
            touch(pid, "invite", text=r.get("note") or "", channel="imported", detail="imported",
                  ts=str(r.get("invited_at") or ""))
        for m in r.get("messages") or []:
            d = "in" if m.get("direction") in ("in", "them") else "out"
            if m.get("text") and ("message", d, m["text"]) not in old:
                touch(pid, "message", direction=d, text=m["text"], channel="imported", detail="imported",
                      ts=str(m.get("ts") or ""))
        st = IMPORT_STATUS.get(str(r.get("status") or "").lower())
        if st:
            set_status(pid, st)
    return n
