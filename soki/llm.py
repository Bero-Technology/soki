"""The model, on the user's own key. One call shape: a prompt in, one JSON value out.

Any OpenAI-compatible endpoint works (config base_url + model): OpenAI, OpenRouter, Azure /openai/v1, Ollama,
LM Studio. Standard library only, so `pip install` pulls nothing. Nothing falls back to anything: if the call fails,
the command fails and says why.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request

from . import config

SYSTEM = "You reply with one JSON value and nothing else."


def first_json(txt: str):
    txt = (txt or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", txt, re.S)
    if m:
        txt = m.group(1)
    for i in sorted(j for j in (txt.find("{"), txt.find("[")) if j >= 0):
        try:
            return json.JSONDecoder().raw_decode(txt[i:])[0]
        except json.JSONDecodeError:
            continue
    raise ValueError(f"no JSON in the model's reply: {txt[:300]}")


def chat(prompt: str, cfg: dict, *, system: str = SYSTEM, timeout: int = 180) -> str:
    key = config.api_key()
    local = any(h in cfg["base_url"] for h in ("localhost", "127.0.0.1"))
    if not key and not local:
        raise SystemExit("no model key: run `soki init`, or set OPENAI_API_KEY")
    body = json.dumps({"model": cfg["model"],
                       "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]})
    req = urllib.request.Request(cfg["base_url"].rstrip("/") + "/chat/completions", data=body.encode(),
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}",
                                          "api-key": key})
    for wait in (0, 5, 20, 60):
        time.sleep(wait)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read())
            break
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and wait != 60:
                continue
            raise SystemExit(f"model call failed: HTTP {e.code} {e.read()[:300].decode(errors='replace')}") from None
        except urllib.error.URLError as e:
            raise SystemExit(f"model endpoint unreachable ({cfg['base_url']}): {e.reason}") from None
    txt = d["choices"][0]["message"].get("content") or ""
    if not txt.strip():
        raise SystemExit(f"model {cfg['model']} sent an empty reply")
    return txt


def ask_json(prompt: str, cfg: dict, **kw):
    return first_json(chat(prompt, cfg, **kw))
