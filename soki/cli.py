"""soki: a sales CRM that runs on your own machine, on your own model key.

    soki init                      who you are, what you offer, who you want to meet, your model key
    soki setup [site ...]          get the browser ready and log in to each site yourself (default: linkedin)
    soki config [set <key> <value>]  show the settings, or set one (me.name, audience, caps.invites_per_day, api_key …)
    soki add <url> [--name ...]    put someone in the books (or --csv file.csv: url,name,headline,company,notes)
    soki import <file.json|.csv>   people from another CRM, with what already happened to them (never invited twice)
    soki list [status]             everyone, or everyone at one status
    soki show <who>                one person: their record, every touch, the latest drafts
    soki judge [<who>|--all]       the model scores fit against your audience line
    soki draft [<who>|--next N]    the model writes the connection note; the rules check it
    soki fit <who> <0-10> "<why>"  your own (or your agent's) judgement instead of `judge`
    soki note <who> "<text>"       your own (or your agent's) note instead of `draft`; the rules still check it
    soki approve <who> | skip <who>
    soki send [--n N]              approved people with an approved note, inside every cap, through your browser driver
    soki check <who> [--message]   right before pressing Send by hand: may it go now? (yes + the exact text, or no + why)
    soki sent <who> [--message]    it went out by hand or from your agent's own browser: record it
    soki heard <who> "<text>"      they wrote back: logged, stop words checked, a reply drafted (--no-draft: just log)
    soki reply <who> "<text>"      your own reply instead of the drafted one (approve, then `answer`)
    soki answer <who>              send the approved reply
    soki sync                      (a soki-browser driver) read accepted invites and new replies into the books
    soki mark <who> <status>       connected | replied | meeting | skipped | stopped
    soki today                     what is left under today's caps, and who is waiting on you
    soki doctor                    is the key set, does the model answer, is the browser driver there
    soki mcp                       run as an MCP server (stdio), so Claude or ChatGPT can drive Soki for you
    soki connect [claude|claude-desktop|cursor|codex]   register that MCP server (and skill) with your agent
"""
from __future__ import annotations

import argparse
import csv
import getpass
import json
import sys

from . import books, browser, config, llm, rules, write


def _name(p) -> str:
    return p["name"] or p["id"]


def cmd_init(a) -> None:
    cfg = config.load()

    def ask(label: str, cur: str) -> str:
        v = input(f"{label}{f' [{cur}]' if cur else ''}: ").strip()
        return v or cur

    print("Soki keeps everything in", config.home())
    cfg["me"]["name"] = ask("Your name (you sign notes with the first word)", cfg["me"]["name"])
    cfg["me"]["company"] = ask("Your company", cfg["me"]["company"])
    cfg["me"]["offer"] = ask("What you offer, in one plain line", cfg["me"]["offer"])
    cfg["me"]["proof"] = ask("One fact that makes it believable (optional)", cfg["me"]["proof"])
    cfg["audience"] = ask("Who you want to meet, in one line", cfg["audience"])
    cfg["base_url"] = ask("Model endpoint (OpenAI-compatible)", cfg["base_url"])
    cfg["model"] = ask("Model", cfg["model"])
    print("Saved", config.save(cfg))
    if not config.api_key() or input("Replace the stored model key? [y/N] ").strip().lower() == "y":
        k = getpass.getpass("Model API key (input hidden; blank for a local model): ").strip()
        if k:
            print("Key saved to", config.save_key(k), "(readable by you only)")


def _value(raw: str):
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def cmd_config(a) -> None:
    cfg = config.load()
    if not a.key:
        shown = json.loads(json.dumps(cfg))
        print(json.dumps(shown, indent=2, ensure_ascii=False))
        print("api key:", "set" if config.api_key() else "not set (only needed for judge / draft / heard drafts)")
        return
    if a.key == "api_key":
        print("key saved to", config.save_key(a.value))
        return
    node, parts = cfg, a.key.split(".")
    for k in parts[:-1]:
        if not isinstance(node.get(k), dict):
            raise SystemExit(f"no setting {a.key!r}")
        node = node[k]
    if parts[-1] not in node:
        raise SystemExit(f"no setting {a.key!r} (see `soki config`)")
    v = _value(a.value)
    if isinstance(node[parts[-1]], str) and not isinstance(v, str):
        v = a.value
    node[parts[-1]] = v
    config.save(cfg)
    print(f"{a.key} = {json.dumps(v, ensure_ascii=False)}")


