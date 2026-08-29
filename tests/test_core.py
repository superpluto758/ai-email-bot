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

print("\n%d passed, %d failed" % (P, F))
for f in FAILS: print("   FAILED:", f)
sys.exit(1 if F else 0)
