"""Tests for the UTC clock.

The bot dates money, quotas and reports. Before this, "today" was whatever the
host said - and the two deployments disagreed (Asia/Singapore vs Europe/London),
so the same code gave a different answer on each box. These pin the clock to UTC
regardless of the host, which is the only way the numbers mean one thing.

The hostile TZ below is set BEFORE bot.py is imported, on purpose: that is the
only way to prove the forcing actually happens rather than inheriting a machine
that was already UTC.
"""
import sys, types, importlib.util, json, os, tempfile, logging, time, re
from datetime import datetime, timezone, timedelta

# UTC+14. If the forcing does not work, every date below is wrong for 14 hours
# a day, and wrong by a whole DAY for two hours of it.
os.environ["TZ"] = "Pacific/Kiritimati"
if hasattr(time, "tzset"):
    time.tzset()
HOSTILE_BEFORE = time.strftime("%z")

d = tempfile.mkdtemp()
os.environ.setdefault("ADMIN_ADDRESSES", "owner@example.com")
os.environ.setdefault("ALLOWLIST", "owner@example.com,friend@example.net")
os.environ.setdefault("MAIL_ADDRESS", "assistant@example.com")
os.environ["STATE_PATH"] = d + "/state.json"
sys.modules['imapclient'] = types.SimpleNamespace(IMAPClient=object)
BOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bot.py")
spec = importlib.util.spec_from_file_location('bot', BOT)
b = importlib.util.module_from_spec(spec); sys.modules['bot'] = b
spec.loader.exec_module(b)
logging.getLogger("bot").setLevel(logging.CRITICAL)
SRC = open(BOT).read()

P = F = 0; FAILS = []
def ok(name, cond, detail=""):
    global P, F
    if cond: P += 1
    else:
        F += 1; FAILS.append("%s  %s" % (name, detail))
    print("  %s %s%s" % ("PASS" if cond else "FAIL", name,
                         ("   <- " + str(detail)) if (detail and not cond) else ""))
def section(t): print("\n=== %s ===" % t)

UTC_NOW = datetime.now(timezone.utc)
UTC_DAY = UTC_NOW.strftime("%Y-%m-%d")
UTC_MONTH = UTC_NOW.strftime("%Y-%m")

section("the host clock really was hostile")
ok("test set TZ to UTC+14 before import", HOSTILE_BEFORE == "+1400",
   "%s - no tzdata on this host? every check below is then blind" % HOSTILE_BEFORE)

section("importing bot.py forces the process to UTC")
ok("time.strftime %z is +0000", time.strftime("%z") == "+0000", time.strftime("%z"))
ok("time.timezone is 0", time.timezone == 0, time.timezone)
ok("naive datetime.now() is now UTC",
   abs((datetime.now() - UTC_NOW.replace(tzinfo=None)).total_seconds()) < 5)

section("the helpers")
n = b.now_utc()
ok("now_utc is timezone-aware", n.tzinfo is not None)
ok("now_utc offset is zero", n.utcoffset() == timedelta(0), n.utcoffset())
ok("now_utc agrees with the real UTC now",
   abs((n - UTC_NOW).total_seconds()) < 5)
ok("ts_utc(0) is the epoch in UTC",
   b.ts_utc(0).strftime("%Y-%m-%d %H:%M") == "1970-01-01 00:00",
   b.ts_utc(0).isoformat())
ok("ts_utc is aware too", b.ts_utc(0).tzinfo is not None)

section("money is bucketed by the UTC day, not the host day")
st = {"spend": {}, "spend_week": {}, "spend_day": {}, "by_user": {}}
b.record_spend(st, "claude-sonnet-5", {"input_tokens": 1000, "output_tokens": 100})
days = list(st["spend_day"])
ok("exactly one day bucket", len(days) == 1, days)
ok("day bucket is the UTC date", days[0] == UTC_DAY, "%s vs %s" % (days[0], UTC_DAY))
try:
    from zoneinfo import ZoneInfo
    far = {"Pacific/Kiritimati": UTC_NOW.astimezone(ZoneInfo("Pacific/Kiritimati")),
           "Pacific/Niue": UTC_NOW.astimezone(ZoneInfo("Pacific/Niue"))}
    differing = {z: t.strftime("%Y-%m-%d") for z, t in far.items()
                 if t.strftime("%Y-%m-%d") != UTC_DAY}
    for zone, day in differing.items():
        ok("bucket is not %s's date (%s)" % (zone, day), days[0] != day)
    ok("at least one far zone disagrees with UTC right now (else test is blind)",
       bool(differing), "UTC day %s; all zones agree at this hour" % UTC_DAY)
