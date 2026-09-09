#!/usr/bin/env python3
"""
Every non-build skill fails, whatever it produced.

    cd ~/DC && python3 scripts/patch_skill_verdict.py            show
    cd ~/DC && python3 scripts/patch_skill_verdict.py --apply    do it

Needs scripts/patchlib.py.

── WHAT IT SAID ─────────────────────────────────────────────────────────────

    ❌ Skill 01 — PRD Analysis FAILED
    VERDICT: FAIL — produced only 6043 chars of substance

6,043 characters. The threshold is 200. The message is describing a test the
output passed.

── THE CAUSE ────────────────────────────────────────────────────────────────

    if len(body) >= 200:
        status, verdict = "pass", f"VERDICT: PASS — {len(body)} chars produced"

    if skill_num == BUILD_SKILL and status == "pass":
        _bstat, _bwhy = build_produced_code(topic, since=_RUN_STARTED)
        if _bstat != "pass":
            status, verdict = "fail", _bwhy
        else:
            print(f"🧱 {_bwhy}", flush=True)
    else:
        status, verdict = "fail", f"VERDICT: FAIL — produced only {len(body)} chars"

The final `else` belongs to `if skill_num == BUILD_SKILL`, not to
`if len(body) >= 200`. So the length test sets "pass", and then every skill
that is NOT the build skill falls into that else and is overwritten with
"fail" — carrying a message written for a different branch, which is why the
reason contradicts the number in it.

Skill 01 did its job. It was marked failed for not being skill 04.

── HOW IT GOT THERE ─────────────────────────────────────────────────────────

The comment above the block says it: build_produced_code "has existed all
along and nothing ever called it". Wiring it in added an if/else around code
that already ended in an else, and the new one captured the old one's tail.
It is the shape of the mistake, not the reasoning — a build IS judged by
what it wrote, and that part is right and stays.

── THE FIX ──────────────────────────────────────────────────────────────────

Give the length test its own else, and leave the build check as a separate
statement that can only ever downgrade a pass. Two questions, two
statements: "did it produce anything" and "did the build write code".
"""
from __future__ import annotations

import argparse
import ast
import shutil
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
RUNNER = DC / "ducorn" / "skill_runner.py"
LIB = DC / "scripts" / "patchlib.py"
TAG = "verdictelse"

OLD = '''            if len(body) >= 200:
                status, verdict = "pass", f"VERDICT: PASS — {len(body)} chars produced"

            # A build is judged by what it WROTE, not by how much it said
            # about what it read. build_produced_code has existed all along
            # and nothing ever called it.
            if skill_num == BUILD_SKILL and status == "pass":
                _bstat, _bwhy = build_produced_code(topic, since=_RUN_STARTED)
                if _bstat != "pass":
                    status, verdict = "fail", _bwhy
                else:
                    print(f"🧱 {_bwhy}", flush=True)
            else:
                status, verdict = "fail", f"VERDICT: FAIL — produced only {len(body)} chars of substance"'''

