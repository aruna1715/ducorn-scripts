#!/usr/bin/env python3
"""
The last failing test: one assertion, one word's case.

    cd ~/DC && python3 scripts/patch_masthead_assert.py            show
    cd ~/DC && python3 scripts/patch_masthead_assert.py --apply    do it

── WHAT IS LEFT ─────────────────────────────────────────────────────────────

    AssertionError: assert 'DuCorn Admin' in
        'DUCORN ADMIN\\nV1.0 · PHASE 1 · LOCALHOST:8099\\nONLINE\\nTHEME'

.masthead-wordmark carries `text-transform: uppercase`, so inner_text()
returns what is RENDERED, not what is in the markup. The page is correct; the
assertion compares against the source spelling.

24 of 25 tests pass. This is the twenty-fifth.

── WHY A HUMAN IS FIXING IT ─────────────────────────────────────────────────

Not because the loop failed — it worked. QA went 14 failures, then 12, then
1, diagnosing a genuine Chromium behaviour (url-embedded Basic auth is not
sent on fetches; http_credentials is required) on the way. REX fixed it and
never touched main.py or index.html.

It is being fixed by hand because another full cycle costs a build, a code
review and a QA run to change one word, and QA itself recommended exactly
this: "one-line fix required in test file only. Product code is correct."

── AFTER THIS ───────────────────────────────────────────────────────────────

Run skill 06 ALONE. Resuming the pipeline would re-run 04 and 05 as well,
because a QA rejection is recorded against them — which is right when the
build is at fault and wasteful when it is not.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
T = DC / "ducorn-products" / "products" / "ducorn-admin-rebuild" / "tests" / "test_ui.py"
TAG = "masthead"

OLD = '''            assert "DuCorn Admin" in text'''

NEW = '''            # inner_text() returns RENDERED text and .masthead-wordmark is
            # text-transform: uppercase, so this is "DUCORN ADMIN" on the
            # page and "DuCorn Admin" in the markup. Compare case-insensitively:
            # the test is about the wordmark being present, not about how CSS
            # chose to draw it.
            assert "ducorn admin" in text.lower()'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

if not T.is_file():
    sys.exit(f"NOTHING DONE — {T} is not there")

src = T.read_text(encoding="utf-8")
print("patch_masthead_assert\n")

if 'in text.lower()' in src:
    sys.exit("NOTHING DONE — the assertion is already case-insensitive.")

n = src.count(OLD)
print(f"  {'ok ' if n == 1 else '!! '}the masthead assertion  ({n} match)")
if n != 1:
    sys.exit("\nNOTHING DONE — the anchor did not match exactly once.")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(T, T.with_suffix(f".backup-{TAG}-{stamp}.py"))
T.write_text(src.replace(OLD, NEW, 1), encoding="utf-8")
print(f"\nwrote {T.name}, backup tagged {TAG}-{stamp}")

import ast  # noqa: E402
try:
    ast.parse(T.read_text(encoding="utf-8"))
except SyntaxError as e:
    sys.exit(f"⚠️  line {e.lineno}: {e.msg} — restore the backup.")

# The assertion must still ASSERT something. A test weakened into `assert
# True` passes and pins nothing.
after = T.read_text(encoding="utf-8")
if 'assert "ducorn admin" in text.lower()' not in after:
    sys.exit("⚠️  the replacement did not land as expected — restore the "
             "backup.")
print("verified: test_ui.py parses and the assertion still checks the "
      "wordmark.")

print("""
Now run QA ALONE — not the pipeline, which would rebuild and re-review:

  cd ~/DC/ducorn && .venv/bin/python skill_runner.py \\
      --topic ducorn-admin-rebuild-p1-config --skill 06

If it passes, the checkpoint records it and RESUME on the dashboard carries
the phase on to gate 3 without re-running anything paid.
""")
