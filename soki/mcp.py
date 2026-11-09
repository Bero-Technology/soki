"""Soki as an MCP server, so the person's own agent (Claude Code, Claude Desktop, Codex, any MCP client) runs Soki
for them, and the person never types a command.

    soki mcp                 stdio JSON-RPC (one message per line). Every tool is a `soki` CLI command run in-process
                             with its output captured, so the agent and the terminal share one code path, one set of
                             books and the same brakes. Nothing here can send past the caps: `send` is `soki send`.
    soki connect claude      `claude mcp add` (user scope) + the skill in ~/.claude/skills/soki
    soki connect codex       an [mcp_servers.soki] block in ~/.codex/config.toml + the skill in ~/.codex/skills/soki
    soki connect claude-desktop | cursor    a "soki" entry in that app's mcpServers JSON (the file is backed up first)

The agent can be the model: it judges fit (`fit`) and writes notes (`note`) and replies (`reply`) itself, on the
person's own subscription, and Soki's rules still check every word. Then no API key is needed at all.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__

SKILL = Path(__file__).parent / "skill" / "SKILL.md"

INSTRUCTIONS = """Soki is the person's sales CRM, on their own machine. You run it for them; they never type commands.
Read the guide once (tool `guide`) before the first setup or campaign. In short:
- Set up by asking them in plain words, then `configure`. They log in to sites themselves (`login`); never ask for a
  password.
- You judge fit (`fit`) and write each note (`note`) yourself. Soki's rules check every note; fix what they list.
- Show the person each note and send only what they approved (`approve`, then `send`). The caps, hours and
  never-twice are enforced by Soki; never try to get around a refusal, report it.
