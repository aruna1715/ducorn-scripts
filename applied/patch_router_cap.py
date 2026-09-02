#!/usr/bin/env python3
"""
Bound how much a local model is allowed to say, so a loop cannot be endless.

── WHAT OLLAMA IS DOING RIGHT NOW ───────────────────────────────────────────

    slot print_timing: id 0 | task 18505 | n_decoded = 147538, tg = 29.70 t/s
    slot operator(): id 0 | task 18505 | slot context shift,
                     n_keep = 5, n_left = 32762, n_discard = 16381

One request. A hundred and forty-seven thousand tokens generated, and still
going. At thirty tokens a second that is over eighty minutes of continuous
output from a single call — and `context shift` is llama.cpp saying the 32k
window filled, so it threw away half and carried on. There is no natural end
to this. It will not stop.

Exactly one task in the whole log ever did this: 18505. It is not a pattern,
it is one runaway holding slot 0 — and while it holds the slot, every other
request queues behind it, waits out the router's 150s budget, and comes back
504. Then LiteLLM's `num_retries: 3` tries again, three more times.

So the timeouts were never the problem, and neither was the loop I fixed
earlier, and neither was the prompt. This one stuck generation has been
underneath all of it. Restarting the router does nothing, because the runaway
lives in the Ollama server.

── WHY IT COULD HAPPEN AT ALL ───────────────────────────────────────────────

Nothing anywhere caps the length of a local generation. litellm_config.yaml
sets no max_tokens for local-fast, and no caller sets one, so llama3.1 that
falls into a repetition loop generates until something external stops it.
Nothing external was watching.

── THE FIX ──────────────────────────────────────────────────────────────────

The router already sees every request and knows which model it is going to.
It now clamps max_tokens for local models. In the router rather than in
litellm_config.yaml deliberately: it applies whoever calls and whatever they
forget to set, and it is code that can be tested.

The number is not arbitrary. Ollama is measurably producing ~30 tokens/second
on this machine, and the local budget is 150 seconds, so anything above about
4,500 tokens cannot finish inside the timeout anyway:

    150s × 30 tok/s ≈ 4,500 tokens        cap: 4,096   (~137s worst case)

A PRD from llama3.1 runs 1,000–2,500 tokens, so this is roughly double what
the work needs and still inside the budget. A runaway now ends in a truncated
answer the agent can react to, instead of an endless one nobody can see.

Both numbers are environment-overridable, and they should move together — a
cap above budget × throughput just recreates the timeout.

── DO THIS FIRST ────────────────────────────────────────────────────────────

Task 18505 is still running as you read this, and the cap does not apply to a
request already in flight:

    launchctl kickstart -k gui/$(id -u)/com.ducorn.ollama

Until that happens, every call will keep timing out no matter what else is
fixed.
"""
import ast
import shutil
import sys
from datetime import datetime
from pathlib import Path

PROXY = Path("/Users/ducorn/DC/scripts/ducorn_proxy.py")
s = PROXY.read_text(encoding="utf-8")

if "_timeout_for" not in s:
    sys.exit("Apply patch_router_timing.py first — this builds on it. "
             "NOTHING WRITTEN.")
if "LOCAL_MAX_TOKENS" in s:
    sys.exit("Already patched — local generations are capped.")


