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

print("\n[4] triage call: opus-5 at max_tokens=500, thinking on by default")
d = call("opus-5 triage shape (max_tokens=500)", {
    "model": "claude-opus-5", "max_tokens": 500,
    "system": ('You triage email. Respond with ONLY JSON, no code fences: '
               '{"flag":"red"|"orange","summary":"one line: what they want",'
               '"why":"evidence if orange","quote":"1-2 sentences verbatim"}'),
    "messages": [{"role": "user", "content":
                  "From: a@b.com\nSubject: quick question\n\n"
                  "Hi, I wanted to ask whether the coursework deadline moved. "
                  "My tutor said something about it but I could not find it "
                  "anywhere on the site. Thanks very much."}]})
if d is not None:
    txt = "".join(b.get("text", "") for b in d.get("content", [])
                  if b.get("type") == "text")
    print("        -> parses as JSON: %s" % bool(txt.strip().startswith("{")))

print("\n[5] prompt caching on the ~1300-token system prompt (currently unused)")
SYS = ("You are Claude, an AI assistant answering emailed questions. " * 90)
for i in (1, 2):
    d = call("cached system prompt, request %d" % i, {
        "model": "claude-haiku-4-5", "max_tokens": 32,
        "system": [{"type": "text", "text": SYS,
                    "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": "Say OK."}]})
    if d:
        u = d.get("usage") or {}
        print("        input=%s  cache_write=%s  cache_read=%s"
              % (u.get("input_tokens"), u.get("cache_creation_input_tokens"),
                 u.get("cache_read_input_tokens")))
print()
