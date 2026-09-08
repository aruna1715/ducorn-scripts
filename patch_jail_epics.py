#!/usr/bin/env python3
"""
Teach the jail about epics: a phase builds into its epic's directory.

    cd ~/DC && python3 scripts/patch_jail_epics.py            show
    cd ~/DC && python3 scripts/patch_jail_epics.py --apply    do it

Apply migration 009 and put scripts/product_epics.py in place first.

── WHY ──────────────────────────────────────────────────────────────────────

An epic is one product built over several runs, all writing into ONE
directory. The jail maps a topic to products/<topic>/, so phase 2 of
`ducorn-admin-rebuild` would be jailed to
products/ducorn-admin-rebuild-p2-services/ — an empty directory next to the
one holding phase 1's work, which it could neither read nor extend.

Two changes, and no more than two:

  1. Where a phase builds. product_epics.build_dir(topic) answers it. For
     every standalone product it returns products/<topic>/, which is exactly
     what happens today, so nothing that is not a phase changes at all.

  2. What a phase may read in docs/. Only the phases it declares
     depends_on, inside its own epic. Phase 2 needs the PRD phase 1 wrote;
     it does not need anything belonging to another epic, and does not get
     it.

── THE ONE SANCTIONED HOLE ──────────────────────────────────────────────────

This is the first time one slug has been allowed to read another's
documents, and it is worth being precise about why it is not the thing the
isolation work has spent two days closing:

  · it is declared, in a row, before the run starts — not inferred from a
    name that happens to be a prefix of another name;
  · it points backwards only (define() refuses a forward dependency);
  · it never crosses an epic;
  · the phases involved were already writing into the same directory, so
    no boundary that previously existed is being removed.

── FAILING ──────────────────────────────────────────────────────────────────

The lookup needs the database. It is cached for the life of the process —
an agent subprocess resolves paths hundreds of times and this asks once —
and it RAISES if the database cannot be read, rather than falling back to
products/<topic>/.

That is deliberate and matches product_pathways.for_topic, which refuses to
guess a product type for the same reason. A wrong answer here does not
degrade the run, it writes the product into the wrong directory, and nobody
would notice until a later phase found an empty one.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
JAIL = DC / "ducorn" / "tools" / "product_jail.py"
EPICS = DC / "scripts" / "product_epics.py"
TAG = "jailepics"

OLD_HEAD = '''PRODUCTS_DIR = Path("/Users/ducorn/DC/ducorn-products").resolve()
TOP_LEVEL = {"docs", "products", "pdfs", "outputs"}'''

NEW_HEAD = '''PRODUCTS_DIR = Path("/Users/ducorn/DC/ducorn-products").resolve()
TOP_LEVEL = {"docs", "products", "pdfs", "outputs"}


@lru_cache(maxsize=64)
def _epic_view(topic: str):
    """
    (build directory, slugs whose documents this topic may read).

    Cached: this is asked on every path resolution, and an agent resolves
    hundreds. One database round trip per topic per process.

    Raises rather than guessing. Getting this wrong does not degrade a run —
    it writes the product into the wrong directory, and nothing notices until
    a later phase opens an empty one. product_pathways.for_topic refuses to
    guess a product type on the same reasoning.
    """
    try:
        import product_epics
    except ImportError:
        # product_epics is not installed on this machine yet. Every topic is
        # a standalone product, which is what was true before epics existed.
        return (PRODUCTS_DIR / "products" / topic).resolve(), ()
    try:
        return (product_epics.build_dir(topic).resolve(),
                tuple(product_epics.readable_slugs(topic)))
    except product_epics.EpicsNotInstalled:
        # Migration 009 has not run, so no epic exists and every slug is a
        # standalone product. Provable, so it is safe to answer. Every OTHER
        # failure proves nothing and falls through to the raise below.
        return (PRODUCTS_DIR / "products" / topic).resolve(), ()
    except Exception as e:
        raise PathEscape(
            f"Could not determine where '{topic}' builds: {e}\\n"
            f"This decides which directory the product is written to, so it "
            f"is not guessed. Check the database and start the phase again."
        ) from e'''

OLD_INSIDE = '''def _inside(topic: str, p: Path) -> bool:
    product_root = (PRODUCTS_DIR / "products" / topic).resolve()
    docs_root    = (PRODUCTS_DIR / "docs").resolve()
    if p == product_root or product_root in p.parents:
        return True
    # docs/ is shared and flat. Ownership is decided by who the file belongs
    # to, not by whether the name happens to start with this topic — those are
    # different questions the moment one topic's name is a prefix of another's,
    # which is true of three pairs of products in this repo right now.
    if docs_root not in p.parents:
        return False
    return docs_owner(p.name, topic) == topic'''

NEW_INSIDE = '''def _inside(topic: str, p: Path) -> bool:
    # A phase of an epic builds into its EPIC's directory, alongside the
    # phases before it. For everything else this is products/<topic>/, which
    # is what it has always been.
    product_root, siblings = _epic_view(topic)
    docs_root = (PRODUCTS_DIR / "docs").resolve()
    if p == product_root or product_root in p.parents:
        return True
    # docs/ is shared and flat. Ownership is decided by who the file belongs
    # to, not by whether the name happens to start with this topic — those are
    # different questions the moment one topic's name is a prefix of another's,
    # which is true of three pairs of products in this repo right now.
    if docs_root not in p.parents:
        return False
    owner = docs_owner(p.name, topic)
    if owner == topic:
        return True
    # The one sanctioned crossing: an earlier phase of the SAME epic that
    # this phase declared a dependency on. Declared in a row before the run
    # starts, backwards only, never across epics.
    return owner in siblings'''

OLD_VISIBLE = '''        names += sorted(p.name for p in (PRODUCTS_DIR / "docs").glob(f"{topic}-*")
                        if p.is_file() and docs_owner(p.name, topic) == topic)'''

NEW_VISIBLE = '''        for owner in (topic,) + tuple(_epic_view(topic)[1]):
            names += sorted(
                p.name for p in (PRODUCTS_DIR / "docs").glob(f"{owner}-*")
                if p.is_file() and docs_owner(p.name, owner) == owner)'''

OLD_PRODUCT_GLOB = '''        product = PRODUCTS_DIR / "products" / topic
        if product.is_dir():'''

NEW_PRODUCT_GLOB = '''        product = _epic_view(topic)[0]
        if product.is_dir():'''

OLD_RESOLVE = '''    else:
        candidate = PRODUCTS_DIR / "products" / topic / p'''

NEW_RESOLVE = '''    else:
        candidate = _epic_view(topic)[0] / p'''

OLD_MSG = '''        f"  {PRODUCTS_DIR / 'products' / topic}/\\n"'''
NEW_MSG = '''        f"  {_epic_view(topic)[0]}/\\n"'''

EDITS = [
    ("the module header gains _epic_view", OLD_HEAD, NEW_HEAD),
    ("_inside asks where the topic builds", OLD_INSIDE, NEW_INSIDE),
    ("visible_files lists the epic's siblings too", OLD_VISIBLE, NEW_VISIBLE),
    ("visible_files reads the epic directory", OLD_PRODUCT_GLOB, NEW_PRODUCT_GLOB),
    ("resolve_in_jail writes into the epic directory", OLD_RESOLVE, NEW_RESOLVE),
    ("the refusal message names the real directory", OLD_MSG, NEW_MSG),
]

def probe_python() -> str:
    """
    An interpreter that can reach the database.

    `python3` on this Mac is 3.14 and has no psycopg2. The first version of
    this patch verified with sys.executable, so the check failed with
    "No module named psycopg2" and told you to restore a backup that was
    fine. Third time this interpreter has bitten in a week.
    """
    for c in (DC / "ducorn" / ".venv" / "bin" / "python",
              Path("/opt/homebrew/bin/python3.12")):
        if c.exists():
            return str(c)
    return sys.executable


ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()
PY = probe_python()

if not JAIL.is_file():
    sys.exit(f"NOTHING DONE — {JAIL} is not there")
if not EPICS.is_file():
    sys.exit(f"NOTHING DONE — {EPICS} must be in place first "
             f"(it is delivered alongside this patch)")

src = JAIL.read_text(encoding="utf-8")

print("patch_jail_epics\n")
if "_epic_view" in src:
    sys.exit("NOTHING DONE — product_jail.py already knows about epics.")
if "docs_owner" not in src:
    sys.exit("NOTHING DONE — apply patch_jail_exact.py first; this builds on "
             "the ownership function it adds.")

# The tables must exist first. Applying this before migration 009 makes
# every path resolution raise, because the lookup hits a table that is not
# there — which is exactly what happened on the first run of this patch.
check = subprocess.run(
    [PY, "-c",
     "import sys; sys.path.insert(0, %r); import product_epics as pe;"
     "print('TABLES_OK' if pe.get('__probe__') is None else 'TABLES_OK')"
     % str(DC / "scripts")],
    capture_output=True, text=True)
if "TABLES_OK" not in check.stdout:
    detail = (check.stdout + check.stderr).strip()[-300:]
    sys.exit(f"""NOTHING DONE — the epic tables are not queryable yet.

  {detail}

