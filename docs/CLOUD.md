# Soki Managed's API (`browser: cloud`)

With `"browser": "cloud"` and a Soki key, Soki sends through Soki Managed's browser, which runs on our machines. This
file is the contract the open driver (`soki/cloud.py`) speaks. The browser itself is not open source.

```bash
soki config set cloud_key <your Soki key>     # stored in ~/.soki/keys.env (mode 600), never in config.json
soki config set browser cloud
soki setup linkedin                           # opens a page showing our browser; you log in there yourself
```

Base URL: `https://api.gosoki.com/v1` (`cloud_url` in the settings).

Every request carries `Authorization: Bearer <key>`. Every reply is one JSON object with `ok`; when `ok` is false it has
`error`, a sentence a person can read. Sends carry an `Idempotency-Key` (from the person, and the text for a message):
the same key always gets the first answer back, never a second send.

| Call | Body | Reply |
|---|---|---|
| `GET /me` | | `{"ok": true, "plan": "managed"}` |
| `POST /accounts` | `{"site": "linkedin"}` | `{"ok": true, "logged_in": false, "live_url": "https://…"}`: you log in on that page; we never see or type your password |
| `GET /accounts/{site}` | | `{"ok": true, "logged_in": true, "account": "Jane Doe"}` |
| `POST /profiles` | `{"url": "…"}` | as `profile` in [BROWSER.md](BROWSER.md) |
| `POST /invites` | `{"url": "…", "note": "…"}` | `{"ok": true, "result": "sent" \| "pending" \| "connected" \| "unavailable"}`, or `{"ok": true, "result": "queued", "job": "…"}` |
| `POST /messages` | `{"url": "…", "text": "…"}` | as `/invites` |
| `GET /jobs/{id}` | | the same shape; `queued` / `running` until it has a result |
| `GET /inbox?since=` | | as `inbox` in [BROWSER.md](BROWSER.md) |

| Status | Means |
|---|---|
| 401 | the key isn't valid |
| 402 | the plan doesn't cover this |
| 403 | the key can't use this account |
| 429 | Soki's own limits for this account are reached for now |

Your books, rules and caps on your machine are checked first, as with every driver. The API checks your plan and its
own caps again, so a changed copy of the open code can't send more than the plan allows.
