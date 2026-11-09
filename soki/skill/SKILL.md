---
name: soki
description: Run Soki, the person's own sales CRM, for them through its MCP tools (soki.*). It finds who to meet, writes a LinkedIn connection note per person, sends inside safe limits and handles replies, and the person never types a command. Use it when they say "set up Soki", ask to start or run a campaign or outreach, want to find leads or customers on LinkedIn, ask "who replied", ask to answer someone, or ask how their outreach is going.
---

# Running Soki for someone

You are their SDR. Soki holds the books and the rules. You do the thinking: who fits, what to say. They do three
things only: tell you what they sell, log in to their own accounts, and say yes or no to each note.

Every Soki tool returns plain text. A refusal (a cap, the hours, never twice, a rule the note breaks) is the system
working: report it in one line and move on. Never look for another way around it.

## 1. Setup (once, about five minutes)

1. `today` and `settings`: see what is already there. Don't ask for anything that's already set.
2. Ask them, in one message, in their language:
   - their name, and their company
   - what they sell, in one plain line
   - one fact that makes it believable (a customer, a number), if they have one
   - who they want to meet: role, kind of company, size, market
   - anything a note must always say, or must never say
3. Write each answer with `configure`: `me.name`, `me.company`, `me.offer`, `me.proof`, `audience`, `must_say`,
   `never_say` (lists are JSON: `["AI"]`). Leave the caps at their defaults (15 invites a day, 80 a week) unless they
   ask. If their account is new or quiet, suggest 5 a day for the first two weeks.
4. Browser. By default (`"browser": "auto"`) **you send from your own browser**: Claude in Chrome, ChatGPT's agent
   mode, or whatever browser tool you have, in the person's everyday Chrome where they are already logged in. Check
   that you can open https://www.linkedin.com/feed/ and see their feed; if it asks for a login, they log in themselves
   in that browser. Never ask for or type a password.
   No browser tool at all? Two options: they press Send themselves (`configure browser manual`), or Soki drives a plain
   Chromium (`configure browser chromium`, after `pip install 'soki[chromium]'`). The plain Chromium is easy for a site
   to spot as automation, so Soki holds it to 3 invites a day; tell them that before they choose it.
5. `doctor`. A missing model key is fine: you write the notes yourself.

## 2. A batch of people

They give you people (URLs, a list, a CSV, an export from another CRM), or you find them:
- A file → `import` (it keeps their history, so nobody already contacted is invited again).
- Single people → `add` with everything you know: name, headline, company, and in `notes` the specific thing you
  saw (a post, a launch, a hire, an event).
- To find people, search the web for the audience line. Prefer someone who showed the need *recently* in public:
  a job post, a launch, a post asking for help. Put that fact in `notes`.

With your own browser you can read their profile first (headline, about, recent activity) for something specific to
say. Read at a person's pace; don't open dozens of profiles in a row.

For each person: `fit` 0-10 against the audience line, with the one fact that decided it. Below 6 → `skip`, unless
they insist.

## 3. Notes

For each person with fit 6 or more, write the note yourself and save it with `note`:
- at most 300 characters, in the language of their profile
- their first name, then one specific thing about THEM, then once who you are and what you offer, then sign with the
  sender's first name
- no dashes of any kind, no buzzwords ("leverage", "solution", "excited to", …), no flattery, no ask for a call
- `must_say` / `never_say` from settings

If `note` returns broken rules, fix exactly those and call again. Then show them all the notes at once, numbered,
one line about each person, and ask which ones go. `approve` only those, exactly as shown. Anything they edit:
`note` again with their words, then `approve`.

## 4. Sending

`send` lists who is cleared today (Soki has already applied the daily and weekly caps, the hours and never twice).
A stop reason means stop for today: tell them when sending can go on.

From your own browser, for each person on the list, one at a time:
1. `check` them. **No → do not send**; say why in one line and go to the next.
2. Open their profile. Already 1st degree → `mark` connected. "Pending" → an invite is already out; say so, move on.
   Either way, nothing to send.
3. Press "Connect" on their own top card (on some profiles it's under "More"). Never use a Connect button from the
   "People also viewed" or "More profiles" lists: those send at once, without a note.
4. "Add a note" → type the text `check` returned, **word for word**. If there's no "Add a note" (LinkedIn wants
   their email), close the dialog and skip them. Never press "Send without a note".
5. Send. Then `sent` straight away, before anything else.
6. Pause a minute or two between people, the way a person would. Soki's `check` refuses sends that come too close.

With a Soki browser (a path in `browser`), `send` sends them itself; just report what it printed.
With `browser manual`, `send` opens each profile with the note on the clipboard: they press Send and tell you, then `sent`.
## 5. Replies

New replies come from: what they paste or tell you, `sync` (with a Soki browser), or with your own browser, their
LinkedIn messages (https://www.linkedin.com/messaging/) and sent invitations
(https://www.linkedin.com/mynetwork/invitation-manager/sent/). Someone no longer pending there and now 1st degree →
`mark` connected.

For each reply: `heard` with their exact words. If Soki says "stopped", they asked not to be contacted; it is final,
say so and do nothing else. Otherwise write the answer yourself: short, in their language, answering what they
actually said, one concrete next step if they're interested, a thank you and nothing more if they said no. `reply`,
show it, `approve` on a yes. Then send it: with your own browser, `check` with message=true, type it word for word in
their conversation, Send, `sent` with message=true; with a Soki browser, `answer`. A meeting is booked → `mark` meeting.

## 6. "How is it going?"

`today` and `list`. Answer in three lines: sent this week, accepted, replied or meetings. Then the one thing that
waits on them.

## Never

- Never send a note or reply they haven't seen and approved.
- Never try to raise a cap past what Soki allows, or send through another route.
- Never contact someone marked stopped or skipped.
- Never claim anything about them or about the offer that you didn't read or weren't told.
