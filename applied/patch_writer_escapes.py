#!/usr/bin/env python3
"""
Stop DuCornWriterTool writing JSON escape sequences into documents.

WHAT WENT WRONG
---------------
docs/ducorn-run-history-launch.md is a single line, 923 bytes, containing the
two characters \\ and n everywhere a newline belongs. The PDF made from it has
no headings, no paragraphs and no structure — the whole document rendered as
one giant cover title with "\\n\\n##" visible in the text.

The cause is not the PDF engine. An agent emits its tool arguments as JSON; if
that JSON is malformed, CrewAI's lenient fallback parser hands the raw string
through with its escapes intact. The tool then wrote it verbatim and returned
"Content successfully written" — so the pipeline carried on, made a PDF, and
uploaded it to Drive. Silent success on broken input, again.

WHY THIS IS THE RIGHT FIX AND NOT A BANDAID
-------------------------------------------
Repairing the one bad file would leave the tool exactly as able to do it again,
on any run, with any agent. The tool is the only place that sees the bytes
before they become a document, so it is the only place the check belongs.

THE RULE
--------
Deliberately narrow, because a false positive corrupts good content:

  * 2+ literal escapes and 0-1 real newlines  -> repair. A markdown document
    is never one line. There is no ambiguity here.
  * many literal escapes AND real newlines AND an implausibly long line
    -> refuse, and tell the agent to send real newlines. Half-escaped content
    is genuinely ambiguous, so it fails loudly instead of being guessed at.
  * anything else -> write unchanged. A Python snippet containing "\\n" inside
    a string literal is legitimate and must survive untouched.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

TOOL = Path("/Users/ducorn/DC/ducorn/tools/DuCornWriterTool.py")
s = TOOL.read_text(encoding="utf-8")

if "looks_escaped" in s:
    sys.exit("Already patched — looks_escaped() is present.")

HELPERS = '''
# ── Escape detection ─────────────────────────────────────────────────────────
# Single pass so that a literal backslash-backslash is consumed as one unit and
# cannot be re-interpreted. Unknown escapes (\\d in a regex, \\LaTeX) are left
# exactly as they were — this is not a general unescaper and must not act like
# one. codecs 'unicode_escape' is deliberately NOT used: it decodes as latin-1
# and would mangle any non-ASCII character in the document.
_ESCAPES = {"n": "\\n", "t": "\\t", "r": "\\r", '"': '"', "'": "'", "\\\\": "\\\\"}


def unescape(text: str) -> str:
    return re.sub(r"\\\\(.)", lambda m: _ESCAPES.get(m.group(1), m.group(0)), text)


def looks_escaped(content: str) -> str:
    """
    Returns "repair", "refuse" or "" — see the module docstring for the rule.
    """
    esc = len(re.findall(r"\\\\[nt]", content))
    real = content.count("\\n")
    if esc >= 2 and real <= 1:
        return "repair"
    longest = max((len(l) for l in content.split("\\n")), default=0)
    if esc >= 5 and longest > 600:
        return "refuse"
    return ""


'''

# ── 1. import re, and add the helpers above the class ────────────────────────
anchor = '''BASE_DIR = "/Users/ducorn/DC/ducorn-products"
'''
if s.count(anchor) != 1:
    sys.exit(f"ANCHOR MISS [base_dir]: found {s.count(anchor)}, expected 1. Nothing written.")
s = s.replace(anchor, anchor + HELPERS, 1)

anchor = "from crewai.tools import BaseTool\nimport os\n"
if s.count(anchor) != 1:
    sys.exit(f"ANCHOR MISS [imports]: found {s.count(anchor)}, expected 1. Nothing written.")
s = s.replace(anchor, "from crewai.tools import BaseTool\nimport os\nimport re\n", 1)

# ── 2. Check before the write, not after ─────────────────────────────────────
anchor = '''        full.parent.mkdir(parents=True, exist_ok=True)
        try:'''
if s.count(anchor) != 1:
    sys.exit(f"ANCHOR MISS [write]: found {s.count(anchor)}, expected 1. Nothing written.")

s = s.replace(anchor, '''        verdict = looks_escaped(content)
        if verdict == "repair":
            # The whole document arrived on one line. Nothing legitimate looks
            # like this, so repair it and say so in the log — a silent repair
            # would hide how often the agents are emitting bad JSON.
            before = len(content)
            content = unescape(content)
            print(f"[DuCornWriterTool] {filename}: content arrived JSON-escaped "
                  f"({before} bytes on one line) — un-escaped before writing")
        elif verdict == "refuse":
            # Ambiguous: some real newlines, some escaped. Guessing here could
            # corrupt legitimate content, so hand it back to the agent instead
            # of writing something plausible-looking.
            return (f"Error: the content for {filename} mixes real newlines with "
                    f"literal \\\\n escape sequences, so it cannot be written "
                    f"safely. Send the file content as plain text with real "
                    f"line breaks — do not JSON-escape it.")

        full.parent.mkdir(parents=True, exist_ok=True)
        try:''', 1)

backup = TOOL.with_name(f"DuCornWriterTool.backup-escapes-{datetime.now():%Y%m%d-%H%M%S}.py")
shutil.copy2(TOOL, backup)
TOOL.write_text(s, encoding="utf-8")

import ast
try:
    ast.parse(s)
except SyntaxError as e:
    shutil.copy2(backup, TOOL)
    sys.exit(f"SYNTAX ERROR ({e}) — reverted from {backup}")

print("applied: imports, helpers, pre-write check")
print(f"backup:  {backup}")
