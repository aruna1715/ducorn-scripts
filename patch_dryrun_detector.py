#!/usr/bin/env python3
"""
The dry run reported a carried rejection on a run that has never happened.

    cd ~/DC && python3 scripts/patch_dryrun_detector.py            show
    cd ~/DC && python3 scripts/patch_dryrun_detector.py --apply    do it

── WHAT IT SAID ─────────────────────────────────────────────────────────────

    what is in the prompt:
       no  pathway rules
       ...
      yes  a prior rejection

for ducorn-admin-rebuild-p1-config — a slug with no product directory, no
checkpoint and no previous attempt. There was nothing to carry.

── WHY ──────────────────────────────────────────────────────────────────────

Every flag is tested against the WHOLE prompt, and the whole prompt includes
the skill's own instructions. Skill 01's template contains the line

    VERDICT: FAIL — <reason>

telling the agent what format to write its verdict in. The detector's pattern
is REJECTED|VERDICT: FAIL, so it matched the instruction that teaches the
format, and reported it as evidence of a previous failure.

── WHY IT MATTERS MORE THAN A COSMETIC BUG ──────────────────────────────────

This flag exists to answer one question before a paid run: "is this build
about to be told about a rejection?" A carried ghost rejection has cost real
money here before — it is why supersede_stale_reviews and the checkpoint
invalidation exist. A detector that says yes on every run cannot answer that
question, and worse, it makes the real case invisible: when a rejection IS
being carried, the line looks exactly the same.

── THE FIX ──────────────────────────────────────────────────────────────────

Split the flags by where the thing being detected actually lives.

    in the INSTRUCTIONS    pathway rules, deployment contract, UI test
                           contract — appended to the skill text
    in the CONTEXT         founder brief, stack context, a prior rejection —
                           assembled from disk and checkpoints

_report_prompt already receives `context` separately. The context-derived
flags now search that, so a phrase in the skill template cannot masquerade as
evidence about this run.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
RUNNER = DC / "ducorn" / "skill_runner.py"
TAG = "dryrundetect"

OLD = '''    print("\\n  what is in the prompt:")
    for label, pattern in [
        ("pathway rules", r"THIS IS A DOCUMENT|NO USER INTERFACE|COMMAND-LINE"),
        ("founder brief", r"## Founder Brief"),
        ("stack context", r"RULES FOR USING THE ABOVE"),
        ("deployment contract", r"DEPLOYMENT CONTRACT|service\\.json"),
        ("UI test contract", r"Playwright|test_ui\\.py"),
        ("a prior rejection", r"REJECTED|VERDICT: FAIL"),
    ]:
        hit = bool(_re.search(pattern, full_prompt, _re.I))
        print(f"    {'yes' if hit else ' no'}  {label}")'''

NEW = '''    print("\\n  what is in the prompt:")
    # WHERE each thing lives decides where to look for it.
    #
    # Searching the whole prompt made "a prior rejection" true on every run:
    # skill 01's own template contains "VERDICT: FAIL — <reason>", teaching
    # the agent the output format, and the detector read that as evidence of
    # a previous failure. A flag that is always yes cannot warn about the
    # case it exists for — a genuinely carried rejection looked identical.
    #
    #   instructions : appended to the skill text by _skill_text
    #   context      : assembled from disk, checkpoints and earlier skills
    for label, pattern, haystack in [
        ("pathway rules",
         r"THIS IS A DOCUMENT|NO USER INTERFACE|COMMAND-LINE", full_prompt),
        ("deployment contract",
         r"DEPLOYMENT CONTRACT|service\\.json", full_prompt),
        ("UI test contract", r"Playwright|test_ui\\.py", full_prompt),
        ("phase context", r"THIS IS PHASE \\d+ OF", context),
        ("founder brief", r"## Founder Brief", context),
        ("stack context", r"RULES FOR USING THE ABOVE", context),
        ("a prior rejection", r"REJECTED|VERDICT: FAIL", context),
    ]:
        hit = bool(_re.search(pattern, haystack, _re.I))
        print(f"    {'yes' if hit else ' no'}  {label}")'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

if not RUNNER.is_file():
    sys.exit(f"NOTHING DONE — {RUNNER} is not there")

src = RUNNER.read_text(encoding="utf-8")
print("patch_dryrun_detector\n")

if "phase context" in src and "haystack" in src:
    sys.exit("NOTHING DONE — the detector already splits by location.")

n = src.count(OLD)
print(f"  {'ok ' if n == 1 else '!! '}the detector block  ({n} match)")
if n != 1:
    sys.exit("\nNOTHING DONE — the anchor did not match exactly once.")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(RUNNER, RUNNER.with_suffix(f".backup-{TAG}-{stamp}.py"))
RUNNER.write_text(src.replace(OLD, NEW, 1), encoding="utf-8")
print(f"\nwrote {RUNNER.name}, backup tagged {TAG}-{stamp}")

r = subprocess.run([sys.executable, "-m", "py_compile", str(RUNNER)],
                   capture_output=True, text=True)
if r.returncode != 0:
    sys.exit(f"⚠️  it does not parse — restore the backup:\n{r.stderr[-400:]}")

# The point of the fix, checked: the skill template's own VERDICT line must
# no longer register as a carried rejection.
probe = r'''
import re
INSTRUCTIONS = "Write your verdict as:\nVERDICT: FAIL - <reason>\n"
CONTEXT_CLEAN = "THIS IS PHASE 1 OF 'x'\nBuild the configuration tab.\n"
CONTEXT_CARRIED = CONTEXT_CLEAN + "\nThe previous attempt was REJECTED: no tests.\n"
pat = r"REJECTED|VERDICT: FAIL"
whole_clean = INSTRUCTIONS + CONTEXT_CLEAN
bad = []
if not re.search(pat, whole_clean, re.I):
    bad.append("the fixture does not reproduce the false positive")
if re.search(pat, CONTEXT_CLEAN, re.I):
    bad.append("a clean context still reports a rejection")
if not re.search(pat, CONTEXT_CARRIED, re.I):
    bad.append("a real carried rejection is no longer detected")
print("DETECT_OK" if not bad else "DETECT_BAD " + "; ".join(bad))
'''
r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
if "DETECT_OK" not in r.stdout:
    sys.exit(f"⚠️  {(r.stdout + r.stderr).strip()[-300:]}")

print("""
verified: skill_runner.py parses, a clean context no longer reports a
rejection, and a real carried rejection still does.

Look again, for free:
  python3 scripts/start_phase.py ducorn-admin-rebuild --dry-run

'a prior rejection' should now read no, and a new line 'phase context'
should read yes.
""")
