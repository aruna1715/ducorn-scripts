#!/usr/bin/env python3
"""
Route every product-directory derivation through product_dir.for_topic.

    cd ~/DC && python3 scripts/patch_build_dir_everywhere.py            show
    cd ~/DC && python3 scripts/patch_build_dir_everywhere.py --apply    do it

Needs scripts/product_dir.py and scripts/patchlib.py.

── WHY, CONCRETELY ──────────────────────────────────────────────────────────

products/ducorn-admin-rebuild-p1-config/ does not exist and never will. The
phase builds into products/ducorn-admin-rebuild/. Resuming the build without
this patch fails at skill 04 with

    VERDICT: FAIL — ducorn-admin-rebuild-p1-config/ was never created

after skills 01, 02 and 03 have been paid for. Before that, skill 04 would
have been told nothing about the design approved at gate 2, because
has_approved_design looks for APPROVED_DESIGN.html in the same missing
directory.

── THE ELEVEN SITES ─────────────────────────────────────────────────────────

    skill_runner.py     6   build_produced_code, the stale-rejection sweep,
                            has_approved_design, the cursor working
                            directory, the UI check, code review
    langgraph_flow.py   2   document publishing, stray-PRD recovery
                        2   the two _git_publish paths (string, not Path)
    product_jail.py     2   its own fallbacks — it already asks build_dir,
                            and now shares the fallback instead of owning it
    DuCornCursorTool    1   the jail root it hands to Cursor
    DuCornDeployTool    1   "❌ No such product"

Each becomes _product_dir(topic), a four-line helper that imports
product_dir INSIDE the function. Deliberately not a module-level import:
langgraph_flow already carries a comment about that — "a new module-level
name in a file that does not already have it is how the activity API went
down earlier tonight".

── WHAT DOES NOT CHANGE ─────────────────────────────────────────────────────

Behaviour for every standalone product. for_topic returns
products/<topic>/ for anything that is not a phase, which is every product
built before epics existed and most built after.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
PD = DC / "scripts" / "product_dir.py"
LIB = DC / "scripts" / "patchlib.py"
TAG = "builddir"

HELPER = '''

def _product_dir(topic):
    """
    Where this topic's files belong. A phase builds into its EPIC's
    directory; everything else into one of its own name.

    scripts/product_dir.py holds the rule — this used to be
    PRODUCTS_DIR / "products" / topic in eleven places, all of which were
    wrong for a phase. Imported inside the function on purpose: a new
    module-level name in a file that does not already have one is how the
    activity API went down.
    """
    from product_dir import for_topic
    return for_topic(topic)

'''

OLD_PATH = 'PRODUCTS_DIR / "products" / topic'
NEW_PATH = '_product_dir(topic)'

FILES = [
    # path, anchor to insert the helper after, expected substitutions
    (DC / "ducorn" / "skill_runner.py",
     'PRODUCTS_DIR = Path("/Users/ducorn/DC/ducorn-products")', 6),
    (DC / "ducorn" / "flows" / "langgraph_flow.py",
     'PRODUCTS_DIR = Path("/Users/ducorn/DC/ducorn-products")', 2),
    (DC / "ducorn" / "tools" / "product_jail.py",
     'PRODUCTS_DIR = Path("/Users/ducorn/DC/ducorn-products").resolve()', 2),
]

# Sites whose spelling differs, done one by one.
ONE_OFFS = [
    (DC / "ducorn" / "tools" / "DuCornCursorTool.py",
     '    allowed = (Path(PRODUCTS_DIR) / "products" / topic).resolve()',
     '    allowed = _product_dir(topic)',
     'PRODUCTS_DIR = "/Users/ducorn/DC/ducorn-products"'),
    (DC / "ducorn" / "tools" / "DuCornDeployTool.py",
     '            product_dir = Path(f"/Users/ducorn/DC/ducorn-products/products/{slug}")',
     '            product_dir = _product_dir(slug)',
     'NEXT_PORT_START = 8090  # Start allocating from here'),
]

# The git paths are strings, not Paths.
GIT_OLD = '''            _git_publish(f"products/{topic}/", f"feat(rex): {topic} sources")
        else:
            _git_publish(f"products/{topic}/",
                         f"feat(rex): {topic} initial build")'''
GIT_NEW = '''            # The DIRECTORY, not the topic. A phase's files are in its
            # epic's directory, so committing products/<topic>/ covered a
            # path that is not there — and the build reported a push it had
            # not made.
            _git_publish(_rel_dir(topic), f"feat(rex): {topic} sources")
        else:
            _git_publish(_rel_dir(topic),
                         f"feat(rex): {topic} initial build")'''

REL_HELPER = '''

def _rel_dir(topic):
    """products/<name>/ for git, resolved the same way as _product_dir."""
    from product_dir import rel_for_topic
    return rel_for_topic(topic)

'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in (PD, LIB):
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

sys.path.insert(0, str(DC / "scripts"))
from patchlib import code_only, py_ok, PatchCheckFailed   # noqa: E402

r = subprocess.run([sys.executable, str(PD), "--test"],
                   capture_output=True, text=True)
if "product_dir OK" not in r.stdout:
    sys.exit(f"NOTHING DONE — product_dir fails its own tests:\n{r.stdout}"
             f"{r.stderr[-300:]}")
print("patch_build_dir_everywhere\n")
print("  ok  product_dir passes its self-test")

plan = []
bad = False

for path, anchor, expect in FILES:
    if not path.is_file():
        print(f"  !! {path} is not there"); bad = True; continue
    s = path.read_text(encoding="utf-8")
    if "_product_dir(topic)" in s:
        print(f"  -- {path.name}: already routed"); continue
    n = s.count(OLD_PATH)
    a = s.count(anchor)
    ok = (n == expect and a == 1)
    print(f"  {'ok ' if ok else '!! '}{path.name}: {n} site(s) "
          f"(expected {expect}), {a} anchor")
    bad |= not ok
    plan.append(("bulk", path, anchor, expect))

for path, old, new, anchor in ONE_OFFS:
    if not path.is_file():
        print(f"  !! {path} is not there"); bad = True; continue
    s = path.read_text(encoding="utf-8")
    if "_product_dir(" in s:
        print(f"  -- {path.name}: already routed"); continue
    n, a = s.count(old), s.count(anchor)
    ok = (n == 1 and a == 1)
    print(f"  {'ok ' if ok else '!! '}{path.name}: {n} site, {a} anchor")
    bad |= not ok
    plan.append(("one", path, (old, new, anchor), 1))

flow = DC / "ducorn" / "flows" / "langgraph_flow.py"
fs = flow.read_text(encoding="utf-8")
if "_rel_dir(topic)" in fs:
    print("  -- langgraph_flow.py: git paths already routed")
else:
    n = fs.count(GIT_OLD)
    print(f"  {'ok ' if n == 1 else '!! '}langgraph_flow.py: {n} git-path "
          f"block")
    bad |= n != 1
    plan.append(("git", flow, None, 1))

if bad:
    sys.exit("\nNOTHING DONE — a count did not match. Nothing was written.")
if not plan:
    sys.exit("NOTHING DONE — everything is already routed.")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
touched = {}

for kind, path, extra, _n in plan:
    s = path.read_text(encoding="utf-8")
    if path not in touched:
        shutil.copy2(path, path.with_suffix(f".backup-{TAG}-{stamp}{path.suffix}"))
        touched[path] = 0
    if kind == "bulk":
        anchor = extra
        if "_product_dir(topic)" not in s:
            s = s.replace(anchor, anchor + HELPER.rstrip() + "\n", 1)
        s = s.replace(OLD_PATH, NEW_PATH)
        touched[path] += _n
    elif kind == "one":
        old, new, anchor = extra
        s = s.replace(anchor, anchor + HELPER.rstrip() + "\n", 1)
        s = s.replace(old, new, 1)
        touched[path] += 1
    else:                       # git
        s = s.replace(GIT_OLD, GIT_NEW, 1)
        i = s.find("def _product_dir(topic):")
        if i < 0:
            sys.exit("⚠️  the git block needs _product_dir in the same file "
                     "— restore the backups.")
        s = s.replace("def _product_dir(topic):",
                      REL_HELPER.strip() + "\n\n\ndef _product_dir(topic):", 1)
        touched[path] += 2
    path.write_text(s, encoding="utf-8")

print()
for path, n in touched.items():
    print(f"  {path.name}: {n} site(s), backup tagged {TAG}-{stamp}")

fail = []
for path in touched:
    after = path.read_text(encoding="utf-8")
    try:
        py_ok(after, path.name)
    except PatchCheckFailed as e:
        fail.append(str(e)); continue
    code = code_only(after)
    # In CODE. Every comment above mentions the old spelling, and four checks
    # in this repo have failed on their own prose.
    if OLD_PATH in code:
        fail.append(f"{path.name} still derives the path in code")
    if 'products/{topic}/"' in code and path.name == "langgraph_flow.py":
        fail.append("langgraph_flow still builds a git path from the topic")
    if "def _product_dir" not in code:
        fail.append(f"{path.name} has no _product_dir helper")

if fail:
    sys.exit("⚠️  restore the backups:\n  " + "\n  ".join(fail))
print("\nverified: every file parses, none derives the path in code, and each "
      "has the helper.")

print(f"""
  python3 scripts/product_dir.py ducorn-admin-rebuild-p1-config

should print products/ducorn-admin-rebuild — the epic's directory, not the
phase's. Then resume; skill 04 now looks where the files actually are.
""")
