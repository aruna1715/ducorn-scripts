#!/usr/bin/env python3
"""
The build gate read a sentence and turned it into a requirement.

    cd ~/DC && python3 scripts/patch_build_manifest.py            show
    cd ~/DC && python3 scripts/patch_build_manifest.py --apply    do it

Needs scripts/patchlib.py.

── WHAT IT SAID ─────────────────────────────────────────────────────────────

    ❌ Skill 04 — Build FAILED
    VERDICT: FAIL — design specifies 10 files, build produced 7; missing:
    ['routers/disk.py', 'routers/health.py', 'routers/logs.py',
     'routers/services.py']

── WHERE THOSE FOUR NAMES CAME FROM ─────────────────────────────────────────

One line of the design document. Line 31:

    > **Note:** Phases 2 and 3 will add files to this same directory
    > (e.g. `routers/services.py`, `routers/health.py`, `routers/logs.py`,
    > `routers/disk.py`). The main.py structure must use APIRouter so those
    > additions are purely additive.

A forward reference, explicitly labelled as phases 2 and 3, inside a
blockquote, introduced by "e.g.". The gate scraped it with

    re.findall(r'[\\w\\-/]+\\.(?:py|js|...)', design.read_text())

over the WHOLE document, and required every path-shaped token in it to exist
on disk. REX built phase 1 correctly — main.py, index.html, requirements.txt,
service.json, .env.example, README.md, tests/test_ui.py — and was failed for
not having built phases 2 and 3 as well.

── THE CLASS OF BUG ─────────────────────────────────────────────────────────

A check that reads prose is checking the wrong text. It is the same fault
that has caught four patch verifications in this repo — "title LIKE" matched
in a docstring, "SELECT" matched inside "NOT a SELECT here" — except this one
is in DuCorn's own gate, where it costs a build rather than a false alarm.

Measured on the actual document:

    whole document   10 names, 4 of which no phase-1 build should contain
    fenced blocks     6 names, every one of them on disk

The four phantoms are exactly the prose-only set.

── THE FIX, IN TWO PARTS ────────────────────────────────────────────────────

1. A DECLARED manifest wins. If the design contains a fenced block tagged
   `files` (or a "FILES TO CREATE" list), those are the deliverables and the
   gate enforces them strictly. This is the same move the deployer already
   made with service.json: "Reading a declaration instead of inferring one."

2. Without one, names are taken only from fenced blocks — a file tree or a
   code listing, never running text — and a mismatch is REPORTED, not fatal.
   A check that cannot tell a requirement from an example has not earned the
   right to fail a build; it has earned the right to say what it noticed.

The gstack skill-02 prompt should be updated to emit the `files` block, which
is what restores full enforcement. That is a separate change in a separate
repo, and this works correctly before and after it.
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
LIB = DC / "scripts" / "patchlib.py"
TAG = "buildmanifest"

OLD = '''    # The design named files. The build should have produced them.
    design = PRODUCTS_DIR / "docs" / f"{topic}-skill02-output.txt"
    if design.exists():
        import re
        named = {m for m in re.findall(r'[\\w\\-/]+\\.(?:py|js|jsx|ts|tsx|html|css|sql|sh)',
                                       design.read_text())}
        have = {p.name for p in src}
        missing = sorted(n for n in named if n.split("/")[-1] not in have)
        if missing:
            return "fail", (f"VERDICT: FAIL — design specifies {len(named)} files, "
                            f"build produced {len(src)}; missing: {missing[:8]}")'''

NEW = '''    # The design named files. The build should have produced them —
    # but only the ones the design DECLARED, not every path-shaped token in
    # its prose.
    #
    # This used to scrape the whole document, so one line of it —
    #
    #   > Note: Phases 2 and 3 will add files to this same directory (e.g.
    #   > routers/services.py, routers/health.py, ...)
    #
    # became four required phase-1 deliverables, and a correct build was
    # failed for not having built the next two phases. A check that reads
    # prose is checking the wrong text.
    design = PRODUCTS_DIR / "docs" / f"{topic}-skill02-output.txt"
    if design.exists():
        import re
        _text = design.read_text(errors="replace")
        _NAME = r'[\\w\\-/]+\\.(?:py|js|jsx|ts|tsx|html|css|sql|sh)'

        # 1. A declared manifest, if the design provides one. Strict.
        _declared = re.findall(r"```files\\b(.*?)```", _text, re.S)
        # 2. Otherwise, fenced blocks only — a file tree or a listing, never
        #    running text. Advisory, because an inferred requirement is not
        #    a requirement.
        _blocks = _declared or re.findall(r"```.*?```", _text, re.S)
        named = {m for b in _blocks for m in re.findall(_NAME, b)}

        have = {p.name for p in src}
        missing = sorted(n for n in named if n.split("/")[-1] not in have)
        if missing and _declared:
            return "fail", (f"VERDICT: FAIL — the design declares {len(named)} "
                            f"files, build produced {len(src)}; missing: "
                            f"{missing[:8]}")
        if missing:
            # Said out loud and not enforced. The reviewer at skill 05 reads
            # this and can judge whether a name was a deliverable or an
            # illustration — which is a judgement, and this is a regex.
            print(f"📋 the design mentions {len(missing)} file(s) the build "
                  f"did not produce: {missing[:8]}\\n"
                  f"   Not enforced: no ```files block declares them. "
                  f"Skill 05 should judge whether they were deliverables.",
                  flush=True)'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in (RUNNER, LIB):
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

sys.path.insert(0, str(DC / "scripts"))
from patchlib import code_only, py_ok, PatchCheckFailed   # noqa: E402

src_txt = RUNNER.read_text(encoding="utf-8")
print("patch_build_manifest\n")

if "```files" in src_txt:
    sys.exit("NOTHING DONE — the gate already reads a declared manifest.")

n = src_txt.count(OLD)
print(f"  {'ok ' if n == 1 else '!! '}the design-file check  ({n} match)")
if n != 1:
    sys.exit("\nNOTHING DONE — the anchor did not match exactly once.")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(RUNNER, RUNNER.with_suffix(f".backup-{TAG}-{stamp}.py"))
RUNNER.write_text(src_txt.replace(OLD, NEW, 1), encoding="utf-8")
print(f"\nwrote {RUNNER.name}, backup tagged {TAG}-{stamp}")

after = RUNNER.read_text(encoding="utf-8")
try:
    py_ok(after, "skill_runner.py")
except PatchCheckFailed as e:
    sys.exit(f"⚠️  {e} — restore the backup.")

code = code_only(after)
if "design.read_text())}" in code:
    sys.exit("⚠️  the whole-document scrape is still there — restore the "
             "backup.")
print("verified: skill_runner.py parses and no longer scrapes the whole "
      "design document.")

# The behaviour, on THIS design document, which is the case that failed.
probe = r'''
import re
DOC = """
Layout:

