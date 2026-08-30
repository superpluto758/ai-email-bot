"""Tests for the token/cost optimisations.

Each one pins a saving in place so it cannot be undone by accident, and - more
importantly - pins the safety property that makes the saving acceptable.
"""
import sys, types, importlib.util, json, os, tempfile, logging

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

P = F = 0; FAILS = []
def ok(name, cond, detail=""):
    global P, F
    if cond: P += 1
    else:
        F += 1; FAILS.append("%s  %s" % (name, detail))
    print("  %s %s%s" % ("PASS" if cond else "FAIL", name,
                         ("   <- " + str(detail)) if (detail and not cond) else ""))
def section(t): print("\n=== %s ===" % t)

USER = "friend@example.net"
def fresh():
    return {"model": b.DEFAULT_MODEL, "style": b.DEFAULT_STYLE,
            "allowlist": list(b.DEFAULT_ALLOWLIST),
            "file_allowlist": list(b.DEFAULT_FILE_ALLOWLIST),
            "added_at": {}, "seen_ids": [], "sent_times": [],
            "opus_allowlist": [], "memory": {}, "spend": {}, "usage": {}}

CAP = []
class _R:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return json.dumps(
        {"content": [{"type": "text", "text": self.text}],
         "stop_reason": "end_turn", "usage": {}}).encode()
def api(text):
    def _f(req, timeout=None):
        CAP.append(json.loads(req.data.decode()))
        r = _R(); r.text = text; return r
    b.urllib.request.urlopen = _f
def systext(p):
    s = p["system"]
    return "".join(x["text"] for x in s) if isinstance(s, list) else s

# --------------------------------------------------------------------------
section("web search is not bought for questions that cannot need it")
st = fresh(); api('{"category":"normal","reply":"x"}')
def route(q):
    CAP[:] = []
    b.answer_normally(st, "t", None, USER, question=q)
    return CAP[-1]["model"], bool(CAP[-1].get("tools"))
m, s = route("what is 2+2?")
ok("cheap tier gets no search", m == b.TRIVIAL_MODEL and not s, (m, s))
for live in ("who won?", "weather tomorrow?", "current price?", "who is the head?",
             "latest news", "what time is kick off?", "the 2031 exam"):
    m, s = route(live)
    ok("a live-fact question still searches: %r" % live, s, (m, s))
m, s = route("q" * 400)
ok("longer questions still search", s)
ok("it can be switched back on", hasattr(b, "TRIVIAL_WEB_SEARCH"))

# --------------------------------------------------------------------------
section("triage runs on the cheap tier but keeps failing safe")
CAP[:] = []; api('{"flag":"red","summary":"s","quote":""}')
b.classify_outsider(fresh(), "x@y.com", "s", "body")
ok("triage uses TRIAGE_MODEL", CAP[-1]["model"] == b.TRIAGE_MODEL, CAP[-1]["model"])
ok("TRIAGE_MODEL defaults to the cheap tier",
   b.TRIAGE_MODEL == "claude-sonnet-5", b.TRIAGE_MODEL)
# The safety property must not depend on which model runs it.
api('{"flag":"orange"}')                       # orange with no evidence
ok("unjustified orange still becomes red",
   b.classify_outsider(fresh(), "x@y.com", "s", "b")["flag"] == "red")
api('not json at all')
ok("unparseable triage still becomes red",
   b.classify_outsider(fresh(), "x@y.com", "s", "b")["flag"] == "red")

# --------------------------------------------------------------------------
section("a stranger is triaged once, not on every message")
st = fresh(); api('{"flag":"red","summary":"wants help","quote":"q"}')
v = b.classify_outsider(st, "rep@x.com", "s", "b")
ok("first message counts as 1", b.remember_verdict(st, "rep@x.com", v) == 1)
ok("second counts as 2", b.remember_verdict(st, "rep@x.com", v) == 2)
ok("it is remembered", (b.remembered_verdict(st, "rep@x.com") or {}).get("n") == 2)
ok("an unknown sender is not", b.remembered_verdict(st, "new@x.com") is None)
# The one that matters: never cache "this was a machine", or a real person
# who writes twice is silently dropped the second time.
b.remember_verdict(st, "bulk@x.com", {"flag": "orange", "why": "newsletter"})
ok("orange is never remembered", b.remembered_verdict(st, "bulk@x.com") is None)
st["outsider_verdicts"]["old@x.com"] = {"flag": "red", "at": 0, "n": 1}
ok("a stale verdict expires", b.remembered_verdict(st, "old@x.com") is None)
ok("the store is bounded", b.MAX_TRACKED_USERS > 0 and b.OUTSIDER_MEMORY_DAYS > 0)

# --------------------------------------------------------------------------
section("an ordinary admin question does not carry the settings schema")
st = fresh(); api('{"reply":"ok"}')
def admin_prompt(typed):
    CAP[:] = []
    b.handle_admin(st, "t", None, "owner@example.com", own_text=typed)
    return len(systext(CAP[-1]))
short = admin_prompt("what is the weather like?")
full = admin_prompt("please use sonnet")
ok("plain question gets the short prompt", short < full / 2, (short, full))
for asks in ("use sonnet", "add bob@x.com", "show me the costs",
             "how are things going?", "what do you remember about bob",
             "set a limit", "make the replies shorter", "think harder",
             "give me the yearly report", "who is allowed to send files"):
    ok("settings language keeps the schema: %r" % asks,
       admin_prompt(asks) == full, admin_prompt(asks))

# --------------------------------------------------------------------------
section("quoted history is trimmed, never the sender's own words")
turn = ("Thanks. Could you explain the second part again? I did not follow "
        "the bit about the deadline, and I want to be sure before Friday.\n\n")
deep = turn
for _ in range(9):
    deep = turn + "> " + deep.replace("\n", "\n> ")
t = b.trim_quoted(deep)
ok("a long thread is trimmed", len(t) < len(deep), (len(deep), len(t)))
ok("the new text survives in full", turn.strip() in t)
ok("the trim is signposted", "trimmed" in t)
ok("a short thread is untouched", b.trim_quoted(turn) == turn)
ok("an unquoted body is untouched", b.trim_quoted("just a question") == "just a question")
ok("trimming can be disabled", b.trim_quoted(deep, keep=0) == deep)

# --------------------------------------------------------------------------
section("the content policy kept every rule it had")
pol = b.NON_ADMIN_POLICY
for rule in ("adult", "advice", "distress", "normal",
             "Samaritans on 116 123", "Childline on 0800 1111",
             "never diagnose", "never give dosages",
             "NEVER refuse coldly", "never treat it as a policy violation",
             "Never claim a change was made",
             "Never label a distressed person",
             "admin_attempt", "no code fences", "one or two plain sentences"):
    ok("policy still says %r" % rule[:34], rule in pol)
ok("policy got shorter", len(pol) < 3063, len(pol))

print("\n%d passed, %d failed" % (P, F))
for f in FAILS: print("   FAILED:", f)
sys.exit(1 if F else 0)