- Anyone who says stop is stopped for good by Soki; never contact them again by any route."""


def _p(**props) -> dict:
    req = [k for k, v in props.items() if not v.pop("optional", False)]
    return {"type": "object", "properties": props, "required": req}


S = {"type": "string"}
WHO = {"type": "string", "description": "the person: their id (LinkedIn slug), profile URL, or a unique part of their name"}

TOOLS = [
    ("guide", "How to run Soki for the person: setup, a campaign, the daily loop, replies. Read it first.", _p(),
     lambda a: None),
    ("today", "Where things stand: caps left today, how many people at each status, what waits on the person.", _p(),
     lambda a: ["today"]),
    ("settings", "Show every setting (who they are, offer, audience, must/never say, caps, hours, model, browser).",
     _p(), lambda a: ["config"]),
    ("configure", "Set one setting. key examples: me.name, me.company, me.offer, me.proof, audience, must_say, "
                  "never_say, caps.invites_per_day, caps.invites_per_week, hours, min_fit, model, base_url, browser, "
                  "api_key. value: text, or JSON for lists/numbers (e.g. [\"AI\"], 8, [9,19]).",
     _p(key=S, value=S), lambda a: ["config", "set", a["key"], a["value"]]),
    ("setup", "Get the browser ready and open each site's login page for the PERSON to log in (waits up to 10 min "
              "per site). Sites: linkedin, xiaohongshu, rednote, instagram, x, tiktok.",
     _p(sites={"type": "array", "items": S, "optional": True}), lambda a: ["setup", *(a.get("sites") or [])]),
    ("doctor", "Is everything working: settings, model key (optional when you write the notes), browser and login.",
     _p(), lambda a: ["doctor"]),
    ("add", "Put one person in the books.", _p(url={"type": "string", "description": "their LinkedIn profile URL"},
                                               name={"type": "string", "optional": True},
                                               headline={"type": "string", "optional": True},
                                               company={"type": "string", "optional": True},
                                               notes={"type": "string", "optional": True,
                                                      "description": "what you know about them: a post, a launch"}),
     lambda a: ["add", a["url"], *[x for k in ("name", "headline", "company", "notes") if a.get(k)
                                   for x in (f"--{k}", a[k])], "--source", "agent"]),
    ("import", "Bring people in from a .json or .csv file (another CRM's export, a list you built), with their "
               "history: status, fit, note, invited_at, messages. Already-contacted people are never invited twice.",
     _p(file=S), lambda a: ["import", a["file"]]),
    ("list", "Everyone, or everyone at one status (found approved invited connected replied meeting skipped stopped).",
     _p(status={"type": "string", "optional": True}), lambda a: ["list", *([a["status"]] if a.get("status") else [])]),
    ("show", "One person: record, every touch, latest drafts.", _p(who=WHO), lambda a: ["show", a["who"]]),
    ("fit", "Record YOUR judgement of how well they fit the audience, 0-10, and the fact that decided it.",
     _p(who=WHO, score={"type": "integer"}, why=S), lambda a: ["fit", a["who"], str(a["score"]), a["why"]]),
    ("note", "Save YOUR connection note for them. Soki checks it against the rules (300 chars, their first name "
             "first, something about them before you, no dashes, no buzzwords, must/never say, signed); if it fails, "
             "nothing is saved and the broken rules come back: fix them and call again.",
     _p(who=WHO, text=S), lambda a: ["note", a["who"], a["text"]]),
    ("approve", "The person approved this note (or reply). Only call after they said yes to the exact text.",
     _p(who=WHO), lambda a: ["approve", a["who"]]),
    ("skip", "Not this one, ever.", _p(who=WHO), lambda a: ["skip", a["who"]]),
    ("send", "Approved invites, inside every cap. With a Soki browser it sends them; with your own browser (the "
             "default) it lists who is cleared, and you send each one: `check`, Send, `sent`.",
     _p(n={"type": "integer", "optional": True}), lambda a: ["send", "--n", str(a.get("n") or 5)]),
    ("check", "Right before pressing Send in your own browser: may this invite (or, with message=true, this reply) go "
              "now? Returns yes and the exact text to send, or no and why. Never press Send after a no.",
     _p(who=WHO, message={"type": "boolean", "optional": True}),
     lambda a: ["check", a["who"], *(["--message"] if a.get("message") else [])]),
    ("sent", "Record that it went out (from your own browser, or pressed by the person). Call right after Send.",
     _p(who=WHO, message={"type": "boolean", "optional": True}),
     lambda a: ["sent", a["who"], *(["--message"] if a.get("message") else [])]),
    ("heard", "They wrote back: log their exact words. A stop phrase stops them for good.",
     _p(who=WHO, text=S), lambda a: ["heard", a["who"], a["text"], "--no-draft"]),
    ("reply", "Save YOUR answer to someone who wrote back (then approve, then answer).", _p(who=WHO, text=S),
     lambda a: ["reply", a["who"], a["text"]]),
    ("answer", "Send the approved reply.", _p(who=WHO), lambda a: ["answer", a["who"]]),
    ("sync", "Read accepted invites and new replies from the browser into the books.", _p(), lambda a: ["sync"]),
    ("mark", "Set where someone is: connected, replied, meeting, skipped, stopped.", _p(who=WHO, status=S),
     lambda a: ["mark", a["who"], a["status"]]),
    ("judge", "Have the configured model (API key) score fit, instead of you. Optional.",
     _p(who={"type": "string", "optional": True}), lambda a: ["judge", *([a["who"]] if a.get("who") else [])]),
    ("draft", "Have the configured model (API key) write notes, instead of you. Optional.",
     _p(who={"type": "string", "optional": True}), lambda a: ["draft", *([a["who"]] if a.get("who") else [])]),
]
BY_NAME = {t[0]: t for t in TOOLS}


def run(argv: list[str]) -> tuple[str, bool]:
    from . import cli  # noqa: PLC0415
    buf = io.StringIO()
    err = False
    with contextlib.redirect_stdout(buf):
        try:
            cli.main(argv)
        except SystemExit as e:
            if e.code not in (0, None):
                err = True
                if not isinstance(e.code, int):
                    print(e.code)
        except Exception as e:          # a bug must not kill the server: say it, keep serving
            err = True
            print(f"{type(e).__name__}: {e}")
    return buf.getvalue().strip() or ("failed" if err else "done"), err


def call(name: str, args: dict) -> tuple[str, bool]:
    if name not in BY_NAME:
        return f"unknown tool {name!r}", True
    if name == "guide":
        return SKILL.read_text(encoding="utf-8"), False
    try:
        argv = BY_NAME[name][3](args or {})
    except KeyError as e:
        return f"missing argument {e}", True
    return run(argv)


def handle(msg: dict) -> dict | None:
    mid, method = msg.get("id"), msg.get("method", "")
    if mid is None:                     # a notification: nothing to answer
        return None
    if method == "initialize":
        ver = (msg.get("params") or {}).get("protocolVersion") or "2025-06-18"
        res = {"protocolVersion": ver, "capabilities": {"tools": {}},
               "serverInfo": {"name": "soki", "version": __version__}, "instructions": INSTRUCTIONS}
    elif method == "ping":
        res = {}
    elif method == "tools/list":
        res = {"tools": [{"name": n, "description": d, "inputSchema": s} for n, d, s, _ in TOOLS]}
    elif method == "tools/call":
        p = msg.get("params") or {}
        text, err = call(p.get("name", ""), p.get("arguments") or {})
        res = {"content": [{"type": "text", "text": text}], "isError": err}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"no method {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": res}


def serve() -> None:
    os.environ["SOKI_AGENT"] = "1"
    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            out.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
                      + "\n")
            out.flush()
            continue
        reply = handle(msg)
        if reply is not None:
            out.write(json.dumps(reply, ensure_ascii=False) + "\n")
            out.flush()


def command() -> list[str]:
    """How an agent starts this server: this very Python, so it works whatever the agent's PATH is."""
    return [sys.executable, "-m", "soki", "mcp"]


