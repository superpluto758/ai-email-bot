# AI Email Assistant

A self-hosted assistant that answers email. Send it a question, get a considered
reply — with attachments read, forwards understood, and answers in whatever
language you wrote in.

It connects to a mailbox over **IMAP IDLE**, so mail is pushed to it the moment
it arrives rather than polled for. Replies typically land within seconds. It
runs anywhere Docker does: a NAS, a Raspberry Pi, an old laptop, a cheap VPS.

Built for people who want a private assistant on their own address rather than
another account on someone else's platform.

---

## What it does

- **Answers email** from addresses you allow, in the sender's own language
- **Reads attachments** — photos, PDFs, and text files go to the model as real
  content, so "what does this say?" works on a photographed page
- **Understands forwards**, including emails attached as `.eml`, and always
  replies to the person who forwarded rather than anyone quoted inside
- **Searches the web** for anything time-sensitive instead of trusting training
  data that may be out of date
- **Two permission tiers** — who may write to it at all, and the smaller set
  who may send files
- **Admin commands by email** — add and remove people, change tone, switch
  model, request usage stats, all in plain English
- **Per-user limits** — a daily reply cap per person, editable by email; owners
  are always unlimited
- **Analytics on demand** — messages, tokens, searches and cost per person
- **Weekly and monthly summaries** emailed to the owners, the weekly one
  doubling as a heartbeat
- **Memory** — it remembers useful context about the people who write to it,
  stored on your own machine
- **Cheaper routing** — short, plain questions go to a smaller model
- **A content policy for non-owners**, with alerts to you when it triggers

## What it deliberately will not do

These are enforced in code, not left to the model's judgement:

- **Never emails anyone but the sender.** Replies go to the `From` address, in
  thread. No forwarding, no CC, no third parties — there is no code path for it.
- **Never takes instructions from email.** Message content is treated as a
  question to answer, never as a command. That includes text inside forwarded
  messages, which is a common injection route.
- **Never lets admin rights be granted or removed by email.** The admin list
  lives in the environment. An admin cannot remove another admin, or themselves.
- **Never hammers a mail server.** Five rejected logins and it stops
  permanently rather than retrying — repeated failures look like credential
  stuffing and get mailboxes suspended.

---

## Setup

