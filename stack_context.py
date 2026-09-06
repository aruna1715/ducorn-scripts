#!/usr/bin/env python3
"""
The DuCorn stack context, and the rules for using it — in one place.

── WHY THIS IS A MODULE ─────────────────────────────────────────────────────

The context file exists so that a product ABOUT the DuCorn stack can be
written from facts instead of from a model's impression of what an AI company
probably runs. It worked, once, in one node:

    langgraph_flow.py:681   node_research   → SAGE got it
    skill_runner.py         node_build      → REX got nothing

REX wrote the documents. The agent-to-model table in section 7.2 says
"not recorded" nine times, and every one of those values was sitting in the
context file the whole run — attached to the researcher and to nobody else.

REX was right to write "not recorded". The rule it was given is the rule that
makes the document trustworthy. The delivery is what failed, and it failed
because the attachment lived inside one node rather than beside the prompt
every skill builds.

Both callers now import from here. There is no second copy to drift.

── WHAT IS STRIPPED ─────────────────────────────────────────────────────────

Whole sections whose heading names a credential. The file is 6,946 characters
and the two "## Credentials" sections are 895 of them, which is why the log
says 6,051 — that is a stripped file, not a truncated one. Nothing here caps
length; the cap that used to exist (SUBJECT_CONTEXT_CHARS = 20000) never bit.
"""
from __future__ import annotations

import re
from pathlib import Path

import os

# Overridable so this can be exercised against a copy of the tree before it
# runs against the real one — the same reason patch_pathways.py takes
# DUCORN_ROOT. Defaults to the Mini's layout.
PRODUCTS_DIR = Path(os.environ.get(
    "DUCORN_PRODUCTS_DIR", "/Users/ducorn/DC/ducorn-products"))
CONTEXT_FILE = PRODUCTS_DIR / "docs" / "ducorn-stack-context.md"

# Sections removed before any model sees the file. Matched on the heading, so
# a whole section goes rather than a line here and there.
SKIP_SECTIONS = ("environment variable", "credential", "token", "password",
                 "api key", "secret")

# A brief that merely RUNS on the stack, versus one that is ABOUT it. The
# distinction matters: attaching an inventory of our services to every research
# task once produced a PRD for a fixture product that was an inventory of our
# services, because a local model reading a document right before writing one
# will reuse it.
STACK_WORDS = (r"\bducorn\b|\blaunchd\b|litellm|langgraph|ollama|"
               r"skill_runner|the stack")

IS_SUBJECT = (
    r"\b(architecture|technology stack|tech stack|stack documentation|"
    r"document(ing|ation)? (the )?(ducorn )?(stack|architecture|system)|"
    r"how (ducorn|the (system|pipeline)) works)\b")

# Background for a product that runs on the stack. Not a limit for a product
# that is about it — see context_for().
BACKGROUND_CHARS = 2000


def stack_context(max_chars: int | None = None) -> str:
    """The context file with credential sections removed."""
    if not CONTEXT_FILE.exists():
        return ""
    kept, skipping = [], False
    for line in CONTEXT_FILE.read_text(errors="replace").splitlines():
        if line.startswith("## "):
            skipping = any(w in line.lower() for w in SKIP_SECTIONS)
        if not skipping:
            kept.append(line)
    text = "\n".join(kept).strip()
    return text[:max_chars] if max_chars else text


def is_subject(brief: str) -> bool:
    """Is this product ABOUT the stack, rather than merely part of it?"""
    return bool(brief and re.search(IS_SUBJECT, brief, re.I))


def mentions_stack(brief: str) -> bool:
    return bool(brief and re.search(STACK_WORDS, brief, re.I))