Apply the migration first:
  cp <delivered>/009_product_epics.sql {DC}/scripts/migrations/
  python3 scripts/migrate.py --status      # 009 should be listed as pending
  python3 scripts/migrate.py
""")
print(f"  ok  the epic tables exist and are queryable")

ok = True
for what, old, _new in EDITS:
    n = src.count(old)
    print(f"  {'ok ' if n == 1 else '!! '}{what}  ({n} match)")
    ok = ok and n == 1
if not ok:
    sys.exit("\nNOTHING DONE — an anchor did not match exactly once.")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(JAIL, JAIL.with_suffix(f".backup-{TAG}-{stamp}.py"))

out = src
for _what, old, new in EDITS:
    out = out.replace(old, new, 1)
if "from functools import lru_cache" not in out:
    out = out.replace("from pathlib import Path",
                      "from functools import lru_cache\nfrom pathlib import Path", 1)
JAIL.write_text(out, encoding="utf-8")
print(f"\nwrote {JAIL.name}, backup tagged {TAG}-{stamp}")

r = subprocess.run([sys.executable, "-m", "py_compile", str(JAIL)],
                   capture_output=True, text=True)
if r.returncode != 0:
    sys.exit(f"⚠️  it does not parse — restore the backup:\n{r.stderr[-400:]}")

# ── a standalone product must behave EXACTLY as before ──────────────────────
probe = f'''
import sys
sys.path.insert(0, "{DC}/ducorn/tools")
sys.path.insert(0, "{DC}/scripts")
from product_jail import resolve_in_jail, PathEscape, PRODUCTS_DIR

bad = []
# an ordinary product still writes into its own directory
got = resolve_in_jail("some-standalone-product", "main.py")
want = PRODUCTS_DIR / "products" / "some-standalone-product" / "main.py"
if got != want:
    bad.append("standalone product moved: %s" % got)

# and still cannot reach another product
try:
    resolve_in_jail("some-standalone-product", "products/other/main.py")
    bad.append("a standalone product can read another product")
except PathEscape:
    pass

print("JAIL_OK" if not bad else "JAIL_BAD " + "; ".join(bad))
'''
r = subprocess.run([PY, "-c", probe], capture_output=True, text=True)
if "JAIL_OK" not in r.stdout:
    sys.exit(f"⚠️  VERIFICATION FAILED — restore the backup:\n"
             f"{(r.stdout + r.stderr).strip()[-600:]}")

print("""
verified: a standalone product still resolves to its own directory and still
cannot reach another product's. Nothing that is not a phase behaves
differently.

Next:
  python3 scripts/product_epics.py --list
  python3 scripts/run_tests.py
""")
