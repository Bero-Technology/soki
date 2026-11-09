# Soki

**Your own sales agent.** Tell Claude or ChatGPT who you want to meet. Soki helps it find them, write each person a
note that sounds like you, send inside safe limits, and answer when they write back. It runs on your machine, uses
your own agent and browser, and needs no API key and no seat price.

```bash
uv tool install soki          # or: pip install soki        (Python 3.9+, no dependencies)
soki connect claude           # or: claude-desktop · cursor · codex
```

Then, in your agent, say: **"Set up Soki."** It asks what you sell and who you want to meet. After that you only do
two things: log in to LinkedIn in your own browser, and say yes or no to each note.

## How it works

Your agent does the thinking: it judges who fits and writes every note and reply, on your own subscription. Soki is
the part that has to be right every time, so it's in code and no prompt can talk its way past it:

- **Books.** One SQLite file on your machine (`~/.soki/books.db`). Each person is one record, whatever spelling of
  their URL comes in. Every invite, message and reply is logged, append-only.
- **Rules on every note.** At most 300 characters. Their first name first, then something about *them* before
  anything about you. No dashes, no template words ("leverage", "solution", "excited to"…), plus your own
  `must_say` and `never_say`. Your agent rewrites a note until it passes.
- **Brakes.**
  - Never the same person twice, even after a status mix-up.
  - Daily and weekly caps (15 and 80 by default, and it refuses to go above 40 a day).
  - Only inside your hours, with a gap between sends.
  - Anyone who writes "remove me", "not interested" or "unsubscribe" is stopped for good.
- **You approve.** Nothing goes out that you haven't seen. Your agent asks Soki `check` right before every Send and
  records it with `sent` right after.

## Sending

| `browser` | Who presses Send | Notes |
|---|---|---|
| `auto` (default) | Your agent, in its own browser (Claude in Chrome, ChatGPT's agent mode), inside your everyday Chrome where you're already logged in | Nothing extra to install |
| `manual` | You. Soki opens the profile and copies the note | Works with any agent |
| `chromium` | Soki, through Playwright (`pip install 'soki[chromium]'`) | A site can tell it's automated, so Soki holds it to 3 invites a day |

## Free, or run for you

| | **Soki (this repo)** | **Soki Managed** |
|---|---|---|
| Price | Free, MIT. You use your own agent subscription | $199 a month per account, plus $100 for each meeting that actually happens. No annual contract |
| Platforms | LinkedIn | LinkedIn, Instagram, X, Xiaohongshu and more |
| Who runs it | Your agent, while you're there to approve | We do, every day, whether you're there or not |
| Browser | Your own Chrome, or a plain Chromium | Our own browser, on our machines. It isn't in this repo and isn't for download |
| Accounts | One, yours | Several brands, markets and accounts |
| Replies | Your agent drafts, you approve | Answered around the clock in any language, meetings booked |

What Managed adds:

- Finds people like a person would: people who showed the need this week (a job post, a launch, a post asking for help), and reads their profile and posts before writing a word.
- Its own browser, not a test one: accounts run in a real browser built for this, on our machines, one account in one place. It is not for download and not in the free version.
- A person watching every account daily; at the first warning from a site, that account rests.
- Every platform (LinkedIn, Instagram, X, Xiaohongshu and more), written in the buyer's own language. Built for selling across borders.
- Works when you don't: replies in minutes day and night, meetings booked into your calendar.
- Pay for meetings, not seats: $199 a month per account and $100 per meeting that actually happens, no yearly contract.

### Will my account get restricted?

No tool can promise an account is never restricted, and we don't. Three things decide the odds:

1. **A real browser.** Your everyday Chrome is real. Soki's `chromium` mode is a test browser that sites can
   recognise, which is why Soki holds it to 3 invites a day.
2. **The pace of a person.** The caps, hours and gaps above are held in code in both versions.
3. **One account, one place.** An account that suddenly shows up from a second browser or machine looks hijacked.

The free version gives you 1 and 2 when your agent works in your own Chrome. Managed gives you all three on a
browser built for this, plus a person on our team watching your account.

For comparison: appointment-setting agencies typically charge $300 to $600 a meeting. Managed's first month's fee waits
until your first meeting is held. Details at [gosoki.com](https://gosoki.com/#pricing).

## Bring your history

```bash
soki import contacts.csv      # url, name, headline, company, status, note, invited_at, …
```

Your agent can do this too. Everyone you've already contacted stays off-limits, so nobody gets a second invite.

## Without an agent

Every tool is also a command: `soki --help`. `soki init` asks the setup questions in the terminal. With an
OpenAI-compatible key (OpenAI, OpenRouter, Azure, or a local Ollama), `soki judge` and `soki draft` have that model do
the thinking.

## Honest limits

- LinkedIn's User Agreement does not allow automated activity. Soki keeps you in the loop (you approve every note)
  and keeps the pace of a person. How you use your own account is up to you.
- Caps only protect an account if no other tool runs on it too.
- The free version sends on LinkedIn only. It can log you in to other sites, but it has no send flow for them yet.

## Develop

```bash
uv run --with pytest -- python -m pytest -q
```

MIT licensed.

---

**中文简介**：Soki 是你自己的销售 agent。在 Claude 或 ChatGPT 里说"帮我设置 Soki"，它会问你卖什么、想认识谁，然后替你找人，
给每个人写一条像你本人写的邀请语，在安全限额内发出，对方回复时帮你起草回答。不需要 API key，不按席位收费，数据只存在你自己的
电脑上。代码守住规则：同一个人不发两次，每天和每周有上限，对方说"别联系我"就永久停止，每一条都要你点头才发。

免费版只发 LinkedIn，用你自己的 Chrome。想要多平台（LinkedIn、Instagram、X、小红书…）、每天不用你在场、多账号，并且用我们自己的
防检测浏览器跑，那是 **Soki Managed**（托管版：每个账号每月 $199，每个实际开成的会再收 $100，不签年约），浏览器只跑在我们的机器上，不在这个仓库里，也不提供下载。见
[gosoki.com](https://gosoki.com/#pricing)。
