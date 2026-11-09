import datetime as dt
import json
import os
import stat
import sys

import pytest

from soki import books, browser, cli, config, llm, rules, write


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SOKI_HOME", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = config.load()
    cfg["me"].update(name="Ada Lin", company="Acme Help", offer="a tool that turns your docs into a help bot")
    cfg["audience"] = "founders of B2B SaaS with a support team"
    config.save(cfg)
    return tmp_path


NOON = dt.datetime(2026, 11, 9, 12, 0).astimezone()


# --- books ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("url", ["https://www.linkedin.com/in/Jane-Doe/", "linkedin.com/in/jane-doe",
                                 "https://uk.linkedin.com/in/jane-doe?trk=x", "https://www.linkedin.com/in/jane%2Ddoe"])
def test_one_person_whatever_the_spelling(url):
    assert books.person_id(url) == "jane-doe"


def test_not_a_profile():
    with pytest.raises(ValueError):
        books.person_id("https://www.linkedin.com/company/acme/")


def test_add_fills_but_never_overwrites():
    pid, new = books.add("linkedin.com/in/jane", name="Jane")
    assert new
    books.set_status(pid, "invited")
    _, new = books.add("https://www.linkedin.com/in/jane/", name="Other", headline="CEO")
    p = books.get(pid)
    assert not new and p["name"] == "Jane" and p["headline"] == "CEO" and p["status"] == "invited"


def test_status_moves_forward_and_stopped_is_final():
    pid, _ = books.add("linkedin.com/in/a")
    books.set_status(pid, "replied")
    books.set_status(pid, "connected")
    assert books.get(pid)["status"] == "replied"
    books.set_status(pid, "stopped")
    books.set_status(pid, "meeting")
    assert books.get(pid)["status"] == "stopped"


def test_never_twice():
    cfg = config.load()
    pid, _ = books.add("linkedin.com/in/a")
    assert books.can_invite(pid, cfg, NOON) == ""
    books.touch(pid, "invite", ok=True)
    books.update(pid, status="found")             # even if the status were wrong, the record says invited
    assert "never twice" in books.can_invite(pid, cfg, NOON)


def test_a_failed_invite_does_not_count():
    cfg = config.load()
    pid, _ = books.add("linkedin.com/in/a")
    books.touch(pid, "invite", ok=False)
    assert books.can_invite(pid, cfg, NOON + dt.timedelta(hours=1)) == ""


def test_daily_cap(monkeypatch):
    cfg = config.load()
    cfg["caps"].update(invites_per_day=2, min_gap_seconds=0)
    for i in range(2):
        pid, _ = books.add(f"linkedin.com/in/p{i}")
        books.touch(pid, "invite")
    pid, _ = books.add("linkedin.com/in/next")
    assert "today's invite cap" in books.can_invite(pid, cfg)


def test_hours_and_gap():
    cfg = config.load()
    pid, _ = books.add("linkedin.com/in/a")
    assert "outside your hours" in books.can_invite(pid, cfg, NOON.replace(hour=23))
    other, _ = books.add("linkedin.com/in/b")
    books.touch(other, "invite")
    cfg["hours"] = [0, 24]                         # the gap, whatever time of day the test runs
    assert "wait at least" in books.can_invite(pid, cfg)


def test_message_needs_a_connection():
    cfg = config.load()
    pid, _ = books.add("linkedin.com/in/a")
    assert "not connected" in books.can_message(pid, cfg, NOON)
    books.set_status(pid, "connected")
    assert books.can_message(pid, cfg, NOON) == ""


# --- config --------------------------------------------------------------------------------------------------------

def test_a_reckless_cap_is_refused():
    cfg = config.load()
    cfg["caps"]["invites_per_day"] = 100
    with pytest.raises(SystemExit):
        config.save(cfg)


def test_key_file_is_private(home):
    f = config.save_key("sk-test")
    assert config.api_key() == "sk-test"
    assert stat.S_IMODE(os.stat(f).st_mode) == 0o600


# --- rules ---------------------------------------------------------------------------------------------------------

GOOD = "Hi Jane, your post on cutting support tickets by half stuck with me. I build Acme Help, it turns docs into a help bot. Ada"


def test_a_good_note_passes():
    assert rules.note_problems(GOOD, "Jane", config.load()) == []