def swap(label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {text.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    return text.replace(old, new, 1)


s = swap("cap constant", s, '''def _timeout_for(model: str) -> float:''',
         '''# The longest answer a local model may produce.
#
# Ollama measures ~30 tok/s on this machine and the local budget is 150s, so
# anything past ~4,500 tokens cannot finish inside the timeout regardless. A
# PRD from llama3.1 is 1,000–2,500 tokens, so this is about double what the
# work needs. Raise it and you must raise DUCORN_LOCAL_TIMEOUT with it, or the
# cap just becomes a slower timeout.
LOCAL_MAX_TOKENS = int(os.environ.get("DUCORN_LOCAL_MAX_TOKENS", "4096"))


def _cap_local_output(body: dict, model: str) -> str:
    """
    Bound a local generation. Returns a note for the log, or "".

    llama3.1 fell into a repetition loop and produced 147,538 tokens on one
    request, holding Ollama's only slot for over an hour while every other
    call queued behind it and timed out. Nothing capped the length: not the
    config, not the callers. Now the router does, for everyone, whatever they
    forget to set.
    """
    if not str(model).startswith("local-"):
        return ""
    asked = body.get("max_tokens")
    if asked is None:
        body["max_tokens"] = LOCAL_MAX_TOKENS
        return f"max_tokens defaulted to {LOCAL_MAX_TOKENS}"
    try:
        asked = int(asked)
    except (TypeError, ValueError):
        body["max_tokens"] = LOCAL_MAX_TOKENS
        return f"max_tokens was {asked!r}; set to {LOCAL_MAX_TOKENS}"
    if asked > LOCAL_MAX_TOKENS:
        body["max_tokens"] = LOCAL_MAX_TOKENS
        return f"max_tokens clamped {asked} → {LOCAL_MAX_TOKENS}"
    return ""


def _timeout_for(model: str) -> float:''')

s = swap("apply cap", s, '''        body["model"] = chosen
        note = "" if chosen == requested else f" (normalised from {requested!r})"
        print(f"[DuCorn Router] → {chosen}{note}", flush=True)''',
         '''        body["model"] = chosen
        note = "" if chosen == requested else f" (normalised from {requested!r})"
        capped = _cap_local_output(body, chosen)
        print(f"[DuCorn Router] → {chosen}{note}"
              + (f"  [{capped}]" if capped else ""), flush=True)''')

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = PROXY.with_name(f"ducorn_proxy.backup-cap-{stamp}.py")
shutil.copy2(PROXY, backup)
PROXY.write_text(s, encoding="utf-8")

try:
    ast.parse(s)
except SyntaxError as e:
    shutil.copy2(backup, PROXY)
    sys.exit(f"SYNTAX ERROR ({e}) — reverted from {backup}")

# Exercise the capper on the patched file rather than trusting the edit.
tree = ast.parse(s)
seg = next((ast.get_source_segment(s, n) for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "_cap_local_output"),
           None)
if seg is None:
    shutil.copy2(backup, PROXY)
    sys.exit(f"_cap_local_output did not land — reverted from {backup}")

ns = {"os": __import__("os"), "LOCAL_MAX_TOKENS": 4096}
exec(seg, ns)
cap = ns["_cap_local_output"]

cases = [
    ({}, "local-fast", 4096, "defaulted"),
    ({"max_tokens": 200}, "local-fast", 200, "left alone"),
    ({"max_tokens": 999999}, "local-fast", 4096, "clamped"),
    ({"max_tokens": None}, "local-fast", 4096, "defaulted"),
    ({}, "claude-sonnet", None, "remote untouched"),
    ({"max_tokens": 64000}, "claude-opus", 64000, "remote untouched"),
]
print("\nchecking the cap:")
for body, model, expect, label in cases:
    cap(body, model)
    got = body.get("max_tokens")
    ok = got == expect
    print(f"  {'ok  ' if ok else 'FAIL'} {model:14} {label:18} -> {got}")
    if not ok:
        shutil.copy2(backup, PROXY)
        sys.exit(f"expected {expect}, got {got} — reverted from {backup}")

print(f"\napplied: local generations capped at {ns['LOCAL_MAX_TOKENS']} tokens")
print(f"backup:  {backup.name}")
print()
print("KILL THE RUNAWAY FIRST — the cap cannot touch a request already running:")
print("  launchctl kickstart -k gui/$(id -u)/com.ducorn.ollama")
print("  launchctl kickstart -k gui/$(id -u)/com.ducorn.router")
print()
print("Then watch it work:")
print("  tail -f ~/DC/logs/router.log | grep -E '⏱|max_tokens'")