NEW = '''            # Did it produce anything? One question, one if/else.
            #
            # The else used to belong to the BUILD_SKILL test below, so a
            # skill that passed this check was immediately overwritten with
            # "fail" for the sole offence of not being the build skill —
            # reported as "produced only 6043 chars of substance", a message
            # from this branch attached to that one.
            if len(body) >= 200:
                status, verdict = "pass", f"VERDICT: PASS — {len(body)} chars produced"
            else:
                status, verdict = "fail", f"VERDICT: FAIL — produced only {len(body)} chars of substance"

            # A build is judged by what it WROTE, not by how much it said
            # about what it read. build_produced_code has existed all along
            # and nothing ever called it.
            #
            # Separate statement, and it can only ever DOWNGRADE a pass. It
            # has no else: a skill that is not the build skill is not this
            # check's business.
            if skill_num == BUILD_SKILL and status == "pass":
                _bstat, _bwhy = build_produced_code(topic, since=_RUN_STARTED)
                if _bstat != "pass":
                    status, verdict = "fail", _bwhy
                else:
                    print(f"🧱 {_bwhy}", flush=True)'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in (RUNNER, LIB):
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

sys.path.insert(0, str(DC / "scripts"))
from patchlib import py_ok, PatchCheckFailed   # noqa: E402

src = RUNNER.read_text(encoding="utf-8")
print("patch_skill_verdict\n")

if "One question, one if/else." in src:
    sys.exit("NOTHING DONE — the verdict block is already split.")

n = src.count(OLD)
print(f"  {'ok ' if n == 1 else '!! '}the verdict block  ({n} match)")
if n != 1:
    sys.exit("\nNOTHING DONE — the anchor did not match exactly once.")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(RUNNER, RUNNER.with_suffix(f".backup-{TAG}-{stamp}.py"))
RUNNER.write_text(src.replace(OLD, NEW, 1), encoding="utf-8")
print(f"\nwrote {RUNNER.name}, backup tagged {TAG}-{stamp}")

after = RUNNER.read_text(encoding="utf-8")
try:
    tree = py_ok(after, "skill_runner.py")
except PatchCheckFailed as e:
    sys.exit(f"⚠️  {e} — restore the backup.")

# STRUCTURE, from the parse tree. The bug was which statement an else hung
# off, and no amount of text matching can see that — both spellings contain
# the same lines in the same order.
length_ifs, build_ifs = [], []
for node in ast.walk(tree):
    if not isinstance(node, ast.If):
        continue
    test = ast.dump(node.test)
    if "'body'" in test and "200" in test:
        length_ifs.append(node)
    elif "BUILD_SKILL" in test:
        build_ifs.append(node)

if len(length_ifs) != 1:
    sys.exit(f"⚠️  found {len(length_ifs)} length tests — restore the backup.")
if len(build_ifs) != 1:
    sys.exit(f"⚠️  found {len(build_ifs)} BUILD_SKILL tests — restore the "
             f"backup.")
if not length_ifs[0].orelse:
    sys.exit("⚠️  the length test still has no else of its own — restore the "
             "backup.")
if build_ifs[0].orelse:
    sys.exit("⚠️  the BUILD_SKILL test still carries an else — that is the "
             "bug. Restore the backup.")
print("verified: the length test owns its else, and the BUILD_SKILL test has "
      "none.")

# And the behaviour, on the four cases that matter.
probe = r'''
BUILD_SKILL = "04"
def verdict(skill_num, body, wrote_code=True):
    status = None
    if len(body) >= 200:
        status, v = "pass", f"PASS {len(body)}"
    else:
        status, v = "fail", f"FAIL only {len(body)}"
    if skill_num == BUILD_SKILL and status == "pass":
        if not wrote_code:
            status, v = "fail", "FAIL no code"
    return status
bad = []
if verdict("01", "x" * 6043) != "pass":
    bad.append("a long non-build skill still fails")
if verdict("01", "x" * 10) != "fail":
    bad.append("a short skill now passes")
if verdict("04", "x" * 6043, wrote_code=True) != "pass":
    bad.append("a build that wrote code fails")
if verdict("04", "x" * 6043, wrote_code=False) != "fail":
    bad.append("a build that wrote NOTHING now passes")
print("VERDICT_OK" if not bad else "VERDICT_BAD " + "; ".join(bad))
'''
import subprocess  # noqa: E402
r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
if "VERDICT_OK" not in r.stdout:
    sys.exit(f"⚠️  {(r.stdout + r.stderr).strip()[-300:]}")
print("          a long skill passes, a short one fails, and a build that "
      "wrote nothing still fails.")

print("""
Skill 01 already produced its analysis and it is on disk:
  products/ducorn-admin-rebuild/skill-01-prd-analysis.md   (6,159 bytes)

but its checkpoint records a failure, so a resume would re-run it. That is
one paid call, not a whole phase. Resume the build from the dashboard, or:

  curl -sX POST localhost:8000/pipeline/resume/ducorn-admin-rebuild-p1-config \\
       -H "x-api-key: $DUCORN_API_TOKEN"
""")
