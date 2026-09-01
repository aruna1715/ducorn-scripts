#!/usr/bin/env python3
"""
The router waits five minutes for a stalled local model. The test has ten.

── WHAT THE ROUTER LOG SAYS ─────────────────────────────────────────────────

    [DuCorn Router] upstream timeout:
    INFO: 127.0.0.1:53701 - "POST /v1/chat/completions HTTP/1.1" 504 Gateway Timeout

Twenty of those against 998 successes in the last stretch of router.log. Two
per cent is not much — until you see the budget:

    async with httpx.AsyncClient(timeout=300) as client:

Three hundred seconds. A single stalled Ollama call eats half the e2e test's
600-second allowance, and two eat all of it, whatever the model was doing. The
run does not look broken from the outside; it looks slow. That is why this
test "always times out" and why the last three explanations were all partly
right and none of them sufficient.

It also means we have been debugging blind: nothing in this stack records how
long a model call takes. Every question tonight — is it looping, is Ollama
overloaded, is the context too long — is answerable in one line of timing data
that nobody was writing down.

── THREE CHANGES ────────────────────────────────────────────────────────────

1. A LOCAL MODEL GETS A SHORTER BUDGET THAN A REMOTE ONE.

   They fail differently. Anthropic taking two minutes on a long completion is
   normal. Ollama on a Mac Mini that has produced nothing in two and a half
   minutes is not thinking, it is stuck behind a model reload or a queue —
   and failing fast lets CrewAI retry inside the test's budget instead of the
   whole run dying silently.

       local   150s   (DUCORN_LOCAL_TIMEOUT)
       remote  300s   (DUCORN_REMOTE_TIMEOUT, unchanged)

   Applied per request, not to the client, so the models listing is untouched.

2. EVERY CALL IS TIMED, and the slow ones say so.

       [DuCorn Router] ⏱ local-fast 12.4s
       [DuCorn Router] ⏱ SLOW local-fast 96s of a 150s budget

   One grep now answers "is Ollama healthy" without reading a 6 MB log.

3. THE TIMEOUT MESSAGE SAYS HOW LONG IT WAITED, and the 504 body carries the
   budget, so a caller can tell a stall from a refusal.

Both budgets are environment-overridable. If 150s turns out to be too tight
for a genuinely long local generation, raise DUCORN_LOCAL_TIMEOUT rather than
editing this again — but check the ⏱ lines first, because now there are some.
"""
import ast
import shutil
import sys
from datetime import datetime
from pathlib import Path

PROXY = Path("/Users/ducorn/DC/scripts/ducorn_proxy.py")
s = PROXY.read_text(encoding="utf-8")

if "_timeout_for" in s:
    sys.exit("Already patched — the router has per-model timeouts.")


def swap(label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {text.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    return text.replace(old, new, 1)


# ── budgets ──────────────────────────────────────────────────────────────────
s = swap("budgets", s, '''def _bad_request(message, available):''',
         '''# How long to wait for an answer, by where the answer comes from.
#
# One blanket 300s meant a stalled Ollama call burned five minutes before
# anyone found out. A local model that has produced nothing in two and a half
# minutes is stuck behind a reload or a queue, not thinking — failing fast lets
# the caller retry inside its own budget. Remote models keep the long one: a
# large completion legitimately takes minutes.
LOCAL_TIMEOUT = float(os.environ.get("DUCORN_LOCAL_TIMEOUT", "150"))
REMOTE_TIMEOUT = float(os.environ.get("DUCORN_REMOTE_TIMEOUT", "300"))


def _timeout_for(model: str) -> float:
    return LOCAL_TIMEOUT if str(model).startswith("local-") else REMOTE_TIMEOUT


def _bad_request(message, available):''')

# ── timed call ───────────────────────────────────────────────────────────────
s = swap("call", s, '''        try:
            resp = await client.post(f"{LITELLM_URL}/v1/chat/completions",
                                     json=body, headers=headers)
        except httpx.TimeoutException as e:
            print(f"[DuCorn Router] upstream timeout: {e}", flush=True)
            return JSONResponse(
                {"error": {"type": "upstream_timeout",
                           "message": f"LiteLLM at {LITELLM_URL} did not respond "
                                      f"in time serving {chosen!r}."}},
                status_code=504)''',
         '''        budget = _timeout_for(chosen)
        started = time.monotonic()
        try:
            resp = await client.post(f"{LITELLM_URL}/v1/chat/completions",
                                     json=body, headers=headers, timeout=budget)
        except httpx.TimeoutException as e:
            waited = time.monotonic() - started
            print(f"[DuCorn Router] upstream timeout after {waited:.0f}s "
                  f"(budget {budget:.0f}s) serving {chosen!r}: {e}", flush=True)
            return JSONResponse(
                {"error": {"type": "upstream_timeout",
                           "message": f"LiteLLM at {LITELLM_URL} did not respond "
                                      f"within {budget:.0f}s serving {chosen!r}.",
                           "waited_seconds": round(waited, 1),
                           "budget_seconds": budget,
                           "hint": "For a local model this usually means Ollama "
                                   "is reloading or queued behind another run. "
                                   "Raise DUCORN_LOCAL_TIMEOUT only after "
                                   "checking the router's ⏱ lines."}},
                status_code=504)''')

# ── the timing line ──────────────────────────────────────────────────────────
s = swap("timing", s, '''    try:
        return JSONResponse(content=resp.json(), status_code=resp.status_code)''',
         '''    # The number nobody was writing down. Every "is it looping / is Ollama
    # overloaded / is the context too long" question this week was one line of
    # timing data away from an answer.
    elapsed = time.monotonic() - started
    if elapsed > budget * 0.5:
        print(f"[DuCorn Router] ⏱ SLOW {chosen} {elapsed:.0f}s of a "
              f"{budget:.0f}s budget", flush=True)
    else:
        print(f"[DuCorn Router] ⏱ {chosen} {elapsed:.1f}s", flush=True)

    try:
        return JSONResponse(content=resp.json(), status_code=resp.status_code)''')

if "\nimport time" not in s and "\nimport time\n" not in s:
    s = swap("import", s, "import httpx", "import time\nimport httpx")

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = PROXY.with_name(f"ducorn_proxy.backup-timing-{stamp}.py")
shutil.copy2(PROXY, backup)
PROXY.write_text(s, encoding="utf-8")

try:
    ast.parse(s)
except SyntaxError as e:
    shutil.copy2(backup, PROXY)
    sys.exit(f"SYNTAX ERROR ({e}) — reverted from {backup}")

for must in ("import os", "import time", "import httpx"):
    if not any(l.strip().startswith(must) for l in s.splitlines()[:40]):
        shutil.copy2(backup, PROXY)
        sys.exit(f"{must} missing from the top of {PROXY.name} — reverted "
                 f"from {backup}")

print("applied: local 150s / remote 300s, every call timed, timeouts say how long")
print(f"backup:  {backup.name}")
print()
print("Restart the router, then watch the timings:")
print("  launchctl kickstart -k gui/$(id -u)/com.ducorn.router")
print("  tail -f ~/DC/logs/router.log | grep '⏱'")
