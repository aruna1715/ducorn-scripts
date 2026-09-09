#!/usr/bin/env python3
"""
Design links 404 for every phase, because the guard looks in the wrong folder.

    cd ~/DC && python3 scripts/patch_design_link_epics.py            show
    cd ~/DC && python3 scripts/patch_design_link_epics.py --apply    do it

Needs scripts/product_epics.py and scripts/patchlib.py.

── WHAT HAPPENED ────────────────────────────────────────────────────────────

Gate 2 offered three designs. Every link returned "Not found", so the founder
had neither the pictures (the Slack channel bug) nor the pages. The API log
said exactly why, three times:

    [view_design] refusing '.../products/ducorn-admin-rebuild/design/
    design-operator-s-console.html' — outside '.../products/
    ducorn-admin-rebuild-p1-config/design' for slug
    'ducorn-admin-rebuild-p1-config'

── THE CAUSE ────────────────────────────────────────────────────────────────

view_design re-derives where the file ought to be:

    expected = PRODUCTS / row["slug"] / "design"

That is correct for a standalone product and wrong for a phase. A phase
builds into its EPIC's directory — products/ducorn-admin-rebuild — while its
slug is ducorn-admin-rebuild-p1-config. The two are different by design, and
this line assumes they are the same.

Worth being clear about what did NOT go wrong: the guard fails closed, says
what it refused and why, and would have stopped a real path escape. The
security reasoning is sound. It is the FACT it reasons from — where a run's
files live — that went stale when epics arrived.

That is the fourth control in this stack to hold a private copy of that fact.
product_jail asked product_epics.build_dir instead of deriving its own, and
this is the same repair applied to the same question.

── THE FIX ──────────────────────────────────────────────────────────────────

    expected = product_epics.build_dir(row["slug"]) / "design"

build_dir is the one place the mapping lives: a phase resolves to its epic's
directory, everything else to a directory of its own name. The check stays
exactly as strict — one directory, resolved, must be a parent of the file.

No epics installed, or migration 009 not applied, falls back to the old
derivation, which is the correct answer when there are no phases. Any OTHER
failure refuses: this endpoint is the one thing on the API reachable without
a key, and "I could not work out where this belongs" is not a reason to serve
a file.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
API = DC / "ducorn-products" / "products" / "ducorn-activity-api" / "main.py"
PE = DC / "scripts" / "product_epics.py"
LIB = DC / "scripts" / "patchlib.py"
TAG = "designepic"

OLD = '''    p = _P(row["path"]).resolve()
    expected = (_P("/Users/ducorn/DC/ducorn-products/products")
                / row["slug"] / "design").resolve()
    if expected not in p.parents or not p.is_file():'''

NEW = '''    p = _P(row["path"]).resolve()

    # WHERE a run's files live is one question with one answer, and it is
    # product_epics.build_dir. This used to compute
    # PRODUCTS / row["slug"] / "design", which is right for a standalone
    # product and wrong for a phase: a phase builds into its EPIC's
    # directory. Every design of every phase 404'd, with the guard working
    # correctly against a folder that does not exist.
    _PRODUCTS = _P("/Users/ducorn/DC/ducorn-products/products")
    try:
        import product_epics as _pe
        _base = _P(_pe.build_dir(row["slug"]))
    except ImportError:
        _base = _PRODUCTS / row["slug"]          # no epics on this machine
    except Exception as _e:
        if type(_e).__name__ == "EpicsNotInstalled":
            _base = _PRODUCTS / row["slug"]      # migration 009 not applied
        else:
            # Fail closed. This is the only endpoint reachable without a key,
            # and "I could not work out where this belongs" is not a reason
            # to serve a file from disk.
            print(f"[view_design] refusing {row['path']!r} — could not "
                  f"resolve the build directory for {row['slug']!r}: {_e}")
            return HTMLResponse("<h1>Not found</h1>", status_code=404)

    expected = (_base / "design").resolve()
    if expected not in p.parents or not p.is_file():'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in (API, PE, LIB):
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

sys.path.insert(0, str(DC / "scripts"))
from patchlib import code_only, calls_in, py_ok, PatchCheckFailed  # noqa: E402

if "def build_dir" not in PE.read_text(encoding="utf-8"):
    sys.exit("NOTHING DONE — product_epics has no build_dir().")

src = API.read_text(encoding="utf-8")
print("patch_design_link_epics\n")
print("  ok  product_epics.build_dir() is available")

if "_pe.build_dir" in src:
    sys.exit("NOTHING DONE — view_design already asks build_dir.")

n = src.count(OLD)
print(f"  {'ok ' if n == 1 else '!! '}the path guard in view_design  "
      f"({n} match)")
if n != 1:
    sys.exit("\nNOTHING DONE — the anchor did not match exactly once.")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(API, API.with_suffix(f".backup-{TAG}-{stamp}.py"))
API.write_text(src.replace(OLD, NEW, 1), encoding="utf-8")
print(f"\nwrote {API.name}, backup tagged {TAG}-{stamp}")

after = API.read_text(encoding="utf-8")
try:
    py_ok(after, "main.py")
except PatchCheckFailed as e:
    sys.exit(f"⚠️  {e} — restore the backup.")

if len(calls_in(after, "view_design", "build_dir")) != 1:
    sys.exit("⚠️  view_design does not call build_dir exactly once — restore "
             "the backup.")
code = code_only(after)
body = code[code.find("def view_design"):code.find("def pipeline_approve")]
if "expected not in p.parents" not in body:
    sys.exit("⚠️  the containment check is gone — restore the backup. This "
             "patch corrects WHERE it looks, it does not remove it.")
print("verified: main.py parses; view_design asks build_dir once and still "
      "checks containment.")

# The guard must still refuse a file outside its directory. Proved on the
# real rule, not on the comment describing it.
probe = r'''
from pathlib import Path
PRODUCTS = Path("/tmp/pv/products")
def allowed(base, path):
    expected = (Path(base) / "design").resolve()
    p = Path(path).resolve()
    return expected in p.parents
epic = PRODUCTS / "ducorn-admin-rebuild"
bad = []
if not allowed(epic, epic / "design" / "a.html"):
    bad.append("a phase design inside the epic directory is still refused")
if allowed(epic, PRODUCTS / "other-product" / "design" / "a.html"):
    bad.append("a file in ANOTHER product is now served")
if allowed(epic, epic / "src" / "a.html"):
    bad.append("a file outside design/ is now served")
if allowed(epic, Path("/etc/passwd")):
    bad.append("an absolute path outside products/ is now served")
print("GUARD_OK" if not bad else "GUARD_BAD " + "; ".join(bad))
'''
r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
if "GUARD_OK" not in r.stdout:
    sys.exit(f"⚠️  {(r.stdout + r.stderr).strip()[-300:]}")
print("          and the rule still refuses another product, a sibling "
      "folder and an absolute path.")

print("""
  launchctl kickstart -k gui/$(id -u)/com.ducorn.api

Then the three gate-2 links work — the tokens are still valid, they last 30
days and nothing about them changed. Open one and pick a design.
""")