@pytest.mark.parametrize("note,why", [
    ("Hi Jane, I'm Ada from Acme Help and we make help bots. Ada", "open with something specific"),
    (GOOD.replace("stuck with me", "stuck with me — really"), "no dashes"),
    (GOOD.replace("turns", "seamlessly turns").replace("help bot", "help bot solution"), "template words"),
    (GOOD.replace(" Ada", ""), "sign it"),
    ("Hi Jane, " + "x" * 300 + " Ada", "at most 300"),
    (GOOD.replace("Hi Jane", "Hi there"), "first name"),
])
def test_bad_notes(note, why):
    assert any(why in b for b in rules.note_problems(note, "Jane", config.load()))


def test_must_and_never_say():
    cfg = config.load()
    cfg["must_say"], cfg["never_say"] = ["free trial"], ["Acme Help"]
    bad = rules.note_problems(GOOD, "Jane", cfg)
    assert any("must say 'free trial'" in b for b in bad) and any("must not say 'Acme Help'" in b for b in bad)


def test_stop_words():
    assert rules.stop_word("Please remove me from your list") == "remove me"
    assert rules.stop_word("Thanks, sounds great") == ""
    assert rules.stop_word("bitte nicht", {"stop_words": ["bitte nicht"]}) == "bitte nicht"


# --- the model -----------------------------------------------------------------------------------------------------

def test_first_json():
    assert llm.first_json('sure:\n```json\n{"a": 1}\n```') == {"a": 1}
    assert llm.first_json('[{"a": 1}]') == [{"a": 1}]


def test_note_is_rewritten_until_it_passes(monkeypatch):
    replies = iter([{"note": "Hi Jane, I'm Ada. Ada"}, {"note": GOOD}])
    prompts = []
    monkeypatch.setattr(llm, "ask_json", lambda p, cfg, **kw: prompts.append(p) or next(replies))
    pid, _ = books.add("linkedin.com/in/jane", name="Jane Doe")
    assert write.invite_note(books.get(pid), config.load()) == GOOD
    assert "open with something specific" in prompts[1]


def test_draft_next_skips_the_unjudged_and_the_unfit(monkeypatch):
    monkeypatch.setattr(llm, "ask_json", lambda p, cfg, **kw: {"note": GOOD})
    fit, _ = books.add("linkedin.com/in/jane", name="Jane Doe")
    unfit, _ = books.add("linkedin.com/in/tom", name="Jane Tom")
    unjudged, _ = books.add("linkedin.com/in/x", name="Jane X")
    books.update(fit, fit=8)
    books.update(unfit, fit=2)
    cli.main(["draft"])
    assert books.draft(fit) and not books.draft(unfit) and not books.draft(unjudged)


def test_a_note_that_never_passes_is_not_saved(monkeypatch):
    monkeypatch.setattr(llm, "ask_json", lambda p, cfg, **kw: {"note": "Hi Jane, I'm Ada. Ada"})
    pid, _ = books.add("linkedin.com/in/jane", name="Jane Doe")
    with pytest.raises(SystemExit):
        cli.main(["draft", pid])
    assert books.draft(pid) is None


# --- the whole loop, with a fake browser driver ----------------------------------------------------------------------

def fake_driver(tmp_path, result="sent"):
    log = tmp_path / "driver.log"
    exe = tmp_path / "fake-browser"
    exe.write_text(f"""#!{sys.executable}
import json, sys
open({str(log)!r}, "a").write(" ".join(sys.argv[1:]) + "\\n")
cmd = sys.argv[1]
if cmd == "status":
    print(json.dumps({{"ok": True, "logged_in": True, "protocol": 1}}))
elif cmd == "inbox":
    print(json.dumps({{"ok": True, "accepted": ["https://www.linkedin.com/in/jane/"],
        "threads": [{{"url": "https://www.linkedin.com/in/jane/", "messages": [{{"from": "them", "text": "please remove me"}}]}}]}}))
else:
    print(json.dumps({{"ok": True, "result": {result!r}}}))
""")
    exe.chmod(0o755)
    cfg = config.load()
    cfg["browser"] = str(exe)
    cfg["caps"]["min_gap_seconds"] = 0
    cfg["hours"] = [0, 24]
    config.save(cfg)
    return log