def cmd_import(a) -> None:
    with open(a.file, encoding="utf-8") as f:
        rows = json.load(f) if a.file.endswith(".json") else list(csv.DictReader(f))
    if isinstance(rows, dict):
        rows = rows.get("people") or rows.get("contacts") or []
    print(json.dumps(books.import_rows(rows)))


def cmd_fit(a) -> None:
    p = books.find(a.who)
    if not 0 <= a.score <= 10:
        raise SystemExit("fit is 0 to 10")
    books.update(p["id"], fit=a.score, fit_why=a.why[:300])
    print(f"{_name(p)}: fit {a.score}")


def cmd_note(a) -> None:
    cfg = config.load()
    p = books.find(a.who)
    bad = rules.note_problems(a.text, write.first_name(p), cfg)
    if bad:
        raise SystemExit("not saved, the note breaks the rules:\n- " + "\n- ".join(bad))
    books.save_draft(p["id"], "invite", a.text.strip())
    print(f"{_name(p)}: note saved ({len(a.text.strip())} chars); approve it with `soki approve {p['id']}`")


def cmd_reply(a) -> None:
    p = books.find(a.who)
    books.save_draft(p["id"], "reply", a.text.strip())
    print(f"{_name(p)}: reply saved; `soki approve {p['id']}`, then `soki answer {p['id']}`")


def cmd_check(a) -> None:
    """Right before pressing Send by hand: may this go out now? Exit 1 with the reason when not."""
    cfg = config.load()
    p = books.find(a.who)
    kind = "reply" if a.message else "invite"
    d = books.draft(p["id"], kind)
    if not (d and d["approved"]):
        raise SystemExit(f"no: {_name(p)} has no approved {'reply' if a.message else 'note'}")
    why = books.can_message(p["id"], cfg) if a.message else books.can_invite(p["id"], cfg)
    if not why and not a.message:
        bad = rules.note_problems(d["text"], write.first_name(p), cfg)
        why = "the note breaks the rules now: " + "; ".join(bad) if bad else ""
    if why:
        raise SystemExit(f"no: {why}")
    print(f"yes: send exactly this to {_name(p)}, then `soki sent {p['id']}`\n{d['text']}")


def cmd_sent(a) -> None:
    """It went out (pressed by hand, or by the agent's own browser). A fact is always recorded; a rule it broke is said
    out loud, because the time to stop was `soki check`, before Send."""
    cfg = config.load()
    p = books.find(a.who)
    kind = "reply" if a.message else "invite"
    d = books.draft(p["id"], kind)
    if not (d and d["approved"]):
        raise SystemExit(f"{_name(p)} has no approved {'reply' if a.message else 'note'} to record")
    why = books.can_message(p["id"], cfg) if a.message else books.can_invite(p["id"], cfg)
    books.touch(p["id"], "message" if a.message else "invite", text=d["text"], detail="sent by hand")
    if not a.message:
        books.set_status(p["id"], "invited")
    warn = f"  (WARNING: recorded although it broke a rule: {why}; check before Send next time)" \
        if why and "wait at least" not in why else ""
    print(f"{_name(p)}: {'message sent' if a.message else 'invited'}{warn}")


def cmd_mcp(a) -> None:
    from . import mcp  # noqa: PLC0415
    mcp.serve()


def cmd_connect(a) -> None:
    from . import mcp  # noqa: PLC0415
    print(mcp.connect(a.agent))


def cmd_setup(a) -> None:
    cfg = config.load()
    drv = browser.get(cfg)
    r = drv.setup()
    print("browser ", r.get("detail") or r.get("error"))
    if not r.get("ok"):
        raise SystemExit(1)
    for site in a.sites or ["linkedin"]:
        print(f"{site}: log in in the window that opens (Soki never sees or types your password)…", flush=True)
        r = drv.login(site)
        print(f"{site}: {'ok' if r.get('ok') else 'NOT logged in'}  {json.dumps(r.get('logins') or r.get('detail') or r.get('error'), ensure_ascii=False)}")
    print("status  ", json.dumps(drv.status(), ensure_ascii=False))


