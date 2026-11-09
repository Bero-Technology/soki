# The soki-browser protocol (version 1)

A browser driver is any executable. Soki calls it as `<exe> <command> [args]` and reads **the last line of stdout as
one JSON object**. That object always has `ok`. When `ok` is false it also has `error`, a sentence a person can read.
Exit codes are ignored, and output that isn't JSON counts as a failure, never as a send.

Soki has already checked caps, hours, never-twice and stop words before it calls `invite` or `message`. The driver
does what it's told, once, and reports what actually happened on the page.

| Command | Reply |
|---|---|
| `setup` | `{"ok": true, "detail": ""}`: get ready once (make the browser profile) |
| `login <site>` | `{"ok": true, "site": "", "logins": {"linkedin": "Jane Doe"}}`: the person logs in themselves; the driver never types a password. Sites: `linkedin`, `xiaohongshu`, `rednote`, `instagram`, `x`, `tiktok` |
| `status` | `{"ok": true, "logged_in": true, "account": "Jane Doe", "protocol": 1}` |
| `profile <url>` | `{"ok": true, "name": "", "headline": "", "company": "", "about": "", "recent": ["post text", …]}` |
| `invite <url> --note-file <path>` | `{"ok": true, "result": "sent" \| "pending" \| "connected" \| "unavailable", "detail": ""}` |
| `message <url> --text-file <path>` | `{"ok": true, "result": "sent" \| "unavailable", "detail": ""}` |
| `inbox [--since <iso time>]` | `{"ok": true, "accepted": ["<profile url>", …], "threads": [{"url": "", "name": "", "messages": [{"from": "them" \| "me", "text": "", "ts": ""}]}]}` |

What each `invite` result means:

- `sent`: the invite went out with exactly the note given. The driver checked the typed text before pressing Send,
  so a truncated note is never sent.
- `pending`: an invite was already waiting. Nothing was sent.
- `connected`: you're already connected. Nothing was sent.
- `unavailable`: there was no way to connect (no button, or LinkedIn asked for their email). Nothing was sent.

The note and message come in a file, not on the command line, so they never show up in `ps` or shell history.
