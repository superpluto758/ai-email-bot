#!/usr/bin/env python3
"""Send the bot's EXACT request shapes to the real Anthropic API.

    ANTHROPIC_API_KEY=sk-ant-... python3 live_probe.py

Costs well under a penny: every probe is a few tokens. Nothing is emailed,
no state is written, and the bot itself is not started.
"""
import json, os, sys, urllib.request, urllib.error

KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
if not KEY:
    sys.exit("set ANTHROPIC_API_KEY first")
URL = "https://api.anthropic.com/v1/messages"

WEB_NEW = {"type": "web_search_20260209", "name": "web_search",
           "allowed_callers": ["direct"], "max_uses": 6}
WEB_OLD = {"type": "web_search_20250305", "name": "web_search", "max_uses": 6}


def call(label, payload, betas=None):
    headers = {"x-api-key": KEY, "anthropic-version": "2023-06-01",
               "content-type": "application/json"}
    if betas:
        headers["anthropic-beta"] = ",".join(betas)
    req = urllib.request.Request(URL, data=json.dumps(payload).encode(),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.loads(r.read().decode())
        text = "".join(b.get("text", "") for b in d.get("content", [])
                       if b.get("type") == "text")
        kinds = sorted({b.get("type") for b in d.get("content", [])})
        u = d.get("usage") or {}
        print("  PASS  %-46s stop=%-11s blocks=%s out_tok=%s text=%r"
              % (label, d.get("stop_reason"), kinds, u.get("output_tokens"),
                 text[:44]))
        return d
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf8", "replace")
        try:
            msg = json.loads(body)["error"]["message"]
        except Exception:
            msg = body[:180]
        print("  FAIL  %-46s HTTP %s: %s" % (label, e.code, msg[:150]))
        return None
    except Exception as e:
        print("  ERR   %-46s %s" % (label, e))
        return None


def base(model, **kw):
    p = {"model": model, "max_tokens": 6000,
         "system": "Answer in one short sentence.",
         "messages": [{"role": "user", "content": "Say OK."}]}
    p.update(kw)
    return p


print("\n[1] web_search tool version vs model  (bot always sends _20260209)")
for m in ("claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5"):
    call("%s + web_search_20260209" % m, base(m, tools=[WEB_NEW], max_tokens=256))
call("claude-haiku-4-5 + web_search_20250305", base("claude-haiku-4-5",
     tools=[WEB_OLD], max_tokens=256))

print("\n[2] output_config.effort by model  (bot omits it only for haiku)")
for m in ("claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5"):
    lvl = "max" if m == "claude-sonnet-5" else "xhigh"
    call("%s effort=%s" % (m, lvl), base(m, output_config={"effort": lvl},
                                         max_tokens=2000))

print("\n[3] server-side fallbacks  (bot sends these on any opus-5 call)")
call("opus-5 fallbacks=default", base("claude-opus-5", fallbacks="default",
     max_tokens=256), betas=["server-side-fallback-2026-07-01"])

TRIAGE_SYS = ('You triage email. Respond with ONLY JSON, no code fences: '
              '{"flag":"red"|"orange","summary":"one line: what they want",'
              '"why":"evidence if orange","quote":"1-2 sentences verbatim"}')
TRIAGE_MSG = ("From: a@b.com\nSubject: quick question\n\n"
              "Hi, I wanted to ask whether the coursework deadline moved. "
              "My tutor said something about it but I could not find it "
              "anywhere on the site. Thanks very much.")


def triage(label, model, max_tokens, effort):
    p = {"model": model, "max_tokens": max_tokens, "system": TRIAGE_SYS,
         "messages": [{"role": "user", "content": TRIAGE_MSG}]}
    if effort:
        p["output_config"] = {"effort": effort}
    d = call(label, p)
    if d is None:
        return
    txt = "".join(b.get("text", "") for b in d.get("content", [])
                  if b.get("type") == "text")
    # startswith("{") is NOT a parse. The failure that matters here is thinking
    # eating the budget and truncating the JSON mid-string, which still starts
    # with a brace. json.loads is the only check worth making.
    try:
        got = json.loads(txt)
        print("        -> REAL json.loads OK, flag=%r, keys=%s"
              % (got.get("flag"), sorted(got)))
    except Exception as e:
        print("        -> json.loads FAILED (%s) - the verdict would fall back "
              "to red" % type(e).__name__)


print("\n[4] triage: the shape the bot ACTUALLY sends today")
triage("sonnet-5 max_tokens=1500 effort=low  (live shape)",
       "claude-sonnet-5", 1500, "low")
print("\n[4b] the same call starved of tokens, for contrast")
triage("sonnet-5 max_tokens=500 effort=low", "claude-sonnet-5", 500, "low")
triage("opus-5 max_tokens=500 effort=high  (the old shape)",
       "claude-opus-5", 500, None)

print("\n[5] prompt caching, per model, at the bot's real prompt size")
# The bot's non-admin system prompt is ~1161 tokens. The per-model cache
# minimum decides whether cache_control does anything at all: Opus 5 needs
# 512, Sonnet 5 needs 1024, Haiku 4.5 needs 4096. Below the minimum the API
# accepts the request and silently ignores the caching - no error, no saving.
SYS = ("You are Claude, an AI assistant answering emailed questions. " * 90)
for model in ("claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"):
    for i in (1, 2):
        d = call("%s cached system prompt, request %d" % (model, i), {
            "model": model, "max_tokens": 32,
            "system": [{"type": "text", "text": SYS,
                        "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": "Say OK."}]})
        if d:
            u = d.get("usage") or {}
            w = u.get("cache_creation_input_tokens") or 0
            r = u.get("cache_read_input_tokens") or 0
            print("        input=%-6s cache_write=%-6s cache_read=%-6s %s"
                  % (u.get("input_tokens"), w, r,
                     "CACHING" if (w or r) else "cache_control IGNORED"))

print("\n[6] does web_search_20260209 actually RUN on haiku, or only validate?")
for model, tool, name in (("claude-haiku-4-5", WEB_NEW, "_20260209"),
                          ("claude-haiku-4-5", WEB_OLD, "_20250305")):
    d = call("%s %s, question that needs a search" % (model, name), {
        "model": model, "max_tokens": 1024, "tools": [tool],
        "system": "Use the web_search tool for anything time-sensitive.",
        "messages": [{"role": "user", "content":
                      "Who is the current Prime Minister of the United Kingdom?"}]})
    if d:
        kinds = [b.get("type") for b in d.get("content", [])]
        u = d.get("usage") or {}
        srv = (u.get("server_tool_use") or {}).get("web_search_requests", 0)
        print("        -> searches=%s  blocks=%s" % (srv, sorted(set(kinds))))
print()

# --------------------------------------------------------------------------
# Everything above reconstructs the bot's request shapes by hand, which is
# exactly how a probe goes stale: it kept testing an opus-5 triage call two
# commits after the bot stopped sending one. This section imports bot.py and
# calls the real call_claude, so the payload under test is the one the bot
# actually builds - tool version, effort, betas, cached system block and all.
print("\n[7] the REAL code path: bot.call_claude() against the live API")
import types, tempfile, importlib.util, logging

os.environ.setdefault("MAIL_ADDRESS", "probe@example.com")
os.environ["STATE_PATH"] = tempfile.mkdtemp() + "/probe-state.json"
sys.modules["imapclient"] = types.SimpleNamespace(IMAPClient=object)
_here = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("bot", os.path.join(_here, "bot.py"))
bot = importlib.util.module_from_spec(_spec)
sys.modules["bot"] = bot
_spec.loader.exec_module(bot)
logging.getLogger("bot").setLevel(logging.ERROR)


def real(label, model, question, web_search, effort=None, max_tokens=400,
         must_search=False):
    """Drive the bot's own call_claude with the bot's own system prompt.

    must_search says this question cannot be answered from training data. The
    first version of this probe passed a stripped "Answer in one short
    sentence." system prompt, so it was not testing the CURRENT FACTS
    instruction that exists precisely to stop stale answers - and sonnet
    duly answered from memory and was scored PASS. Use guardrails()."""
    tool = bot.web_search_tool(model)
    bot.LAST_CALL.clear()
    try:
        out = bot.call_claude(model, bot.guardrails(), question,
                              max_tokens=max_tokens, web_search=web_search,
                              effort=effort)
    except Exception as e:
        print("  ERR   %-44s %s: %s" % (label, type(e).__name__, e))
        return
    u = bot.LAST_CALL.get("usage") or {}
    searches = bot.LAST_CALL.get("searches", 0)
    bad = out in (bot.EMPTY_ANSWER, bot.MALFORMED_NOTICE)
    if must_search and not searches:
        bad = True
        label += "  <- ANSWERED FROM MEMORY"
    print("  %s  %-44s tool=%-19s searches=%s" %
          ("FAIL" if bad else "PASS", label,
           tool["type"] if web_search else "(none)", searches))
    print("        in=%-6s out=%-5s cache_w=%-6s cache_r=%-6s text=%r"
          % (u.get("input_tokens"), u.get("output_tokens"),
             u.get("cache_creation_input_tokens"),
             u.get("cache_read_input_tokens"), (out or "")[:40]))


# The tier that changed: haiku is now on web_search_20260209. This proves the
# bot's own web_search_tool() picks it AND that the call goes through.
LIVE_Q = "Who is the current Prime Minister of the United Kingdom?"

real("trivial tier, no search (the default)", bot.TRIVIAL_MODEL or "claude-haiku-4-5",
     "What is 2+2?", web_search=False)
real("trivial tier WITH search (TRIVIAL_WEB_SEARCH=1)",
     bot.TRIVIAL_MODEL or "claude-haiku-4-5", LIVE_Q,
     web_search=True, must_search=True)
real("main tier + search + effort", "claude-sonnet-5", LIVE_Q,
     web_search=True, effort="low", must_search=True)
real("top tier + search + effort + fallbacks", "claude-opus-5", LIVE_Q,
     web_search=True, effort="low", must_search=True)
# Second identical sonnet call: the system block is byte-identical, so this is
# where a cache read should appear if caching is doing anything.
real("sonnet again - cache read expected", "claude-sonnet-5", LIVE_Q,
     web_search=True, effort="low", must_search=True)
print()
