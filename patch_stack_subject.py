#!/usr/bin/env python3
"""
When the stack IS the subject, stop handing over 2,000 characters of it.

── THE CAP AND WHY IT EXISTS ────────────────────────────────────────────────

    def _stack_context_for(brief: str, max_chars: int = 2000) -> str:

Two thousand characters is right for what that cap was written for: a product
that merely touches the stack, given a little background so it does not invent
service names. It is fenced as REFERENCE ONLY, and capped precisely so a local
model reading a document right before writing one does not simply reuse it —
which is a failure that has already happened here.

But a document ABOUT the DuCorn architecture is a different thing entirely.
There the stack is not background; it is the subject. Handing an agent 2,000
characters of a 7,000-character machine-generated inventory and asking for a
comprehensive architecture document guarantees invention, because the missing
5,000 characters are exactly what it was asked to write about.

── WHAT CHANGES ─────────────────────────────────────────────────────────────

A brief that is ABOUT the stack — one naming architecture, documentation or
the technology stack itself — gets the whole context, and the fence changes
with it:

    background:   REFERENCE ONLY — DO NOT COPY            (2,000 chars)
    the subject:  THE SUBJECT — every fact you write must appear here (all)

Anything else keeps today's behaviour exactly.

── AND THE INSTRUCTION THAT MATTERS MORE THAN THE SIZE ──────────────────────

An agent writing about a system it cannot read will fill gaps rather than
leave them. So when the stack is the subject, the fence carries an explicit
rule: every port, version, service name and file path must appear in the
context, and anything absent is written as "not recorded" rather than guessed.

That is the difference between a document you can trust and a document that
reads well. For something meant to be a single source of truth, it is the
whole ballgame.
"""
import ast
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

FLOW = Path("/Users/ducorn/DC/ducorn/flows/langgraph_flow.py")
s = FLOW.read_text(encoding="utf-8")

if "_STACK_IS_SUBJECT" in s:
    sys.exit("Already patched — a document about the stack gets all of it.")
if "_stack_context_for" not in s:
    sys.exit("_stack_context_for is not in this flow. NOTHING WRITTEN.")

applied = []