```
admin/
  main.py
  index.html
```

> **Note:** Phases 2 and 3 will add files (e.g. `routers/services.py`,
> `routers/health.py`).
"""
DECLARED = DOC + "\n```files\nmain.py\nindex.html\nrouters/health.py\n```\n"
NAME = r'[\w\-/]+\.(?:py|js|jsx|ts|tsx|html|css|sql|sh)'
def named(text):
    d = re.findall(r"```files\b(.*?)```", text, re.S)
    blocks = d or re.findall(r"```.*?```", text, re.S)
    return {m for b in blocks for m in re.findall(NAME, b)}, bool(d)
bad = []
n, decl = named(DOC)
if decl: bad.append("a document with no files block was read as declaring one")
if "routers/health.py" in n:
    bad.append("a prose forward reference is still required")
if n != {"main.py", "index.html"}:
    bad.append(f"the fenced tree gave {sorted(n)}")
n2, decl2 = named(DECLARED)
if not decl2: bad.append("an explicit files block was not detected")
if "routers/health.py" not in n2:
    bad.append("a DECLARED file was dropped — declarations must be strict")
print("MANIFEST_OK" if not bad else "MANIFEST_BAD " + "; ".join(bad))
'''
r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
if "MANIFEST_OK" not in r.stdout:
    sys.exit(f"⚠️  {(r.stdout + r.stderr).strip()[-300:]}")
print("          a prose forward reference no longer counts, and a declared "
      "file still does.")

print("""
Skill 04's output is already on disk and the build is complete:
  main.py  index.html  requirements.txt  service.json  .env.example
  README.md  tests/test_ui.py

Do NOT re-run the build to satisfy a gate that was wrong. Re-grade it:

  python3 scripts/regrade_skill.py ducorn-admin-rebuild-p1-config 04
""")