def _skill_to(d: Path) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SKILL, d / "SKILL.md")
    return d / "SKILL.md"


JSON_APPS = {
    "claude-desktop": lambda: (Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
                               if sys.platform == "darwin" else
                               Path(os.environ.get("APPDATA", Path.home() / ".config")) / "Claude" /
                               "claude_desktop_config.json"),
    "cursor": lambda: Path.home() / ".cursor" / "mcp.json",
}


def connect(agent: str) -> str:
    cmd = command()
    if agent == "claude":
        claude = shutil.which("claude")
        if not claude:
            raise SystemExit("Claude Code (`claude`) is not installed here. Its MCP command is:\n  " + " ".join(cmd))
        subprocess.run([claude, "mcp", "remove", "soki", "-s", "user"], capture_output=True)
        r = subprocess.run([claude, "mcp", "add", "-s", "user", "soki", "--", *cmd], capture_output=True, text=True)
        if r.returncode:
            raise SystemExit(f"claude mcp add failed: {(r.stderr or r.stdout).strip()}")
        sk = _skill_to(Path.home() / ".claude" / "skills" / "soki")
        return f"Claude Code: MCP server 'soki' added (user scope), skill at {sk}. Start a new session and say: set up Soki."
    if agent in JSON_APPS:
        f = JSON_APPS[agent]()
        d = json.loads(f.read_text() or "{}") if f.is_file() else {}
        if f.is_file():
            shutil.copyfile(f, f.with_name(f.name + ".bak-soki"))
        d.setdefault("mcpServers", {})["soki"] = {"command": cmd[0], "args": cmd[1:]}
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
        return (f"{agent}: 'soki' added to {f}. Quit and reopen the app, then say: set up Soki. "
                "(The how-to comes from Soki's own `guide` tool.)")
    cfg = Path.home() / ".codex" / "config.toml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    txt = cfg.read_text() if cfg.is_file() else ""
    block = f'\n[mcp_servers.soki]\ncommand = {json.dumps(cmd[0])}\nargs = {json.dumps(cmd[1:])}\n'
    if "[mcp_servers.soki]" not in txt:
        cfg.write_text(txt.rstrip("\n") + "\n" + block)
    sk = _skill_to(Path.home() / ".codex" / "skills" / "soki")
    return f"Codex: [mcp_servers.soki] in {cfg}, skill at {sk}. Start Codex and say: set up Soki."
