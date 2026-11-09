"""Where Soki keeps things, and what the user told it.

Everything lives in one folder on the user's own machine: SOKI_HOME, else ~/.soki.

    config.json   who you are, what you offer, who you want to meet, the caps, the model
    keys.env      the model key (OPENAI_API_KEY=...), never written into config.json
    books.db      the books: people, every touch, every draft (oe-style: one SQLite file is the truth)
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULTS: dict = {
    "me": {"name": "", "company": "", "offer": "", "proof": ""},
    "audience": "",
    "min_fit": 6,                   # `soki draft --next` writes only for people judged at least this fit (0-10)
    "must_say": [],
    "never_say": [],
    # LinkedIn's own weekly ceiling is about 100 invites. A person sends a handful a day, spread out. Stay under both.
    "caps": {"invites_per_day": 15, "invites_per_week": 80, "messages_per_day": 30, "min_gap_seconds": 90},
    "hours": [9, 19],               # local time; nothing goes out outside these hours
    "stop_words": [],               # extra phrases on top of rules.STOP_WORDS
    # Any OpenAI-compatible endpoint: OpenAI, OpenRouter, Azure's /openai/v1, a local Ollama or LM Studio.
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-5-mini",
    "browser": "auto",              # auto | agent | manual | chromium | the path to a soki-browser executable
}


def home() -> Path:
    p = Path(os.environ.get("SOKI_HOME") or "~/.soki").expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p


def config_path() -> Path:
    return home() / "config.json"


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def load() -> dict:
    p = config_path()
    user = json.loads(p.read_text()) if p.is_file() else {}
    cfg = _merge(DEFAULTS, user)
    check(cfg)
    return cfg


def save(cfg: dict) -> Path:
    check(cfg)
    p = config_path()
    p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
    return p


def check(cfg: dict) -> None:
    """A bad cap is a loud error, never a silent default: a brake that falls back is no brake."""
    caps = cfg["caps"]
    for k in ("invites_per_day", "invites_per_week", "messages_per_day", "min_gap_seconds"):
        v = caps.get(k)
        if not (isinstance(v, int) and not isinstance(v, bool) and v >= 0):
            raise SystemExit(f"config caps.{k} must be a whole number >= 0 (got {v!r})")
    if caps["invites_per_day"] > 40 or caps["invites_per_week"] > 150:
        raise SystemExit("config caps: more than 40 invites a day or 150 a week gets accounts restricted; lower them")
    if not (isinstance(cfg["min_fit"], int) and 0 <= cfg["min_fit"] <= 10):
        raise SystemExit(f"config min_fit must be a whole number 0 to 10 (got {cfg['min_fit']!r})")
    h = cfg["hours"]
    if not (isinstance(h, list) and len(h) == 2 and all(isinstance(x, int) for x in h) and 0 <= h[0] < h[1] <= 24):
        raise SystemExit(f"config hours must be [start, end] in 0..24 (got {h!r})")
    for k in ("must_say", "never_say", "stop_words"):
        if not (isinstance(cfg[k], list) and all(isinstance(x, str) for x in cfg[k])):
            raise SystemExit(f"config {k} must be a list of phrases")


def api_key() -> str:
    """OPENAI_API_KEY from the environment, else SOKI_HOME/keys.env. Empty when neither has it."""
    k = os.environ.get("OPENAI_API_KEY", "")
    if not k:
        f = home() / "keys.env"
        if f.is_file():
            for line in f.read_text().splitlines():
                name, _, val = line.partition("=")
                if name.strip() == "OPENAI_API_KEY":
                    k = val
    return k.strip().strip('"').strip("'")


def save_key(key: str) -> Path:
    f = home() / "keys.env"
    f.write_text(f"OPENAI_API_KEY={key.strip()}\n")
    f.chmod(0o600)
    return f