def test_send_then_sync_then_stop(tmp_path, monkeypatch, capsys):
    log = fake_driver(tmp_path)
    monkeypatch.setattr(llm, "ask_json", lambda p, cfg, **kw: {"note": GOOD})
    pid, _ = books.add("linkedin.com/in/jane", name="Jane Doe")
    cli.main(["draft", pid])
    cli.main(["send"])
    assert books.get(pid)["status"] == "found"                  # not approved: nothing goes
    cli.main(["approve", pid])
    cli.main(["send"])
    assert books.get(pid)["status"] == "invited"
    assert "invite https://www.linkedin.com/in/jane/ --note-file" in log.read_text()
    cli.main(["send"])
    assert log.read_text().count("invite ") == 1                # never twice
    cli.main(["sync"])                                           # accepted, then "please remove me"
    assert books.get(pid)["status"] == "stopped"
    assert books.draft(pid, "reply") is None


def test_heard_drafts_a_reply(monkeypatch):
    monkeypatch.setattr(llm, "ask_json", lambda p, cfg, **kw: {"message": "Glad it helps. Want a demo link?"})
    pid, _ = books.add("linkedin.com/in/jane", name="Jane Doe")
    books.set_status(pid, "connected")
    cli.main(["heard", pid, "Interesting, how does it work?"])
    assert books.get(pid)["status"] == "replied"
    assert books.draft(pid, "reply")["text"].startswith("Glad")


def test_driver_garbage_is_a_failure_not_a_send(tmp_path):
    exe = tmp_path / "bad"
    exe.write_text("#!/bin/sh\necho clicked\n")
    exe.chmod(0o755)
    r = browser.External(str(exe)).invite("https://www.linkedin.com/in/x/", "hi")
    assert r["ok"] is False


def test_setup_logs_in_each_site(tmp_path, capsys):
    log = fake_driver(tmp_path)
    cli.main(["setup", "linkedin", "xiaohongshu"])
    calls = log.read_text().splitlines()
    assert calls[:3] == ["setup", "login linkedin", "login xiaohongshu"]


def test_manual_login_knows_the_sites():
    assert browser.Manual().login("nowhere")["ok"] is False


# --- agent mode: config, import, the agent's own notes, MCP --------------------------------------------------------

def test_config_set():
    cli.main(["config", "set", "me.offer", "help bots"])
    cli.main(["config", "set", "caps.invites_per_day", "5"])
    cli.main(["config", "set", "must_say", '["AI"]'])
    c = config.load()
    assert c["me"]["offer"] == "help bots" and c["caps"]["invites_per_day"] == 5 and c["must_say"] == ["AI"]
    with pytest.raises(SystemExit):
        cli.main(["config", "set", "caps.invites_per_day", "90"])
    with pytest.raises(SystemExit):
        cli.main(["config", "set", "nonsense", "1"])


def test_import_keeps_history_and_never_twice(tmp_path):
    f = tmp_path / "crm.json"
    f.write_text(json.dumps([
        {"url": "https://www.linkedin.com/in/old-lead/", "name": "Old Lead", "status": "invited", "fit": "high",
         "why": "runs ads", "note": "Hi Old, ...", "invited_at": "2026-11-08T09:00:00+00:00"},
        {"url": "https://www.linkedin.com/in/talked/", "name": "Talked", "status": "replied",
         "messages": [{"direction": "in", "text": "sounds good"}]},
        {"url": "https://example.com/x"}]))
    cli.main(["import", str(f)])
    cli.main(["import", str(f)])                                  # twice: nothing doubles
    cfg = config.load()
    assert books.get("old-lead")["status"] == "invited" and books.get("old-lead")["fit"] == 8
    assert len(books.touches("old-lead")) == 1 and len(books.touches("talked")) == 1
    assert "never twice" in books.can_invite("old-lead", cfg, NOON) or "already" in books.can_invite("old-lead", cfg, NOON)
    assert books.caps_left(cfg)["invites_today"] == cfg["caps"]["invites_per_day"]     # imported ≠ this account's sends


def test_agent_note_is_checked():
    pid, _ = books.add("linkedin.com/in/jane", name="Jane Doe")
    with pytest.raises(SystemExit) as e:
        cli.main(["note", pid, "Hi Jane, I'm Ada — we make bots. Ada"])
    assert "no dashes" in str(e.value.code) and books.draft(pid) is None
    cli.main(["note", pid, GOOD])
    assert books.draft(pid)["text"] == GOOD


