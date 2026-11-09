"""What a note may and may not be, held in code. A model writes the words; these decide whether they may go out.

    note_problems(note, first, cfg)   [] = ok, else one plain sentence per broken rule (fed back to the writer)
    stop_word(text, cfg)              the stop phrase an inbound message contains, or ''

Ported from Soki's engine, where every rule here is one a real reply (or a real complaint) taught us.
"""
from __future__ import annotations

import re

NOTE_MAX_CHARS = 300        # LinkedIn's own limit for a connection note

# Words that make a note read like a template. Whole words or phrases, any case; "game-changer" also hits "game changer".
BUZZWORDS = (
    "leverage", "synergy", "game changer", "cutting edge", "elevate", "unlock", "seamless", "innovative",
    "revolutionize", "revolutionise", "next level", "world class", "disrupt", "disruptive", "empower", "supercharge",
    "skyrocket", "boost", "reach out", "touch base", "circle back", "value add", "best in class", "solution",
    "solutions", "passionate", "excited to", "delighted to", "amazing", "incredible", "stunning", "transform",
    "transformative", "unleash", "holistic", "robust", "scalable", "ecosystem", "thrilled", "i hope this finds you",
)

STOP_WORDS = ("unsubscribe", "opt out", "remove me", "take me off", "stop messaging", "stop contacting",
              "stop emailing", "stop writing", "do not contact", "don't contact", "dont contact", "do not message",
              "don't message", "leave me alone", "not interested")

DASHES = re.compile(r"[‒–—―]| - | -- ")      # the dash a model reaches for; reads as machine-made


def _phrase(w: str) -> re.Pattern:
    parts = [re.escape(p) for p in re.split(r"[\s\-]+", w.strip()) if p]
    return re.compile(r"(?<!\w)" + r"[\s\-]+".join(parts) + r"(?!\w)", re.I)


def note_problems(note: str, first: str, cfg: dict) -> list[str]:
    bad = []
    note = note.strip()
    if not 1 <= len(note) <= NOTE_MAX_CHARS:
        bad.append(f"{len(note)} characters; at most {NOTE_MAX_CHARS}")
    if first and first.lower() not in note[:60].lower():
        bad.append(f"greet them by first name ('{first}') at the start")
    if DASHES.search(note):
        bad.append("no dashes at all; use a comma or a full stop")
    hits = sorted({w for w in BUZZWORDS if _phrase(w).search(note)})
    if hits:
        bad.append(f"drop the template words: {', '.join(hits)}")
    for w in cfg.get("never_say", []):
        if w.strip() and _phrase(w).search(note):
            bad.append(f"must not say '{w}'")
    for w in cfg.get("must_say", []):
        if w.strip() and not _phrase(w).search(note):
            bad.append(f"must say '{w}'")
    me = (cfg.get("me") or {}).get("name", "").strip()
    if me and me.split()[0].lower() not in note.lower():
        bad.append(f"sign it as '{me.split()[0]}'")
    # The first thing after the greeting is about THEM, not us: a note that opens with "I'm" or "We" gets ignored.
    body = re.sub(r"^\s*(hi|hello|hey|dear)\s+[^,!.]{1,40}[,!.]\s*", "", note, flags=re.I)
    if re.match(r"(i'?m|i am|we|our|my)\b", body, re.I):
        bad.append("open with something specific about them (their post, product, role), not about you")
    return bad


def stop_word(text: str, cfg: dict | None = None) -> str:
    words = STOP_WORDS + tuple((cfg or {}).get("stop_words", []))
    for w in words:
        if w.strip() and _phrase(w).search(text or ""):
            return w
    return ""