def cmd_add(a) -> None:
    rows = []
    if a.csv:
        with open(a.csv, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    if a.url:
        rows.append({"url": a.url, "name": a.name, "headline": a.headline, "company": a.company, "notes": a.notes})
    if not rows:
        raise SystemExit("give a profile URL or --csv")
    new = old = bad = 0
    for r in rows:
        try:
            _, created = books.add(r.get("url", ""), name=r.get("name"), headline=r.get("headline"),
                                   company=r.get("company"), notes=r.get("notes"), about=r.get("about"),
                                   source=a.source or ("csv" if a.csv else "hand"))
        except ValueError as e:
            bad += 1
            print("skipped:", e)
            continue
        new, old = new + created, old + (not created)
    print(f"{new} added, {old} already in the books, {bad} not LinkedIn profiles")


def cmd_list(a) -> None:
    rows = books.people(a.status)
    for p in rows:
        fit = "" if p["fit"] is None else f"fit {p['fit']:>2}  "
        print(f"{p['status']:<10} {fit}{p['id']:<32} {p['name']}  {p['headline'][:50]}")
    print(f"({len(rows)})")


def cmd_show(a) -> None:
    p = books.find(a.who)
    print(json.dumps(dict(p), indent=2, ensure_ascii=False))
    for t in books.touches(p["id"]):
        print(f"{t['ts']}  {t['direction']:<3} {t['action']:<8} {'ok' if t['ok'] else 'no'}  {t['text'][:80]}  "
              f"{t['detail']}")
    for kind in ("invite", "reply"):
        d = books.draft(p["id"], kind)
        if d:
            print(f"\n{kind} draft ({'approved' if d['approved'] else 'not approved'}):\n{d['text']}")


def _targets(a, statuses: tuple[str, ...]) -> list:
    if getattr(a, "who", None):
        return [books.find(a.who)]
    out = [p for s in statuses for p in books.people(s)]
    return out[: a.next] if getattr(a, "next", None) else out


def cmd_judge(a) -> None:
    cfg = config.load()
    todo = _targets(a, ("found",)) if (a.who or a.all) else [p for p in books.people("found") if p["fit"] is None]
    for p in todo:
        j = write.judge(p, cfg)
        books.update(p["id"], fit=j["fit"], fit_why=j["why"])
        print(f"{j['fit']:>2}  {_name(p)}: {j['why']}")


def cmd_draft(a) -> None:
    cfg = config.load()
    todo = _targets(a, ("approved", "found"))
    if not a.who:                                   # named = your call; otherwise only the judged and fit
        todo = [p for p in todo if not books.draft(p["id"], "invite")
                and (p["status"] == "approved" or (p["fit"] is not None and p["fit"] >= cfg["min_fit"]))]
        if not todo:
            print(f"no one to write for: run `soki judge` first (notes go to people with fit >= {cfg['min_fit']})")
    for p in todo:
        note = write.invite_note(p, cfg)
        books.save_draft(p["id"], "invite", note)
        print(f"\n{_name(p)} ({len(note)} chars):\n{note}")


def cmd_approve(a) -> None:
    p = books.find(a.who)
    if books.draft(p["id"], "invite") and p["status"] in ("found", "approved"):
        books.approve_draft(p["id"], "invite")
    if books.draft(p["id"], "reply"):
        books.approve_draft(p["id"], "reply")
    books.set_status(p["id"], "approved") if p["status"] == "found" else None
    print(f"{_name(p)}: approved")


def cmd_skip(a) -> None:
    p = books.find(a.who)
    books.set_status(p["id"], "skipped")
    print(f"{_name(p)}: skipped")


def cmd_send(a) -> None:
    cfg = config.load()
    drv = browser.get(cfg)
    sent = 0
    for p in books.people("approved"):
        if sent >= a.n:
            break
        d = books.draft(p["id"], "invite")
        if not (d and d["approved"]):
            print(f"wait  {_name(p)}: no approved note (`soki draft`, then `soki approve`)")
            continue
        why = books.can_invite(p["id"], cfg)
        if why:
            print(f"stop  {_name(p)}: {why}")
            if "cap" in why or "hours" in why or "wait at least" in why:
                break
            continue
        bad = rules.note_problems(d["text"], write.first_name(p), cfg)      # the rules hold at the last moment too
        if bad:
            print(f"stop  {_name(p)}: the note breaks the rules now: {'; '.join(bad)}")
            continue
        r = drv.invite(p["url"], d["text"])
        ok = r.get("ok") and r.get("result") == "sent"
        books.touch(p["id"], "invite", text=d["text"], ok=bool(ok), detail=r.get("detail") or r.get("error") or
                    r.get("result", ""))
        if ok:
            books.set_status(p["id"], "invited")
            sent += 1
            print(f"sent  {_name(p)}")
        elif r.get("result") == "handed_over":
            sent += 1
            print(f"open  {_name(p)}: {r['detail']}")
        elif r.get("result") == "connected":
            books.set_status(p["id"], "connected")
            print(f"--    {_name(p)}: already connected")
        else:
            print(f"no    {_name(p)}: {r.get('result') or r.get('error')}")
    print(f"{sent} sent. Left: {books.caps_left(cfg)}")


def _thread(pid: str) -> list[dict]:
    return [{"who": "them" if t["direction"] == "in" else "me", "text": t["text"]}
            for t in books.touches(pid) if t["text"] and (t["direction"] == "in" or t["ok"])]


def heard(p, text: str, cfg: dict, draft: bool = True) -> str:
    """One inbound message. A stop phrase stops them for good and nothing is drafted."""
    books.touch(p["id"], "message", direction="in", text=text)
    stop = rules.stop_word(text, cfg)
    if stop:
        books.set_status(p["id"], "stopped")
        return f"stopped: they said '{stop}'. Soki will never contact them again."
    books.set_status(p["id"], "replied")
    if not draft:
        return f"logged; write the answer with `soki reply {p['id']} \"...\"`"
    msg = write.reply(books.get(p["id"]), _thread(p["id"]), cfg)
    books.save_draft(p["id"], "reply", msg)
    return f"reply drafted (`soki approve {p['id']}`, then `soki answer {p['id']}`):\n{msg}"


def cmd_heard(a) -> None:
    print(heard(books.find(a.who), a.text, config.load(), draft=not a.no_draft))


def cmd_answer(a) -> None:
    cfg = config.load()
    p = books.find(a.who)
    d = books.draft(p["id"], "reply")
    if not (d and d["approved"]):
        raise SystemExit(f"{_name(p)} has no approved reply (`soki approve {p['id']}`)")
    why = books.can_message(p["id"], cfg)
    if why:
        raise SystemExit(f"not now: {why}")
    r = browser.get(cfg).message(p["url"], d["text"])
    if r.get("result") == "handed_over":
        print(f"{_name(p)}: {r['detail']} (use --message)")
        return
    ok = bool(r.get("ok") and r.get("result") == "sent")
    books.touch(p["id"], "message", text=d["text"], ok=ok, detail=r.get("detail") or r.get("error") or "")
    print("sent" if ok else f"not sent: {r.get('result') or r.get('error')}")


def cmd_sync(a) -> None:
    cfg = config.load()
    r = browser.get(cfg).inbox()
    if not r.get("ok"):
        raise SystemExit(r.get("error", "inbox failed"))
    for url in r.get("accepted", []):
        try:
            pid = books.person_id(url)
            if books.get(pid)["status"] == "invited":
                books.set_status(pid, "connected")
                print(f"accepted  {pid}")
        except (ValueError, SystemExit):
            continue
    seen = {(t["person_id"], t["text"]) for t in books.touches() if t["direction"] == "in"}
    for th in r.get("threads", []):
        try:
            p = books.get(books.person_id(th["url"]))
        except (ValueError, SystemExit):
            continue                                    # someone not in the books: not ours to answer
        for m in th.get("messages", []):
            if m.get("from") == "them" and (p["id"], m.get("text", "")) not in seen:
                print(f"{_name(p)}: {heard(p, m['text'], cfg)}")


def cmd_mark(a) -> None:
    p = books.find(a.who)
    books.set_status(p["id"], a.status)
    print(f"{_name(p)}: {books.get(p['id'])['status']}")


def cmd_today(a) -> None:
    cfg = config.load()
    print("left today:", json.dumps(books.caps_left(cfg)))
    counts = {s: len(books.people(s)) for s in books.STATUSES}
    print("books:", "  ".join(f"{s} {n}" for s, n in counts.items() if n))
    waiting = [p for p in books.people("replied") if (d := books.draft(p["id"], "reply")) and not d["approved"]]
    for p in waiting:
        print(f"reply waiting for your ok: {_name(p)}")
    no_note = [p for p in books.people("approved") if not books.draft(p["id"], "invite")]
    if no_note:
        print(f"{len(no_note)} approved without a note: `soki draft --next {len(no_note)}`")


def cmd_doctor(a) -> None:
    cfg = config.load()
    print("home     ", config.home())
    print("key      ", "set" if config.api_key() else "MISSING (soki init)")
    print("model    ", cfg["model"], "at", cfg["base_url"])
    try:
        out = llm.ask_json('Reply {"ok": true}', cfg, timeout=60)
        print("answers  ", "yes" if out.get("ok") else out)
    except SystemExit as e:
        print("answers  ", "NO:", e)
    print("browser  ", json.dumps(browser.get(cfg).status()))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="soki", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init").set_defaults(f=cmd_init)
    s = sub.add_parser("config")
    s.add_argument("verb", nargs="?", choices=("set",))
    s.add_argument("key", nargs="?")
    s.add_argument("value", nargs="?")
    s.set_defaults(f=cmd_config)
    s = sub.add_parser("import")
    s.add_argument("file")
    s.set_defaults(f=cmd_import)
    s = sub.add_parser("fit")
    s.add_argument("who")
    s.add_argument("score", type=int)
    s.add_argument("why")
    s.set_defaults(f=cmd_fit)
    for name, f in (("note", cmd_note), ("reply", cmd_reply)):
        s = sub.add_parser(name)
        s.add_argument("who")
        s.add_argument("text")
        s.set_defaults(f=f)
    for name, f in (("check", cmd_check), ("sent", cmd_sent)):
        s = sub.add_parser(name)
        s.add_argument("who")
        s.add_argument("--message", action="store_true", help="a reply (message), not an invite")
        s.set_defaults(f=f)
    sub.add_parser("mcp").set_defaults(f=cmd_mcp)
    s = sub.add_parser("connect")
    s.add_argument("agent", nargs="?", default="claude", choices=("claude", "claude-desktop", "cursor", "codex"))
    s.set_defaults(f=cmd_connect)
    s = sub.add_parser("setup")
    s.add_argument("sites", nargs="*")
    s.set_defaults(f=cmd_setup)
    s = sub.add_parser("add")
    s.add_argument("url", nargs="?")
    for k in ("name", "headline", "company", "notes", "csv", "source"):
        s.add_argument(f"--{k}", default="")
    s.set_defaults(f=cmd_add)
    s = sub.add_parser("list")
    s.add_argument("status", nargs="?", choices=books.STATUSES)
    s.set_defaults(f=cmd_list)
    for name, f in (("show", cmd_show), ("approve", cmd_approve), ("skip", cmd_skip), ("answer", cmd_answer)):
        s = sub.add_parser(name)
        s.add_argument("who")
        s.set_defaults(f=f)
    s = sub.add_parser("judge")
    s.add_argument("who", nargs="?")
    s.add_argument("--all", action="store_true")
    s.set_defaults(f=cmd_judge)
    s = sub.add_parser("draft")
    s.add_argument("who", nargs="?")
    s.add_argument("--next", type=int, default=5)
    s.set_defaults(f=cmd_draft)
    s = sub.add_parser("send")
    s.add_argument("--n", type=int, default=5)
    s.set_defaults(f=cmd_send)
    s = sub.add_parser("heard")
    s.add_argument("who")
    s.add_argument("text")
    s.add_argument("--no-draft", action="store_true")
    s.set_defaults(f=cmd_heard)
    s = sub.add_parser("mark")
    s.add_argument("who")
    s.add_argument("status", choices=("connected", "replied", "meeting", "skipped", "stopped"))
    s.set_defaults(f=cmd_mark)
    for name, f in (("sync", cmd_sync), ("today", cmd_today), ("doctor", cmd_doctor)):
        sub.add_parser(name).set_defaults(f=f)
    a = ap.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main(sys.argv[1:])
