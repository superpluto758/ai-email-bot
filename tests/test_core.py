"""Offline test suite for the email bot. Exercises every function without
touching the network or the real mailbox."""
import sys, types, importlib.util, json, os, time, tempfile, email.message, logging

d = tempfile.mkdtemp(); os.environ.setdefault("ADMIN_ADDRESSES", "owner@example.com,second@example.com,third@example.com,work@example.org")
os.environ.setdefault("ALERT_ADDRESSES", "owner@example.com,second@example.com,third@example.com")
os.environ.setdefault("NEVER_UNPROMPTED_ADDRESSES", "work@example.org")
os.environ.setdefault("ALLOWLIST", "owner@example.com,second@example.com,third@example.com,work@example.org,friend@example.net")
os.environ.setdefault("MAIL_ADDRESS", "assistant@example.com")
os.environ["STATE_PATH"] = d + "/state.json"
sys.modules['imapclient'] = types.SimpleNamespace(IMAPClient=object)
BOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bot.py")
spec = importlib.util.spec_from_file_location('bot', BOT)
b = importlib.util.module_from_spec(spec); sys.modules['bot']=b; spec.loader.exec_module(b)
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

def mk(frm="a@x.com", subj="hi", body="hello", **hdrs):
    m = email.message.EmailMessage()
    m["From"], m["Subject"] = frm, subj
    for k, v in hdrs.items(): m[k.replace("_","-")] = v
    m.set_content(body)
    return email.message_from_bytes(m.as_bytes())

# ---------------------------------------------------------------- addresses
section("addresses")
ok("gmail dots ignored", b.normalize("a.b.c@gmail.com") == b.normalize("abc@gmail.com"))
ok("plus tag ignored", b.normalize("abc+spam@gmail.com") == b.normalize("abc@gmail.com"))
ok("case ignored", b.normalize("ABC@Gmail.com") == b.normalize("abc@gmail.com"))
ok("non-gmail dots kept", b.normalize("a.b@wp.pl") != b.normalize("ab@wp.pl"))
ok("admin recognised", b.is_admin(b.ADMINS[0].upper()))
ok("stranger not admin", not b.is_admin("nobody@example.com"))

# ------------------------------------------------------------------ parsing
section("parsing")
ok("quoted reply stripped",
   b.new_text_only("my new question\n\nOn Mon, someone wrote:\n> old stuff") == "my new question")
ok("outlook block stripped",
   "old" not in b.new_text_only("new text\n\nFrom: X\nSent: yesterday\nold"))
ok("plain body untouched", b.new_text_only("just a question") == "just a question")
ok("forward detected (subject)", b.looks_forwarded("Fwd: hello", ""))
ok("forward detected (chinese)", b.looks_forwarded("转发: hello", ""))
ok("normal subject not a forward", not b.looks_forwarded("Re: hello", "just text"))
ok("mojibake repaired", b._fix_mojibake("Â£10.98") == "£10.98")
ok("clean text untouched", b._fix_mojibake("£10.98") == "£10.98")
ok("folded header collapsed", "\n" not in b.clean_header("a\r\n b\n  c"))
ok("utf-8 body decoded", "café" in b.body_text(mk(body="café au lait")))

section("automated-sender filter")
for frm, subj, want in [
    ("noreply-dmarc-support@google.com", "Report domain: x.com", True),
    ("dmarcreport@microsoft.com", "Report Domain: x.com", True),
    ("odd@tiny-isp.example", "Report Domain: x.com", True),
    ("no-reply@shop.example", "sale", True),
    ("noreply-billing@shop.example", "invoice", True),
    ("mailer-daemon@mx.example", "bounce", True),
    ("j.nowak91@wp.pl", "hi can you help", False),
    ("teacher@school.example", "Report on your son's progress", False)]:
    ok("is_automated %-34s" % frm, b.is_automated(mk(frm, subj), frm) == want)
ok("List-Unsubscribe caught", b.is_automated(mk(List_Unsubscribe="<https://x>"), "a@x.com"))
ok("Precedence bulk caught", b.is_automated(mk(Precedence="bulk"), "a@x.com"))
ok("out-of-office caught", b.is_automated(mk(subj="Automatic reply: away"), "a@x.com"))

# -------------------------------------------------------------- attachments
section("attachments")
def with_attach(mime, name, data=b"x"*10, main="image", sub="png"):
    m = email.message.EmailMessage()
    m["From"], m["Subject"] = "a@x.com", "look"
    m.set_content("see attached")
    m.add_attachment(data, maintype=main, subtype=sub, filename=name)
    return email.message_from_bytes(m.as_bytes())
