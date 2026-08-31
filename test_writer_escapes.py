#!/usr/bin/env python3
"""
Tests for the writer-tool escape check.

Run this on the Mac AFTER applying patch_writer_escapes.py:
    cd ~/DC/ducorn && .venv/bin/python ../scripts/test_writer_escapes.py

It imports the real tool module, so a passing run means the file on disk
behaves — not that a copy of the logic in this file behaves.
"""
import sys
from pathlib import Path

sys.path.insert(0, "/Users/ducorn/DC/ducorn")
from tools.DuCornWriterTool import looks_escaped, unescape  # noqa: E402

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        failures.append(name)


print("\n── repair: the real defect ──")
BAD = (r"# Launch Announcement for Ducorn-Run-History\n\n## Introduction\n\n"
       r"Ducorn-Run-History is the latest innovation in data analysis from DuCorn."
       r"\n\n## Key Features\n\n- Advanced analytics for historical data\n"
       r"- User-friendly interface for easy navigation")
check("verdict is repair", looks_escaped(BAD) == "repair", looks_escaped(BAD))
fixed = unescape(BAD)
check("has real headings", fixed.count("\n## ") == 2)
check("no literal escapes left", "\\n" not in fixed)
check("bullet list survived", "\n- Advanced analytics" in fixed)

print("\n── leave alone: legitimate markdown ──")
GOOD = "# Title\n\nSome prose.\n\n## Section\n\n- a\n- b\n"
check("verdict empty", looks_escaped(GOOD) == "")
check("unchanged", unescape(GOOD) == GOOD)

print("\n── leave alone: code that legitimately contains backslash-n ──")
CODE = ('# Notes\n\n'
        'Use a separator:\n\n'
        '```python\n'
        'print("a\\nb")\n'
        'rows = text.split("\\n")\n'
        '```\n\n'
        'That is all.\n')
check("verdict empty", looks_escaped(CODE) == "", looks_escaped(CODE))
check("code untouched", unescape(CODE) == CODE or looks_escaped(CODE) == "")

print("\n── leave alone: regex escapes are not newlines ──")
RX = "# Regex\n\nMatch `\\d+` and `\\w+` and `\\s`.\n\nDone.\n"
check("verdict empty", looks_escaped(RX) == "")
check("unknown escapes preserved", unescape(RX) == RX)

print("\n── refuse: half-escaped ──")
HALF = ("# Title\n\n" + r"Body text that goes on and on \n\n## Section \n\n"
        r"more and more \n\n- item \n- item \n\n### Deeper \n\n" + "x" * 600)
check("verdict is refuse", looks_escaped(HALF) == "refuse", looks_escaped(HALF))

print("\n── boundary: a short one-liner with no escapes is fine ──")
check("verdict empty", looks_escaped("# Just a title") == "")

print("\n── boundary: quotes and tabs repair together ──")
Q = r'# T\n\nHe said \"hi\"\n\n\tindented'
check("verdict is repair", looks_escaped(Q) == "repair")
u = unescape(Q)
check("quotes unescaped", '"hi"' in u)
check("tab unescaped", "\tindented" in u)

print("\n── non-ASCII survives (unicode_escape would have mangled this) ──")
NA = r"# Café\n\nRésumé — naïve\n\n## Ünïcode"
check("verdict is repair", looks_escaped(NA) == "repair")
check("accents intact", "Café" in unescape(NA) and "Résumé" in unescape(NA))

print()
if failures:
    print(f"{len(failures)} FAILED: {', '.join(failures)}")
    sys.exit(1)
print("all checks passed")