def swap(label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {text.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    applied.append(label)
    return text.replace(old, new, 1)


s = swap("subject detection", s,
         '''def _stack_context_for(brief: str, max_chars: int = 2000) -> str:''',
         '''# A brief that is ABOUT the stack, as opposed to one that merely runs on it.
# "documentation", "architecture", "technology stack" — the words that mean the
# context is the subject rather than the background.
_STACK_IS_SUBJECT = (
    r"\\b(architecture|technology stack|tech stack|stack documentation|"
    r"document(ing|ation)? (the )?(ducorn )?(stack|architecture|system)|"
    r"how (ducorn|the (system|pipeline)) works)\\b")

# All of it. The generated context is around 7,000 characters and every one of
# them is a fact the document is supposed to contain.
SUBJECT_CONTEXT_CHARS = 20000


def _stack_context_for(brief: str, max_chars: int = 2000) -> str:''')

s = swap("give it all", s,
         '''    if not brief or not re.search(_STACK_WORDS, brief, re.I):
        return ""
    return _stack_context(max_chars)''',
         '''    if not brief or not re.search(_STACK_WORDS, brief, re.I):
        return ""
    # When the stack is what the product is ABOUT, a 2,000-character excerpt is
    # not background — it is most of the answer, withheld. The agent fills the
    # rest by inventing, which for a document meant to be authoritative is the
    # worst possible outcome.
    if re.search(_STACK_IS_SUBJECT, brief, re.I):
        return _stack_context(SUBJECT_CONTEXT_CHARS)
    return _stack_context(max_chars)


def stack_is_subject(brief: str) -> bool:
    """Is this product ABOUT the stack, rather than merely part of it?"""
    return bool(brief and re.search(_STACK_IS_SUBJECT, brief, re.I))''')

s = swap("fence and rule", s,
         '''        context = _stack_context_for(founder_brief)
        if context:
            print(f"📚 stack context attached ({len(context)} chars) — this "
                  f"brief refers to the DuCorn stack")''',
         '''        context = _stack_context_for(founder_brief)
        _subject = stack_is_subject(founder_brief)
        if context:
            print(f"📚 stack context attached ({len(context):,} chars) — "
                  + ("the stack is this product's SUBJECT"
                     if _subject else "this brief refers to the DuCorn stack"),
                  flush=True)
        if _subject:
            # An agent writing about a system it cannot read will fill gaps
            # rather than leave them. This is the rule that makes the document
            # trustworthy: no fact that is not in the context.
            context += (
                "\\n\\n"
                "RULES FOR USING THE ABOVE — THIS IS YOUR ONLY SOURCE\\n"
                "You cannot read the DuCorn codebase; your file access is "
                "limited to this product's own directory. Everything you know "
                "about the system is above, and it was generated from the "
                "machine itself, today.\\n"
                "- Every port, version, service name, file path, model name "
                "and table name you write MUST appear above, verbatim.\\n"
                "- If something is not above, write \\"not recorded\\" and move "
                "on. Do not estimate, do not infer from convention, do not "
                "carry over anything you know about similar systems.\\n"
                "- You MAY reason freely about WHY a choice is sound, what the "
                "trade-offs are, and how the pieces relate — that is judgement, "
                "and it is what you are for. Facts are not.\\n"
                "- A document that says \\"not recorded\\" in six places is more "
                "useful than one that is confidently wrong in one.")''')

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = FLOW.with_name(f"langgraph_flow.backup-stacksubject-{stamp}.py")
shutil.copy2(FLOW, backup)
FLOW.write_text(s, encoding="utf-8")


def die(msg):
    shutil.copy2(backup, FLOW)
    sys.exit(f"{msg} — reverted from {backup.name}")


try:
    ast.parse(s)
except SyntaxError as e:
    die(f"SYNTAX ERROR ({e})")

r = subprocess.run([sys.executable, "-m", "pyflakes", str(FLOW)],
                   capture_output=True, text=True)
if [l for l in (r.stdout + r.stderr).splitlines() if "undefined name" in l]:
    die("undefined name:\\n" + r.stdout + r.stderr)
print("syntax and undefined-name checks: clean")

# ── which briefs count as being about the stack ──────────────────────────────
src = FLOW.read_text(encoding="utf-8")
tree = ast.parse(src)
seg = next((ast.get_source_segment(src, n) for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "stack_is_subject"), None)
if seg is None:
    die("stack_is_subject did not land")

import re as _re
# Read the constant with ast, not with a regex over the source. Regexing your
# own emitted code is how a check ends up matching a docstring, or missing a
# line break, or eval'ing something it should have parsed — three of tonight's
# four verification failures were exactly this.
_const = next((n.value for n in tree.body
               if isinstance(n, ast.Assign)
               and getattr(n.targets[0], "id", "") == "_STACK_IS_SUBJECT"), None)
if _const is None:
    die("_STACK_IS_SUBJECT is not a module-level assignment in the patched file")
ns = {"re": _re, "_STACK_IS_SUBJECT": ast.literal_eval(_const)}
exec(seg, ns)
subject = ns["stack_is_subject"]

print("\nwhich briefs get the whole context:")
CASES = [
    ("Build DuCorn Technology Stack Documentation ... architecture diagram",
     True, "TONIGHT'S BRIEF"),
    ("Document the DuCorn architecture for founders and customers",
     True, "the public half of it"),
    ("A tech stack overview of how DuCorn works", True, "phrased loosely"),
    ("Build a spend dashboard reading the LiteLLM database",
     False, "runs on the stack, is not about it"),
    ("A temperature converter", False, "nothing to do with us"),
    ("Add a launchd service for the digest", False,
     "touches the stack — background only, as before"),
]
for brief, want, why in CASES:
    got = subject(brief)
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {'ALL' if got else '2k ':4} "
          f"{brief[:46]:48} {why}")
    if not ok:
        die(f"expected subject={want} for {brief[:40]!r}")

for must in ("SUBJECT_CONTEXT_CHARS", "THIS IS YOUR ONLY SOURCE",
             "not recorded"):
    if must not in src:
        die(f"{must!r} is missing from the patched file")

print("\napplied: " + ", ".join(applied))
print(f"backup:  {backup.name}")
print()
print("Refresh the facts first, then the research phase will attach all of them:")
print("  python3 scripts/stack_facts.py --write")
print()
print("Expect, at research:")
print("  📚 stack context attached (6,933 chars) — the stack is this "
      "product's SUBJECT")