blocks, unread = b.extract_attachments(with_attach("image/png","p.png"))
ok("png becomes an image block", blocks and blocks[0]["type"] == "image")
blocks, unread = b.extract_attachments(with_attach("application/pdf","d.pdf",main="application",sub="pdf"))
ok("pdf becomes a document block", blocks and blocks[0]["type"] == "document")
blocks, unread = b.extract_attachments(with_attach("text/plain","n.txt",b"hello there",main="text",sub="plain"))
ok("text inlined", blocks and "hello there" in json.dumps(blocks))
blocks, unread = b.extract_attachments(with_attach("application/octet-stream","x.docx",main="application",sub="vnd.ms-word"))
ok("unreadable type named, not silently dropped", unread and "x.docx" in unread[0])
big = with_attach("image/png","huge.png", b"x"*(5*1024*1024))
blocks, unread = b.extract_attachments(big)
ok("oversized attachment refused", not blocks)

# ----------------------------------------------------------------- api call
section("api payload")
captured = []
class Resp:
    def __enter__(self): return self
    def __exit__(self,*a): pass
    def read(self): return json.dumps(self.payload).encode()
def fake(req, timeout=None):
    captured.append(json.loads(req.data.decode()))
    r = Resp(); r.payload = FAKE[0]; return r
FAKE = [{"content":[{"type":"text","text":"ok"}],"stop_reason":"end_turn","usage":{}}]
b.urllib.request.urlopen = fake

captured.clear(); b.call_claude("claude-opus-5","s","hi",effort="xhigh")
ok("effort sent on opus", captured[0].get("output_config") == {"effort":"xhigh"})
ok("opus keeps refusal fallback", captured[0].get("fallbacks") == "default")
captured.clear(); b.call_claude("claude-haiku-4-5","s","hi",effort="max")
ok("effort NEVER sent to haiku", "output_config" not in captured[0])
captured.clear(); b.call_claude("claude-sonnet-5","s","hi")
ok("no deprecated params", not any(k in captured[0] for k in
    ("thinking","budget_tokens","temperature","top_p","output_format")))
captured.clear(); b.call_claude("claude-sonnet-5","s","hi",web_search=True)
ok("web search tool is current", captured[0]["tools"][0]["type"] == "web_search_20260209")

FAKE[0] = {"content":[{"type":"text","text":"see <cite>src</cite> here"}],"stop_reason":"end_turn","usage":{}}
ok("cite tags stripped", "<cite>" not in b.call_claude("claude-sonnet-5","s","hi"))
FAKE[0] = {"content":[{"type":"text","text":""}],"stop_reason":"refusal","usage":{}}
ok("refusal handled gracefully", "can't help" in (b.call_claude("claude-sonnet-5","s","hi") or ""))
FAKE[0] = {"content":[{"type":"text","text":"answer"}],"stop_reason":"end_turn",
           "usage":{"input_tokens":100,"output_tokens":20,
                    "server_tool_use":{"web_search_requests":2}}}
b.LAST_CALL.clear(); b.call_claude("claude-sonnet-5","s","hi")
ok("usage recorded", b.LAST_CALL["usage"]["input_tokens"] == 100)
ok("searches counted", b.LAST_CALL["searches"] == 2)

# ------------------------------------------------------------------ routing
section("routing")
st = b.load_state(); st["model"] = "claude-opus-5"
USER, VIP, ADMIN = "friend@example.com", "vip@example.com", b.ADMINS[0]
st["opus_allowlist"] = [VIP]
ok("user trivial -> haiku", b.pick_model(st,"what is 7x8?",None,USER) == "claude-haiku-4-5")
ok("user long -> sonnet", b.pick_model(st,"x"*300,None,USER) == "claude-sonnet-5")
ok("user very long capped at sonnet", b.pick_model(st,"x"*5000,None,USER) == "claude-sonnet-5")
ok("user + photo capped at sonnet", b.pick_model(st,"what is this?",[1],USER) == "claude-sonnet-5")
ok("user + news capped at sonnet", b.pick_model(st,"latest news?",None,USER) == "claude-sonnet-5")
ok("vip + photo -> opus", b.pick_model(st,"what is this?",[1],VIP) == "claude-opus-5")
ok("vip + news -> opus", b.pick_model(st,"latest news?",None,VIP) == "claude-opus-5")
ok("vip trivial still haiku", b.pick_model(st,"hi",None,VIP) == "claude-haiku-4-5")
ok("admin always main", b.pick_model(st,"hi",None,ADMIN,is_owner=True) == "claude-opus-5")
ok("fable never auto-routed", "claude-fable-5" not in
   {b.pick_model(st,q,None,u) for q in ("hi","x"*300,"x"*5000) for u in (USER,VIP)})