def test_manual_send_in_agent_mode_never_reads_stdin(monkeypatch):
    monkeypatch.setenv("SOKI_AGENT", "1")
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("asked stdin"))
    monkeypatch.setattr(browser.webbrowser, "open", lambda u: True)
    monkeypatch.setattr(browser, "_clip", lambda t: True)
    cfg = config.load()
    cfg["hours"], cfg["caps"]["min_gap_seconds"] = [0, 24], 0
    config.save(cfg)
    pid, _ = books.add("linkedin.com/in/jane", name="Jane Doe")
    cli.main(["note", pid, GOOD])
    cli.main(["approve", pid])
    cli.main(["send"])
    assert books.get(pid)["status"] == "approved"                 # handed over, not yet sent
    cli.main(["sent", pid])
    assert books.get(pid)["status"] == "invited"
    assert "never twice" in books.can_invite(pid, config.load())


def test_mcp_round_trip():
    from soki import mcp
    init = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
    assert init["result"]["serverInfo"]["name"] == "soki"
    names = {t["name"] for t in mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]}
    assert {"configure", "add", "fit", "note", "approve", "send", "heard", "reply", "guide"} <= names
    assert mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None

    def tool(tool_name, **args):
        r = mcp.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                        "params": {"name": tool_name, "arguments": args}})
        return r["result"]["content"][0]["text"], r["result"]["isError"]

    assert tool("configure", key="me.name", value="Ada Lin") == ("me.name = \"Ada Lin\"", False)
    assert "1 added" in tool("add", url="https://www.linkedin.com/in/jane/", name="Jane Doe")[0]
    text, err = tool("note", who="jane", text="Hi Jane, we sell things. Ada")
    assert err and "open with something specific" in text
    assert tool("note", who="jane", text=GOOD)[1] is False
    assert "Running Soki" in tool("guide")[0]
    assert tool("show", who="nobody-here")[1] is True


def test_connect_json_app_merges_and_backs_up(tmp_path, monkeypatch):
    from soki import mcp
    f = tmp_path / "claude_desktop_config.json"
    f.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}))
    monkeypatch.setitem(mcp.JSON_APPS, "claude-desktop", lambda: f)
    mcp.connect("claude-desktop")
    d = json.loads(f.read_text())
    assert d["theme"] == "dark" and "other" in d["mcpServers"] and d["mcpServers"]["soki"]["args"][-1] == "mcp"
    assert (tmp_path / "claude_desktop_config.json.bak-soki").is_file()


def test_agent_driver_check_then_sent(monkeypatch):
    monkeypatch.setenv("SOKI_AGENT", "1")
    monkeypatch.setattr(browser.webbrowser, "open", lambda u: pytest.fail("the agent driver must not open anything"))
    cfg = config.load()
    cfg["hours"], cfg["caps"]["min_gap_seconds"] = [0, 24], 0
    config.save(cfg)
    assert isinstance(browser.get(config.load()), browser.Agent)
    pid, _ = books.add("linkedin.com/in/jane", name="Jane Doe")
    with pytest.raises(SystemExit) as e:
        cli.main(["check", pid])
    assert "no approved" in str(e.value.code)
    cli.main(["note", pid, GOOD])
    cli.main(["approve", pid])
    cli.main(["send"])
    assert books.get(pid)["status"] == "approved"
    cli.main(["check", pid])
    cli.main(["sent", pid])
    assert books.get(pid)["status"] == "invited"
    with pytest.raises(SystemExit) as e:
        cli.main(["check", pid])
    assert "never twice" in str(e.value.code)


def test_sent_records_a_fact_even_past_a_cap(capsys):
    cfg = config.load()
    cfg["hours"], cfg["caps"]["min_gap_seconds"], cfg["caps"]["invites_per_day"] = [0, 24], 0, 1
    config.save(cfg)
    for n in ("a", "b"):
        pid, _ = books.add(f"linkedin.com/in/{n}", name="Jane " + n)
        cli.main(["note", pid, GOOD])
        cli.main(["approve", pid])
        cli.main(["sent", pid])
    assert books.get("b")["status"] == "invited"
    assert "WARNING" in capsys.readouterr().out


def test_chromium_caps_are_held_low():
    cfg = config.load()
    cfg["browser"] = "chromium"
    assert books.caps_left(cfg)["invites_today"] == books.CHROMIUM_CAPS["invites_per_day"]