You need a mailbox, an [Anthropic API key](https://console.anthropic.com), and
somewhere to run Docker.

```bash
git clone https://github.com/[your-username]/ai-email-bot.git
cd ai-email-bot
```

Edit `docker-compose.yml` and fill in the placeholders — the mailbox address and
app password, your API key, and which addresses are admins. Then:

```bash
docker compose up -d
docker compose logs -f
```

You are looking for:

```
AI email assistant starting - mailbox=... via imap...
connected - waiting for mail (IMAP IDLE, push)
```

Send it a question from an allowlisted address and you should have a reply
within seconds.

### Choosing a mailbox

**Use a dedicated address, not your personal one.** Anything the assistant can
read, the model can see.

Consumer Gmail is a poor fit: its terms discourage automation, and its abuse
detection assumes a human is typing. Automated IMAP access has had accounts
suspended. Providers that expect programmatic access work far better —
Fastmail, Zoho Mail (paid tiers; IMAP is off by default and must be enabled),
Migadu, Purelymail.

Whichever you pick, generate an **app-specific password** rather than using your
account password. IMAP will usually reject the latter outright.

### Deliverability

If replies land in spam, it is almost always a new-domain reputation problem
rather than a fault here. Publish **SPF**, **DKIM** and **DMARC** for your
domain — most providers give you the exact records — and have early recipients
mark the first reply as "not spam". Reputation builds over days.

---

## Using it

### Asking things

Email the address. Attach a photo, forward something, write in any language.
Replies stay in thread, so follow-up questions keep their context.

### Admin commands

From an admin address, in plain English:

| What you want | Something like |
|---|---|
| Add someone | `add alice@example.com to the allowlist` |
| Remove someone | `remove alice@example.com from the allowlist` |
| Let someone send files | `allow alice@example.com to send files` |
| Revoke file permission | `remove alice@example.com from the file allowlist` |
| Change tone | `keep replies shorter and more casual` |
| Switch model | `use sonnet` / `use opus` |
| Analytics | `show me the analytics` / `how's it going?` |
| Cost | `what have I spent this month?` |
| Stats for one person | `how much has alice@example.com used?` |
| Set someone's limit | `set alice@example.com 25 msg/day` |
| Remove a limit | `make alice unlimited` |
| What it remembers | `what do you know about alice@example.com?` |
| Forget someone | `forget everything about alice@example.com` |

There is no fixed syntax — the request is interpreted, not pattern-matched. The
reply always ends with an authoritative `Applied:` line written by the code, so
it cannot claim a change that did not happen.

### Analytics

Any analytics question returns the same full picture, so the answer never
depends on how you phrased it:

```
SYSTEM
  Mailbox:          you@example.com
  Model:            claude-opus-5   (simple questions -> claude-sonnet-5)
  Running for:      4.2 days
  People allowed:   5   (may send files: 4)
  Default limit:    25 msg/day
  Send caps:        30/hour, 150/day  (used today: 7)
  This month:       £10.98 across 1,300,000 in / 290,000 out tokens, 15 searches

THIS MONTH, PER PERSON (2026-08)
User                    sent   recv   input tok  output tok searches         £
alice@example.com          9      8     900,000     200,000       12     £7.60
bob@example.com            6      4     400,000      90,000        3     £3.38
```

`sent` is what they emailed in, `recv` is what they got back — a gap between
them means messages were declined, rate limited or skipped.

Naming someone narrows both tables to them. The same layout is emailed weekly
and at month end, so the scheduled report and the on-demand one can never drift
apart.

### Memory

The model returns a short note with each reply — no extra API call — and it is
kept per person in the state file on your own machine, then fed back into that
person's next conversation:

```
- Year 11, doing GCSE physics
- Prefers short answers with worked examples
```

Capped and trimmed oldest-first. Ask what it knows, or tell it to forget
someone, at any time. Set `MEMORY_ENABLED: "0"` to keep nothing.

### The content policy

Admins are unfiltered. Everyone else is classified per message:

| Category | What happens | You are told |
|---|---|---|
| Adult content | Blocked; nothing answered | yes |
| Medical, legal, financial | General information only, steered to a professional | yes |
| Distress or self-harm | Answered warmly, with real sources of help. **Never blocked** | yes |
| Anything else | Answered normally | no |

Alerts carry a short reason, never a verbatim quote — you learn what kind of
thing was asked without the person's words being reported to you.

The helplines named are UK-based (Samaritans, Childline). If you are elsewhere,
edit `NON_ADMIN_POLICY` in `bot.py`.

---

## Configuration

Everything is set through environment variables in `docker-compose.yml`.

| Variable | Required | Purpose |
|---|:--:|---|
| `MAIL_ADDRESS` | ✓ | The mailbox to read and reply from |
| `MAIL_PASSWORD` | ✓ | App-specific password |
| `ANTHROPIC_API_KEY` | ✓ | From console.anthropic.com |
| `ADMIN_ADDRESSES` | ✓ | Owners, comma separated |
| `IMAP_HOST` / `SMTP_HOST` / `SMTP_PORT` | | Your provider's servers |
| `ALLOWLIST` | | Who gets answered. Defaults to the admins |
| `FILE_ALLOWLIST` | | Who may send attachments. Defaults to the admins |
| `ALERT_ADDRESSES` | | Full alerts. Defaults to the admins |
| `QUIET_ALERT_ADDRESSES` | | Same alerts, quotes removed |
| `FROM_NAME` | | Display name on replies |
| `MAX_SENDS_PER_HOUR` / `MAX_SENDS_PER_DAY` | | Send caps |
| `PER_USER_DAILY_LIMIT` | | Replies per person per day; admins exempt |
| `WEEKLY_REPORT_DAYS` / `MONTHLY_REPORT` | | Scheduled summaries; `0` disables |
| `USD_TO_GBP` / `CURRENCY_SYMBOL` | | Currency for reports |
| `SIMPLE_MODEL` / `SIMPLE_MAX_CHARS` | | Cheaper model for short questions |
| `MEMORY_ENABLED` / `MEMORY_MAX_CHARS` | | Remembering people between emails |
| `REPLY_DELAY_MIN` / `REPLY_DELAY_MAX` | | Random delay, seconds |
| `AUTH_FAIL_LIMIT` | | Rejected logins before it stops |
| `TZ`, `STATE_PATH` | | Timezone, state file location |

The allowlists in the environment are **seeds**. Once running, they live in the
state file and are changed by email.

### Running on a NAS

Some NAS Docker interfaces only accept a pasted compose file and cannot mount a
local `bot.py`. `build_embedded_compose.py` produces a single self-contained
file with the source gzipped and embedded:

```bash
python3 build_embedded_compose.py > compose-embedded.yml
```

Paste that into the NAS UI and fill in the placeholders. Note that some editors
reject very long lines, which is why the embedded payload is wrapped.

---

## Costs

The API is the running cost; the mailbox is a pound or two a month.

Roughly, per reply: a text answer is fractions of a penny. **Web search and
images are what add up** — a search costs about a cent, and a phone photo can be
worth several thousand tokens. If many people use it, switch to a cheaper model
by emailing `use sonnet`, and keep an eye on the console.

The send caps limit outbound mail. They do **not** cap spend — a blocked message
still cost an API call to classify.

Two things help: `SIMPLE_MODEL` routes short questions to a cheaper model for
free, and the weekly report tells you what each person is costing before the
bill does. Currency conversion uses a fixed rate you set; Anthropic bills in
USD, so their console is authoritative.

---

## Requirements

- Docker
- A mailbox with IMAP and SMTP access
- An Anthropic API key

Python dependencies: `imapclient`, installed automatically on start.

---

## Licence

MIT — see [LICENSE](LICENSE).

This is a personal project shared as-is. It talks to your mailbox and spends
money against your API key; read the code before pointing it at anything you
care about.