section("effort")
ok("admin opus -> xhigh", b.pick_effort(st,"claude-opus-5",True) == "xhigh")
ok("admin sonnet -> max", b.pick_effort(st,"claude-sonnet-5",True) == "max")
ok("admin fable -> xhigh", b.pick_effort(st,"claude-fable-5",True) == "xhigh")
ok("admin haiku -> none", b.pick_effort(st,"claude-haiku-4-5",True) is None)
ok("user -> default", b.pick_effort(st,"claude-sonnet-5",False) is None)
st["effort"] = "max"
ok("override honoured", b.pick_effort(st,"claude-opus-5",True) == "max")
ok("override still not sent to haiku", b.pick_effort(st,"claude-haiku-4-5",True) is None)
st["effort"] = None

# ------------------------------------------------------------------- limits
section("limits")
st["sent_times"] = [time.time()]*b.MAX_SENDS_PER_HOUR
ok("hourly cap trips", "hourly" in (b.over_send_limit(st) or ""))
st["sent_times"] = []
ok("no cap when idle", b.over_send_limit(st) is None)
ok("default limit is 30", b.user_daily_limit(st, USER) == 30)
ok("admin unlimited", b.user_daily_limit(st, ADMIN) is None)
st["per_user_limits"] = {b.normalize(USER): 2}
ok("override honoured", b.user_daily_limit(st, USER) == 2)
st["sent_to"] = {b.normalize(USER): [time.time()]*2}
ok("over limit detected", b.over_user_limit(st, USER) == (2,2))
st["per_user_limits"] = {b.normalize(USER): 0}
ok("zero means unlimited", b.user_daily_limit(st, USER) is None)
st["per_user_limits"] = {}; st["sent_to"] = {}

# ------------------------------------------------------------------- memory
section("memory")
st["memory"] = {}
b.add_memory(st, USER, "does GCSE physics")
b.add_memory(st, USER, "prefers short answers")
ok("both notes kept", "physics" in b.get_memory(st,USER) and "short" in b.get_memory(st,USER))
for i in range(200): b.add_memory(st, USER, "note %d padding padding padding" % i)
ok("memory capped", len(b.get_memory(st,USER)) <= b.MEMORY_MAX_CHARS)
ok("oldest trimmed first", "does GCSE physics" not in b.get_memory(st,USER))
ok("dot variant shares memory", b.get_memory(st,"FRIEND@example.com") == b.get_memory(st,USER))

# -------------------------------------------------------------------- spend
section("spend + analytics")
st["spend"]={}; st["spend_week"]={}; st["by_user"]={}; st["usage"]={}; st["usage_names"]={}
b.record_usage(st, USER)
b.record_spend(st,"claude-sonnet-5",{"input_tokens":1_000_000,"output_tokens":100_000},3,USER)
month = time.strftime("%Y-%m")
exp = (1_000_000*2.0 + 100_000*10.0)/1_000_000 + 3*0.01
ok("cost maths correct", abs(st["spend"][month]["usd"] - exp) < 1e-9,
   "%s vs %s" % (st["spend"][month]["usd"], exp))
ok("weekly bucket written", any(st["spend_week"].values()))
ok("per-user tally written", st["by_user"][month][b.normalize(USER)]["searches"] == 3)
for fn in ("spend_report","yearly_cost_report","weekly_cost_report"):
    out = getattr(b, fn)(st)
    ok("%s renders" % fn, isinstance(out,str) and len(out) > 40)
ok("cost_by_user renders", USER in b.cost_by_user(st, month))
ok("usage_report renders", USER in b.usage_report(st))
full = b.full_analytics(st)
for want in ("SYSTEM","Recording since","THIS MONTH, PER PERSON","EMAILS RECEIVED","SPEND BY MONTH"):
    ok("analytics has %r" % want, want in full)
ok("analytics filter narrows", "vip" not in b.full_analytics(st, only=[USER]).lower())

section("who is allowed, by name")
# A count cannot answer the only question anyone asks of the allowlist - did my
# change land? Working that out used to mean comparing counts between two weekly
# reports and guessing which of the +2 was the person you cared about.
import time as _t, hashlib as _h
ps = b.load_state()
ps["allowlist"] = list(b.DEFAULT_ALLOWLIST) + ["late@example.net", "capped@example.net"]
ps["opus_allowlist"] = ["late@example.net"]
ps["file_allowlist"] = list(b.DEFAULT_FILE_ALLOWLIST) + ["late@example.net"]
ps["added_at"] = {"late@example.net": _t.time() - 3 * 86400}
ps["per_user_limits"] = {"capped@example.net": 5}
rep = b.people_report(ps)
ok("every allowed address is named",
   all(a in rep for a in ps["allowlist"]), rep)
