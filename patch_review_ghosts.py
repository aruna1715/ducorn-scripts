#!/usr/bin/env python3
"""
Supersede review reports by what they ARE, not by a filename we guessed.

    cd ~/DC && python3 scripts/patch_review_ghosts.py            show
    cd ~/DC && python3 scripts/patch_review_ghosts.py --apply    do it

── THE DEFECT ───────────────────────────────────────────────────────────────

supersede_stale_reviews moves the previous run's review reports out of the
builder's reach, so a rejection from a fortnight ago cannot be read as
today's instructions. It matches four exact filenames:

    code-review.md   qa-report.md   qa-report-skill-06.md   content-review.md

The file the content reviewer actually wrote is:

    content-review-20260906.md

so it was never moved. It is still sitting in the product directory now.

The interesting part is WHY the name is wrong. Nothing in skill_runner.py,
langgraph_flow.py or gstack/ writes that filename — I searched. The reviewing
AGENT chose it, and added the date itself. The list is a guess about what a
language model will call its own output, and it will be wrong again: the
next reviewer that writes qa-report-final.md, or code-review-v2.md, gets the
same free pass.

An exact-match list cannot track a filename chosen by a model. That is the
class, and matching four more names would not close it.

── THE FIX ──────────────────────────────────────────────────────────────────

Match on the stem, anchored at the start:

    ^(code-review|qa-report|content-review)  ... .md

which catches content-review-20260906.md, qa-report-final.md and
code-review-v2.md alike. Anchored, so a deliverable named
"api-code-review-guide.md" is untouched — it does not START with a review
stem, and this stack does build engineering documents.

── DELIBERATELY NOT DONE ────────────────────────────────────────────────────

Not '*review*.md'. This pipeline writes documents for a living, and a
document product whose own title contains "review" would have its
deliverable moved into .superseded/ mid-run. The anchored form is the
widest match that cannot eat a product.

Every move is already printed and returned. This adds the count so a run
that moves six ghosts says six.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
RUNNER = DC / "ducorn" / "skill_runner.py"
TAG = "reviewghosts"

OLD = '''_REVIEW_ARTIFACTS = ("code-review.md", "qa-report.md", "qa-report-skill-06.md",
                     "content-review.md")'''

NEW = '''# The reviewing agent names its own output. It wrote
# "content-review-20260906.md" — dated, by its own choice — and the exact-name
# list below never moved it, so the next build read a stale rejection as
# instructions. Nothing in this repo produces that filename; a model did.
#
# So: match the STEM, anchored at the start. content-review-20260906.md,
# qa-report-final.md and code-review-v2.md all match. A deliverable called
# "api-code-review-guide.md" does not — it does not start with a review stem,
# and this pipeline writes engineering documents for a living.
_REVIEW_STEMS = ("code-review", "qa-report", "content-review")
_REVIEW_RE = re.compile(
    r"^(" + "|".join(_REVIEW_STEMS) + r")[-_.0-9a-z]*\\.md$", re.I)'''

OLD_LOOP = '''    for name in _REVIEW_ARTIFACTS:
        p = d / name
        if not p.is_file():
            continue
        try:
            dest.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            p.rename(dest / f"{p.stem}-{stamp}{p.suffix}")
            moved.append(name)
        except OSError as e:
            print(f"⚠️  could not supersede {name}: {e}", flush=True)
    return moved'''

NEW_LOOP = '''    for p in sorted(d.glob("*.md")):
        if not p.is_file() or not _REVIEW_RE.match(p.name):
            continue
        try:
            dest.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            p.rename(dest / f"{p.stem}-{stamp}{p.suffix}")
            moved.append(p.name)
        except OSError as e:
            print(f"⚠️  could not supersede {p.name}: {e}", flush=True)
    if moved:
        print(f"📦 superseded {len(moved)} stale review report(s): "
              f"{', '.join(moved)}", flush=True)
    return moved'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

if not RUNNER.is_file():
    sys.exit(f"NOTHING DONE — {RUNNER} is not there")

src = RUNNER.read_text(encoding="utf-8")

checks = [("the exact-name tuple", OLD), ("the rename loop", OLD_LOOP)]
print("patch_review_ghosts\n")
ok = True
for what, needle in checks:
    n = src.count(needle)
    print(f"  {'ok ' if n == 1 else '!! '}{what}  ({n} match)")
    ok = ok and n == 1

if "import re" not in src.split("\n\n")[0] and not re.search(r"^import re$", src, re.M):
    print("  !! skill_runner.py does not import re")
    ok = False
else:
    print("  ok  re is already imported")

if not ok:
    sys.exit("\nNOTHING DONE — an anchor did not match exactly once.")

# What it would catch right now, on the real directories.
products = DC / "ducorn-products" / "products"
rx = re.compile(r"^(code-review|qa-report|content-review)[-_.0-9a-z]*\.md$", re.I)
found = []
if products.is_dir():
    for prod in sorted(products.iterdir()):
        if not prod.is_dir():
            continue
        for f in sorted(prod.glob("*.md")):
            if rx.match(f.name):
                found.append(f"{prod.name}/{f.name}")

print(f"\n  ghosts this would move on the next run of each product: {len(found)}")
for f in found:
    print(f"      {f}")
if not found:
    print("      (none present right now)")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(RUNNER, RUNNER.with_suffix(f".backup-{TAG}-{stamp}.py"))
RUNNER.write_text(src.replace(OLD, NEW, 1).replace(OLD_LOOP, NEW_LOOP, 1),
                  encoding="utf-8")
print(f"\nwrote {RUNNER.name}, backup tagged {TAG}-{stamp}")

r = subprocess.run([sys.executable, "-m", "py_compile", str(RUNNER)],
                   capture_output=True, text=True)
if r.returncode != 0:
    sys.exit(f"⚠️  it does not parse — restore the backup:\n{r.stderr[-400:]}")

# Prove the regex on the names that matter, including the ones it must NOT eat.
probe = r'''
import re
rx = re.compile(r"^(code-review|qa-report|content-review)[-_.0-9a-z]*\.md$", re.I)
must  = ["code-review.md", "qa-report.md", "qa-report-skill-06.md",
         "content-review.md", "content-review-20260906.md",
         "qa-report-final.md", "code-review-v2.md"]
mustnt = ["api-code-review-guide.md", "ducorn-tech-stack.md", "README.md",
          "reviewing-code.md", "code-review.py"]
bad  = [n for n in must if not rx.match(n)]
bad += [n for n in mustnt if rx.match(n)]
print("RE_OK" if not bad else "RE_BAD " + ", ".join(bad))
'''
r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
if "RE_OK" not in r.stdout:
    sys.exit(f"⚠️  the pattern is wrong: {(r.stdout + r.stderr).strip()}")

print("""
verified: skill_runner.py parses, and the pattern matches all seven review
names — the dated one included — while leaving api-code-review-guide.md,
reviewing-code.md and ordinary deliverables alone.
""")