SUBJECT_RULES = """

RULES FOR USING THE ABOVE — THIS IS YOUR ONLY SOURCE
You cannot read the DuCorn codebase; your file access is limited to this
product's directory. The context above is everything you have.

Every specific claim you write MUST appear in that context, verbatim: every
port, path, version, model name, agent name, filename, command and count.

Where the context does not say, write "not recorded" and move on. Do NOT
infer, do NOT fill a gap with what such a system usually has, and do NOT
soften an absence into a plausible-sounding sentence. A document that invents
one fact cannot be trusted about any of them.

"not recorded" appearing often is not a failure of the document. It is the
document being honest about its source.
"""


def context_for(brief: str, *, rules: bool = True) -> tuple[str, bool]:
    """
    (context, is_subject) for a brief.

    Returns "" for a product that has nothing to do with the stack — most
    products. For one that merely runs on it, a background excerpt. For one
    that is ABOUT it, all of it, because a 2,000-character excerpt of the
    answer is not background: it is most of the answer, withheld, and the
    agent fills the rest by inventing.
    """
    if not mentions_stack(brief):
        return "", False
    if is_subject(brief):
        text = stack_context()
        return (text + SUBJECT_RULES if rules and text else text), True
    return stack_context(BACKGROUND_CHARS), False


# ─────────────────────────────────────────────────────────────────────────────
# The founder brief, which must never be truncated
# ─────────────────────────────────────────────────────────────────────────────

BRIEF_MARKER = "## Founder Brief"


def founder_brief(prd_text: str) -> str:
    """
    The founder's own words out of a PRD, or "".

    SAGE writes the brief into the PRD verbatim under this heading because it
    is binding. In the tech-stack PRD it begins at character 16,735 of 20,847
    — and skill_runner passed the first 3,000 characters to every later skill.
    REX was never shown the constraints it was being held to.
    """
    i = prd_text.find(BRIEF_MARKER)
    if i < 0:
        return ""
    return prd_text[i:].strip()


def prd_for_prompt(prd_text: str, head_chars: int = 3000) -> str:
    """
    A PRD sized for a prompt, with the founder brief always intact.

    The head carries the product definition; the brief carries the
    constraints. Cutting at a fixed offset kept the first and dropped the
    second, which is the opposite of the right trade.
    """
    brief = founder_brief(prd_text)
    if not brief:
        return prd_text[:head_chars]
    head_limit = max(0, prd_text.find(BRIEF_MARKER))
    head = prd_text[:min(head_chars, head_limit)]
    if head_limit > len(head):
        head += f"\n\n… [{head_limit - len(head):,} characters omitted] …\n"
    return head + "\n" + brief


if __name__ == "__main__":
    import sys
    slug = sys.argv[1] if len(sys.argv) > 1 else None
    text = stack_context()
    raw = CONTEXT_FILE.read_text(errors="replace") if CONTEXT_FILE.exists() else ""
    print(f"context file      {len(raw):,} chars")
    print(f"after stripping   {len(text):,} chars   "
          f"({len(raw) - len(text):,} removed as credentials)")
    if not slug:
        print("\npass a slug to see what its PRD would send.")
        raise SystemExit(0)
    p = PRODUCTS_DIR / "docs" / f"{slug}-PRD.md"
    if not p.is_file():
        raise SystemExit(f"no PRD at {p}")
    t = p.read_text(errors="replace")
    b = founder_brief(t)
    sized = prd_for_prompt(t)
    print(f"\n{slug}")
    print(f"  PRD               {len(t):,} chars")
    print(f"  founder brief at  {t.find(BRIEF_MARKER):,}" if b else
          "  founder brief     NOT PRESENT")
    print(f"  old prompt saw    3,000 chars  "
          f"({'brief included' if t.find(BRIEF_MARKER) < 3000 else 'BRIEF CUT'})")
    print(f"  new prompt sends  {len(sized):,} chars  "
          f"({'brief included' if BRIEF_MARKER in sized else 'BRIEF CUT'})")
    ctx, subj = context_for(b or t)
    print(f"  stack context     {len(ctx):,} chars  "
          f"({'SUBJECT — full file + rules' if subj else 'background' if ctx else 'not attached'})")
