#!/usr/bin/env python3
"""Read-only health check of the bot's actual mailbox.

    MAIL_ADDRESS=... MAIL_PASSWORD=... IMAP_HOST=... python3 mailbox_probe.py

The companion to live_probe.py: that one proves the API accepts what the bot
sends, this one proves the mailbox side is working - the credentials log in,
IDLE is available so it gets push rather than polling, the labels it writes are
actually landing, and its own replies are in the folder.

STRICTLY READ-ONLY. Every fetch uses BODY.PEEK so nothing is marked as read,
no flag is added or removed, nothing is moved or deleted and nothing is sent.
Safe to run against the live mailbox while the bot is running.
"""
import email
import os
import sys
from email.header import decode_header
from email.utils import parseaddr

try:
    from imapclient import IMAPClient
except ImportError:
    sys.exit("pip3 install imapclient")

ADDR = os.environ.get("MAIL_ADDRESS", "").strip()
PW = os.environ.get("MAIL_PASSWORD", "")
HOST = os.environ.get("IMAP_HOST", "").strip()
COUNT = int(os.environ.get("PROBE_COUNT", "15"))
if not (ADDR and PW and HOST):
    sys.exit("set MAIL_ADDRESS, MAIL_PASSWORD and IMAP_HOST first")

# The same cleaning the bot does - a password copied out of a web page often
# brings invisible characters with it, and those break an ASCII-only login.
PW = "".join(c for c in PW if not c.isspace()
             and c not in "​‌‍⁠﻿")
LABELS = ("ai-answered", "ai-denied", "ai-skipped")


def hdr(msg, name):
    raw = msg.get(name, "")
    try:
        return "".join(
            part.decode(enc or "utf-8", "replace") if isinstance(part, bytes)
            else part for part, enc in decode_header(raw))
    except Exception:
        return raw


print("connecting to %s as %s" % (HOST, ADDR))
with IMAPClient(HOST, ssl=True, timeout=60) as server:
    try:
        server.login(ADDR, PW)
    except Exception as exc:
        # A stack trace helps nobody here, and the failure is nearly always one
        # of three things. Say them, and stop: the bot depends on this same
        # login, and a provider that sees repeated failures will lock it out
        # from everywhere - which would take the assistant down with it.
        print("  FAIL  login refused: %s" % str(exc)[:120])
        print("""
        Not retrying. The bot signs in with these same credentials, and
        repeated failures get the whole mailbox locked, which would stop it
        answering anything.

        Usually one of:
          1. the wrong password. The one that definitely works is in
             MAIL_PASSWORD in the compose file as DEPLOYED, not in any copy
             of it that still carries a placeholder
          2. an account password where the provider wants an app-specific
             one. With 2FA enabled, most providers refuse the account
             password over IMAP and issue a separate password per app
          3. IMAP access switched off for the account, or blocked for a new
             location - check the provider's security page

        Fix the cause before trying again rather than guessing at passwords.""")
        sys.exit(1)
    print("  PASS  login accepted")

    caps = server.capabilities()
    idle = b"IDLE" in caps
    gmail = b"X-GM-EXT-1" in caps
    print("  %s  IDLE %s  (without it the bot polls instead of getting push)"
          % ("PASS" if idle else "FAIL", "supported" if idle else "MISSING"))
    print("        labelling mode the bot will pick: %s"
          % ("gmail" if gmail else "keywords"))

    info = server.select_folder("INBOX", readonly=True)   # readonly: no \Seen
    total = info.get(b"EXISTS", 0)
    unseen = len(server.search(["UNSEEN"]))
    print("  PASS  INBOX selected read-only: %d message(s), %d unseen"
          % (total, unseen))

    uids = server.search(["ALL"])[-COUNT:]
    if not uids:
        print("  FAIL  the mailbox is empty - nothing to check")
        sys.exit(0)

    fetched = server.fetch(uids, ["FLAGS", "INTERNALDATE",
                                  "BODY.PEEK[HEADER]"])
    print("\nlast %d message(s), newest last:" % len(uids))
    tally = dict.fromkeys(LABELS, 0)
    ours = 0
    for uid in uids:
        item = fetched.get(uid, {})
        raw = item.get(b"BODY[HEADER]") or b""
        msg = email.message_from_bytes(raw)
        flags = [f.decode() if isinstance(f, bytes) else str(f)
                 for f in item.get(b"FLAGS", ())]
        marker = next((k for k in msg.keys() if k.lower().endswith("-bot")), None)
        if marker:
            ours += 1
        for name in LABELS:
            if any(name in f for f in flags):
                tally[name] += 1
        sender = parseaddr(msg.get("From", ""))[1] or "?"
        print("  uid %-7s %s  %-34s %-40s" % (
            uid, str(item.get(b"INTERNALDATE"))[:16], sender[:34],
            hdr(msg, "Subject")[:40]))
        print("            flags=%s%s" % (
            ",".join(flags) or "(none)",
            "   [our own reply: %s]" % marker if marker else ""))

    print("\nof the last %d:" % len(uids))
    for name in LABELS:
        print("  %-14s %d" % (name, tally[name]))
    print("  %-14s %d" % ("our replies", ours))
    if not any(tally.values()):
        print("\n  FAIL  no bot labels on any recent message. Either the bot has\n"
              "        not run since these arrived, or labelling is failing - it\n"
              "        gives up silently after repeated errors and keeps going.")
    else:
        print("\n  PASS  the bot's labels are landing on real messages")
    print("\nnothing was read, flagged, moved or sent.")
