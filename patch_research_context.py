#!/usr/bin/env python3
"""
Stop the stack inventory from being pasted into every PRD.

── WHAT THE LAST RUN PRODUCED ───────────────────────────────────────────────

The fixture product's PRD came back looking like this:

    # pipeline-test-product-e2e
    # DuCorn Stack Context — Auto-collected
    ## 3. Environment Variable Keys
    LITELLM_KEY_SAGE
    SLACK_BOT_TOKEN
    UI_PASSWORD
    ...
    ## 4. Agent Config
    { "ATLAS": "claude-sonnet", "SAGE ...

That is a description of our machine, not of the product. It got there because
node_research appends this to every research task:

    context_path = PRODUCTS_DIR / "docs" / "ducorn-stack-context.md"
    context = context_path.read_text() if context_path.exists() else ""
    ...
    Reference — the DuCorn stack this runs on:
    {context[:2000]}

First, to be clear about what this is and is not: those are variable NAMES,
not values, and I checked every document in docs/ — the four others that
mention them do so legitimately, because they are products about our own
spend and services. Nothing leaked. This is a prompt-hygiene problem, not an
incident.

It is still three distinct mistakes:

  1. IT GOES TO EVERY PRODUCT. Most DuCorn products have nothing to do with
     the DuCorn stack. A customer-facing product gets two thousand characters
     of launchd plists and service ports as "reference".

  2. IT IS NOT MARKED AS REFERENCE. The brief has BINDING markers around it;
     this block has a one-line label. A local model reading a document
     immediately before writing a document treats it as material to reuse —
     which is exactly what happened.

  3. context[:2000] IS AN ARBITRARY CUT. It happens to land in the middle of
     the credential inventory, so the one section with no business being in a
     product document is the one guaranteed to make it in.

── THE FIX ──────────────────────────────────────────────────────────────────

    _stack_context()       reads the file with credential-ish sections
                           dropped — never sent to a model at all, whoever
                           asks and whatever the product.

    _stack_context_for()   returns it only when the founder's brief is
                           actually about the DuCorn stack. Everything else
                           gets nothing, which is the right amount.

    the task block         is fenced and labelled REFERENCE ONLY, with an
                           explicit instruction not to reproduce it — the same
                           treatment the brief gets for the opposite reason.
"""
import ast
import shutil
import sys
from datetime import datetime
from pathlib import Path

FLOW = Path("/Users/ducorn/DC/ducorn/flows/langgraph_flow.py")
s = FLOW.read_text(encoding="utf-8")

if "_stack_context_for" in s:
    sys.exit("Already patched — the stack context is scoped.")


def swap(label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {text.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    return text.replace(old, new, 1)


# ── helpers, next to the node that uses them ─────────────────────────────────
s = swap("helpers", s, "def node_research(state: DuCornState) -> DuCornState:",
         '''# Sections of the stack context that never go to a model. Matched on the
# heading, so a regenerated context file with the same section names is still
# filtered — the file is auto-collected and will change shape without notice.
_CONTEXT_SKIP = ("environment variable", "credential", "token", "password",
                 "api key", "secret")

# A product is "about the stack" if its brief says so. Nothing else needs to
# know what machine it runs on.
_STACK_WORDS = r"\\bducorn\\b|\\blaunchd\\b|litellm|langgraph|ollama|skill_runner|the stack"


def _stack_context(max_chars: int = 2000) -> str:
    """ducorn-stack-context.md with the credential inventory removed."""
    path = PRODUCTS_DIR / "docs" / "ducorn-stack-context.md"
    if not path.exists():
        return ""
    kept, skipping = [], False
    for line in path.read_text(errors="replace").splitlines():
        if line.startswith("## "):
            skipping = any(w in line.lower() for w in _CONTEXT_SKIP)
        if not skipping:
            kept.append(line)
    return "\\n".join(kept).strip()[:max_chars]


def _stack_context_for(brief: str, max_chars: int = 2000) -> str:
    """
    The stack context, but only for products that are part of the stack.

    It used to be appended to every research task. The PRD for a fixture
    product came back as an inventory of our services because a local model
    reading a document right before writing one will reuse it.
    """
    if not brief or not re.search(_STACK_WORDS, brief, re.I):
        return ""
    return _stack_context(max_chars)


def node_research(state: DuCornState) -> DuCornState:''')

# ── the node reads the scoped version ────────────────────────────────────────
s = swap("read", s, '''        # Read stack context
        context_path = PRODUCTS_DIR / "docs" / "ducorn-stack-context.md"
        context = context_path.read_text() if context_path.exists() else ""''',
         '''        # Reference material, for the products that are part of the stack and
        # for no others. Credential sections are stripped before a model sees
        # any of it.
        context = _stack_context_for(founder_brief)
        if context:
            print(f"📚 stack context attached ({len(context)} chars) — this "
                  f"brief refers to the DuCorn stack")''')

# ── the task fences it ───────────────────────────────────────────────────────
s = swap("task block", s, '''The PRD MUST include one of these type markers:
**Type:** software | document | dashboard | api

Reference — the DuCorn stack this runs on:
{context[:2000]}""",''',
         '''The PRD MUST include one of these type markers:
**Type:** software | document | dashboard | api
{_context_block}""",''')

s = swap("block builder", s, '''        task = Task(
            description=f"""Expand the founder's brief below into a complete PRD''',
         '''        # Fenced and labelled, for the same reason the brief is: an unlabelled
        # document sitting next to the instructions gets treated as material.
        _context_block = ""
        if context:
            _context_block = f"""

============================ REFERENCE ONLY — DO NOT COPY ======================
The infrastructure this product would run inside. Use it to get service names,
ports and versions right. It is NOT part of the product and NONE of it belongs
in the PRD — the PRD describes the product, not the machine.

{context}
============================== END OF REFERENCE ================================"""

        task = Task(
            description=f"""Expand the founder's brief below into a complete PRD''')

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = FLOW.with_name(f"langgraph_flow.backup-ctx-{stamp}.py")
shutil.copy2(FLOW, backup)
FLOW.write_text(s, encoding="utf-8")

try:
    ast.parse(s)
except SyntaxError as e:
    shutil.copy2(backup, FLOW)
    sys.exit(f"SYNTAX ERROR ({e}) — reverted from {backup}")

# The helpers use re at module scope; make sure it is imported there.
if not any(l.strip() in ("import re", "import re, os", "import os, re")
           for l in s.splitlines()[:80]):
    shutil.copy2(backup, FLOW)
    sys.exit(f"`re` is not imported near the top of {FLOW.name} — reverted "
             f"from {backup}")

print("applied: stack context is filtered, scoped to stack products, and fenced")
print(f"backup:  {backup.name}")
print()
print("Check what a non-stack brief now gets (should be empty):")
print("  cd ~/DC/ducorn && .venv/bin/python -c \"import sys; "
      "sys.path.insert(0,'.'); from flows.langgraph_flow import _stack_context_for, "
      "_stack_context; "
      "print('non-stack brief ->', repr(_stack_context_for('a temperature converter'))); "
      "print('stack brief     ->', len(_stack_context_for('rebuild the DuCorn dashboard')), 'chars'); "
      "print('credentials leaked ->', 'LITELLM_KEY' in _stack_context(999999))\"")