except ImportError:
    ok("zoneinfo available", False, "skipped far-zone comparison")
ok("month bucket is the UTC month", list(st["spend"]) == [UTC_MONTH], list(st["spend"]))
wk = "%s-W%02d" % UTC_NOW.isocalendar()[:2]
ok("week bucket is the UTC ISO week", list(st["spend_week"]) == [wk],
   "%s vs %s" % (list(st["spend_week"]), wk))

section("the spend cap reads the same key record_spend writes")
# A mismatch here would not raise - the cap would just silently read 0.00 and
# never fire. That is the whole reason this is a test and not a comment.
st2 = {"spend": {}, "spend_week": {}, "spend_day": {}, "by_user": {}}
b.record_spend(st2, "claude-opus-5", {"input_tokens": 2_000_000, "output_tokens": 0})
ok("spend_today sees what was just recorded", b.spend_today(st2) > 0,
   b.spend_today(st2))
ok("spend_today equals the day bucket",
   abs(b.spend_today(st2) - st2["spend_day"][UTC_DAY]["usd"]) < 1e-9)
ok("a big spend trips the cap", b.over_spend_cap(st2))
ok("yesterday's spend does not count toward today",
   b.spend_today({"spend_day": {"1999-01-01": {"usd": 999.0}}}) == 0.0)

section("per-person tallies")
t = b.user_tally({}, "friend@example.net")
ok("user_tally defaults to the UTC month", t == {"msgs_in": 0, "msgs_out": 0,
   "in": 0, "out": 0, "searches": 0, "usd": 0.0})
st3 = {}
b.user_tally(st3, "friend@example.net")
ok("tally filed under the UTC month", list(st3["by_user"]) == [UTC_MONTH],
   list(st3["by_user"]))

section("the Date: header says +0000, not a local offset")
sent = {}
real_smtp = b.smtplib.SMTP_SSL
class FakeSMTP:
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def login(self, *a): pass
    def send_message(self, msg): sent["msg"] = msg
b.smtplib.SMTP_SSL = FakeSMTP
try:
    b.send_mail(["friend@example.net"], "hello", "body")
finally:
    b.smtplib.SMTP_SSL = real_smtp
hdr = sent.get("msg", {}).get("Date", "") if sent else ""
ok("a Date header was set", bool(hdr), hdr)
ok("Date ends +0000", hdr.endswith("+0000"), hdr)
# -0000 is RFC 5322 for "generated somewhere else"; +0000 asserts real UTC.
ok("Date is not the ambiguous -0000", not hdr.endswith("-0000"), hdr)
ok("Date parses back to the right instant",
   abs((b.email.utils.parsedate_to_datetime(hdr) - UTC_NOW).total_seconds()) < 30,
   hdr)

section("reports tell the reader which clock they are on")
rep = b.full_analytics({"model": "claude-opus-5", "allowlist": [],
                        "file_allowlist": [], "spend": {}, "usage": {}})
ok("system block states the clock", "Clock:" in rep and "UTC" in rep)
ok("says daily limits roll over at 00:00 UTC", "00:00 UTC" in rep, )
gen = b.usage_report({"usage": {"friend@example.net": [time.time()]}})
ok("usage report timestamps in UTC", re.search(r"Generated .* UTC", gen),
   gen.splitlines()[-1])

section("no local-clock call can creep back in")
ok("no datetime.now() anywhere", "datetime.now()" not in SRC)
ok("no formatdate(localtime=True)", "localtime=True" not in SRC)
ok("datetime.now( appears once - inside now_utc", SRC.count("datetime.now(") == 1,
   SRC.count("datetime.now("))
ok("datetime.fromtimestamp( appears once - inside ts_utc",
   SRC.count("datetime.fromtimestamp(") == 1, SRC.count("datetime.fromtimestamp("))
ok("TZ is pinned before logging is configured",
   SRC.index('os.environ["TZ"] = "UTC"') < SRC.index("logging.basicConfig"))
ok("tzset is guarded for non-Unix", 'hasattr(time, "tzset")' in SRC)

print("\n%d passed, %d failed" % (P, F))
for f in FAILS: print("   FAILED:", f)
sys.exit(1 if F else 0)