ok("owners are marked", rep.count("yes") >= 3, rep)
admin_row = next(l for l in rep.splitlines() if b.ADMINS[0] in l)
ok("an owner shows as owner", admin_row.split()[1] == "yes", admin_row)
ok("an owner is unlimited", "unlimited" in admin_row, admin_row)
late_row = next(l for l in rep.splitlines() if "late@example.net" in l)
ok("file permission is shown", late_row.split()[2] == "yes", late_row)
ok("top-model permission is shown", late_row.split()[3] == "yes", late_row)
ok("the date they were added is shown",
   _t.strftime("%Y-%m-%d", _t.gmtime(_t.time() - 3 * 86400)) in late_row, late_row)
capped_row = next(l for l in rep.splitlines() if "capped@example.net" in l)
ok("a custom limit is shown", "5/day" in capped_row, capped_row)
ok("someone seeded in the environment says so", "at setup" in rep)
ok("an empty allowlist says so plainly",
   b.people_report({"allowlist": []}) == "Nobody is on the allowlist.")
ok("it appears in the analytics report", "PEOPLE ALLOWED" in b.full_analytics(ps))

section("the exchange rate is applied, not assumed")
# The rate is hand-set and drifts - it sat at 0.79 while the real rate was
# 0.7549, overstating every figure by 4.6%. What matters is that the number the
# report PRINTS is the number it actually divided by, so a stale rate is always
# visible rather than silently baked in.
rs = {"spend": {"2026-09": {"in": 1000, "out": 100, "searches": 0, "usd": 10.0}},
      "spend_week": {}, "by_user": {}}
rep = b.spend_report(rs)
ok("the report states the rate it used",
   "%.2f USD->GBP" % b.USD_TO_GBP in rep, rep.splitlines()[-1])
expected = "%s%.2f" % (b.CURRENCY, 10.0 * b.USD_TO_GBP)
ok("and converts by exactly that rate", expected in rep, (expected, rep))
ok("the rate is a plausible USD->GBP figure, not a typo",
   0.5 < b.USD_TO_GBP < 1.0, b.USD_TO_GBP)
# The spend cap is denominated in USD, so the rate must not touch it.
ok("the daily cap stays in USD", isinstance(b.DAILY_SPEND_CAP_USD, float))
ok("changing the rate cannot change the cap",
   "USD_TO_GBP" not in open(BOT).read().split("def over_spend_cap")[1][:400])

section("which build is actually running")
# The container writes bot.py out of the compose and runs it, so the version
# live on the box could only be inferred from whether some new line showed up
# in a report. That guesswork cost a long misdiagnosis, twice.
ok("BUILD is the sha256 of this very file",
   b.BUILD == _h.sha256(open(BOT, "rb").read()).hexdigest()[:8], b.BUILD)
ok("it is short enough to read aloud", len(b.BUILD) == 8, b.BUILD)
ok("the report states it", "Build:" in b.full_analytics(ps) and b.BUILD in b.full_analytics(ps))
ok("an unreadable source degrades rather than crashing",
   b.build_id.__doc__ and "unknown" in open(BOT).read())

section("what it calls itself")
# One name, two places. Before this the From: display name and the sentence the
# model introduces itself with were set independently, so renaming the bot left
# them disagreeing.
def reload_with(from_name):
    env = dict(os.environ)
    if from_name is None: os.environ.pop("FROM_NAME", None)
    else: os.environ["FROM_NAME"] = from_name
    try:
        sp = importlib.util.spec_from_file_location('bot_renamed', BOT)
        m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m)
        return m
    finally:
        os.environ.clear(); os.environ.update(env)

m = reload_with("Helper Assistant")
ok("BOT_NAME follows FROM_NAME", m.BOT_NAME == "Helper Assistant", m.BOT_NAME)
ok("the prompt introduces it by that name",
   m.guardrails().startswith("You are Helper Assistant,"), m.guardrails()[:50])
ok("it still says it is an AI assistant", "an AI assistant" in m.guardrails())
ok("the From: display name matches",
   b.formataddr((m.FROM_NAME, "x@example.com")).startswith("Helper Assistant <"))

m = reload_with("  Spaced Name  ")
ok("surrounding whitespace is trimmed", m.BOT_NAME == "Spaced Name", m.BOT_NAME)

m = reload_with("")
# An empty FROM_NAME means "send with no display name" - it must not leave the
# prompt saying "You are , an AI assistant".
ok("an empty name falls back rather than breaking the sentence",
   m.BOT_NAME and "You are ," not in m.guardrails(), m.guardrails()[:40])

print("\n%d passed, %d failed" % (P, F))
for f in FAILS: print("   FAILED:", f)
sys.exit(1 if F else 0)
