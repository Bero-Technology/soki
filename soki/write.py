"""The model's three jobs, each one call on the user's own key:

    judge(person, cfg)            {fit: 0-10, why}: is this someone you want to meet, by your own audience line
    invite_note(person, cfg)      a connection note that passes rules.note_problems (rewritten up to 3 times with the
                                  broken rules fed back; still broken → SystemExit, nothing is saved)
    reply(person, thread, cfg)    an answer to someone who wrote back, in their language
"""
from __future__ import annotations

import json

from . import llm, rules


def _who(p) -> str:
    keys = ("name", "headline", "company", "about", "notes")
    return json.dumps({k: p[k] for k in keys if p[k]}, ensure_ascii=False)


def _me(cfg: dict) -> str:
    return json.dumps({"me": cfg["me"], "audience": cfg["audience"]}, ensure_ascii=False)


def first_name(p) -> str:
    return (p["name"] or "").split()[0] if (p["name"] or "").strip() else ""


def judge(p, cfg: dict) -> dict:
    out = llm.ask_json(
        f"I am looking for: {cfg['audience'] or '(not said)'}\nAbout me: {_me(cfg)}\n\nThis person:\n{_who(p)}\n\n"
        "Would they plausibly want what I offer, now? Judge only from what is written; missing facts lower the score. "
        'Reply {"fit": <0-10>, "why": "<one sentence, the fact that decided it>"}', cfg)
    fit = out.get("fit")
    if not isinstance(fit, (int, float)) or not 0 <= fit <= 10:
        raise SystemExit(f"model gave no usable fit score: {out}")
    return {"fit": int(round(fit)), "why": str(out.get("why", ""))[:300]}


NOTE_BRIEF = f"""Write a LinkedIn connection note from me to this person.
- At most {rules.NOTE_MAX_CHARS} characters. Plain words, the way a busy person writes to another.
- Start by greeting them by first name, then one specific thing about THEM (from their profile), then in one line who
  I am and what I offer, then sign with my first name.
- Write in the language their profile is written in.
- No dashes of any kind, no buzzwords, no flattery, no question asking for a call."""


def invite_note(p, cfg: dict, tries: int = 3) -> str:
    first = first_name(p)
    extra = ""
    if cfg["must_say"]:
        extra += f"\n- It must say: {'; '.join(cfg['must_say'])}"
    if cfg["never_say"]:
        extra += f"\n- It must never say: {'; '.join(cfg['never_say'])}"
    ask = f"{NOTE_BRIEF}{extra}\n\nMe: {_me(cfg)}\n\nThem:\n{_who(p)}\n\n" + 'Reply {"note": "<the note>"}'
    note, bad = "", []
    for _ in range(tries):
        prompt = ask if not bad else (f"{ask}\n\nYour last note:\n{note}\nIt broke these rules, fix every one:\n- "
                                      + "\n- ".join(bad))
        note = str(llm.ask_json(prompt, cfg).get("note", "")).strip()
        bad = rules.note_problems(note, first, cfg)
        if not bad:
            return note
    raise SystemExit(f"after {tries} tries the note still breaks the rules: {'; '.join(bad)}\nlast try: {note}")


def reply(p, thread: list[dict], cfg: dict) -> str:
    lines = "\n".join(f"{m['who']}: {m['text']}" for m in thread)
    out = llm.ask_json(
        f"Me: {_me(cfg)}\nThem: {_who(p)}\n\nOur conversation so far, oldest first:\n{lines}\n\n"
        "Write my next message. Answer what they actually said, in their language, short. If they are interested, "
        "suggest one concrete next step. If they said no, thank them and stop. No dashes, no buzzwords.\n"
        'Reply {"message": "<the message>"}', cfg)
    msg = str(out.get("message", "")).strip()
    if not msg:
        raise SystemExit(f"model wrote no message: {out}")
    return msg
