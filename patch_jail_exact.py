#!/usr/bin/env python3
"""
One product must not read another's documents. A prefix test cannot decide that.

    cd ~/DC && python3 scripts/patch_jail_exact.py            show
    cd ~/DC && python3 scripts/patch_jail_exact.py --apply    do it

── THE DEFECT ───────────────────────────────────────────────────────────────

product_jail._inside decides whether a path in the shared docs/ directory
belongs to the product asking for it:

    return docs_root in p.parents and p.name.startswith(f"{topic}-")

docs/ is flat and shared. Files are named "<topic>-<something>", so a prefix
test says yes whenever one topic's name is a prefix of another's. Your topics
include all three of these pairs:

    ducorn-pipeline-dashboard      ⊂  ducorn-pipeline-dashboard-v6, -v10
    ducorn-technical-reference     ⊂  ducorn-technical-reference-guide
    ducorn-spend-status            ⊂  ducorn-spend-status-web

So a run of ducorn-pipeline-dashboard can open
ducorn-pipeline-dashboard-v6-PRD.md, its checkpoint, and every skill output
it ever produced. The agent is not told it is another product's file; the
jail hands it over as its own.

visible_files() has the same test, so the refusal message LISTS the other
product's filenames even when a read is blocked.

── THE FIX ──────────────────────────────────────────────────────────────────

Work out who a file actually belongs to, rather than whether a name starts
with something. The owner is the LONGEST known topic the filename starts
with:

    ducorn-pipeline-dashboard-v6-PRD.md
        starts with "ducorn-pipeline-dashboard-"      ← a topic
        starts with "ducorn-pipeline-dashboard-v6-"   ← also a topic, longer
        owner = ducorn-pipeline-dashboard-v6

and access is granted only when the owner IS the asking product.

The topic list is derived, not maintained: product directories under
products/, plus every "<topic>-gstack-checkpoint.json" in docs/, which every
run writes. The asking topic is always added, so a brand-new product can
still reach its own files on its first run.

Fails closed. When two topics are ambiguous the longer one wins, which means
the more specific product keeps its files and the shorter one is refused —
the safe direction.

── WHY NOT docs/<topic>/ ────────────────────────────────────────────────────

That would delete this whole class rather than fixing an instance, and it is
the wrong trade today: "{topic}-PRD.md", "{topic}-skill{N}-output.txt" and
"{topic}-gstack-checkpoint.json" are built at about twenty call sites across
skill_runner.py and langgraph_flow.py, named inside agent prompts, and there
are 126 files in docs/ that would need moving. Worth doing deliberately, not
as a side effect of a security fix.
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
TAG = "jailexact"

OLD_IMPORT = """from pathlib import Path

PRODUCTS_DIR = Path("/Users/ducorn/DC/ducorn-products").resolve()"""

NEW_IMPORT = '''from functools import lru_cache
from pathlib import Path

PRODUCTS_DIR = Path("/Users/ducorn/DC/ducorn-products").resolve()'''

OLD_INSIDE = '''def _inside(topic: str, p: Path) -> bool:
    product_root = (PRODUCTS_DIR / "products" / topic).resolve()
    docs_root    = (PRODUCTS_DIR / "docs").resolve()
    if p == product_root or product_root in p.parents:
        return True
    # docs/ is shared — only this product's own files are visible
    return docs_root in p.parents and p.name.startswith(f"{topic}-")'''

NEW_INSIDE = '''_CHECKPOINT = "-gstack-checkpoint.json"


@lru_cache(maxsize=1)
def _known_topics() -> frozenset:
    """
    Every topic on disk, derived — never a list anyone maintains.

    Two sources, both produced by the pipeline itself: a directory under
    products/, and a "<topic>-gstack-checkpoint.json" in docs/, which every
    run writes. Document products have no product directory, which is why one
    source is not enough.
    """
    topics = set()
    try:
        topics |= {d.name for d in (PRODUCTS_DIR / "products").iterdir()
                   if d.is_dir()}
    except OSError:
        pass
    try:
        for p in (PRODUCTS_DIR / "docs").glob("*" + _CHECKPOINT):
            topics.add(p.name[:-len(_CHECKPOINT)])
    except OSError:
        pass
    return frozenset(topics)


def docs_owner(name: str, asking: str = "") -> str:
    """
    Which product owns a file in the shared docs/ directory.

    The owner is the LONGEST known topic the filename starts with. This is
    the whole point: "ducorn-pipeline-dashboard" is a prefix of
    "ducorn-pipeline-dashboard-v6-PRD.md", and they are different products.
    The longer match is the real owner; the shorter one is a collision.

    `asking` is added to the candidates so a product on its very first run —
    before it has written a checkpoint — can still reach its own files.
    """
    best = ""
    for t in _known_topics() | ({asking} if asking else set()):
        if name.startswith(t + "-") and len(t) > len(best):
            best = t
    return best


def _inside(topic: str, p: Path) -> bool:
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

OLD_VISIBLE = '''        names += sorted(p.name for p in (PRODUCTS_DIR / "docs").glob(f"{topic}-*")
                        if p.is_file())'''

NEW_VISIBLE = '''        # Same ownership test as the wall itself. Listing by prefix here
        # would print another product's filenames inside the message that
        # refuses to open them.
        names += sorted(p.name for p in (PRODUCTS_DIR / "docs").glob(f"{topic}-*")
                        if p.is_file() and docs_owner(p.name, topic) == topic)'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

if not JAIL.is_file():
    sys.exit(f"NOTHING DONE — {JAIL} is not there")

src = JAIL.read_text(encoding="utf-8")

anchors = [("the import block", OLD_IMPORT),
           ("_inside", OLD_INSIDE),
           ("visible_files' docs glob", OLD_VISIBLE)]

print("patch_jail_exact\n")
ok = True
for what, needle in anchors:
    n = src.count(needle)
    print(f"  {'ok ' if n == 1 else '!! '}{what}  ({n} match)")
    ok = ok and n == 1
if not ok:
    sys.exit("\nNOTHING DONE — an anchor did not match exactly once.")

# ── what is actually exposed right now ──────────────────────────────────────
products = PRODUCTS = DC / "ducorn-products"
docs = products / "docs"
topics = set()
try:
    topics |= {d.name for d in (products / "products").iterdir() if d.is_dir()}
except OSError:
    pass
CK = "-gstack-checkpoint.json"
try:
    topics |= {p.name[:-len(CK)] for p in docs.glob("*" + CK)}
except OSError:
    pass

pairs = sorted((a, b) for a in topics for b in topics
               if a != b and b.startswith(a + "-"))
leaks = []
for short, longer in pairs:
    for f in sorted(docs.glob(f"{longer}-*")):
        if f.is_file():
            leaks.append((short, f.name))

print(f"\n  {len(topics)} topics known · {len(pairs)} colliding pair(s)")
for short, longer in pairs:
    print(f"      '{short}'  can currently read  '{longer}'  files")
print(f"\n  files reachable across products today: {len(leaks)}")
for short, name in leaks[:12]:
    print(f"      {short}  ->  docs/{name}")
if len(leaks) > 12:
    print(f"      … and {len(leaks) - 12} more")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(JAIL, JAIL.with_suffix(f".backup-{TAG}-{stamp}.py"))
JAIL.write_text(src.replace(OLD_IMPORT, NEW_IMPORT, 1)
                   .replace(OLD_INSIDE, NEW_INSIDE, 1)
                   .replace(OLD_VISIBLE, NEW_VISIBLE, 1), encoding="utf-8")
print(f"\nwrote {JAIL.name}, backup tagged {TAG}-{stamp}")

r = subprocess.run([sys.executable, "-m", "py_compile", str(JAIL)],
                   capture_output=True, text=True)
if r.returncode != 0:
    sys.exit(f"⚠️  it does not parse — restore the backup:\n{r.stderr[-400:]}")

# ── prove it on the real directories, both directions ───────────────────────
probe = f'''
import sys
sys.path.insert(0, "{DC}/ducorn/tools")
from product_jail import resolve_in_jail, PathEscape, docs_owner, _known_topics

bad = []

# every colliding pair must now be refused in the short -> long direction
topics = _known_topics()
pairs = [(a, b) for a in topics for b in topics if a != b and b.startswith(a + "-")]
import pathlib
docs = pathlib.Path("{DC}/ducorn-products/docs")
checked = 0
for short, longer in pairs:
    for f in sorted(docs.glob(longer + "-*")):
        if not f.is_file():
            continue
        checked += 1
        try:
            resolve_in_jail(short, "docs/" + f.name)
            bad.append(short + " can still read " + f.name)
        except PathEscape:
            pass

# and every product must still reach its own
own = 0
for t in sorted(topics):
    for f in sorted(docs.glob(t + "-*")):
        if not f.is_file() or docs_owner(f.name) != t:
            continue
        own += 1
        try:
            resolve_in_jail(t, "docs/" + f.name)
        except PathEscape:
            bad.append(t + " lost access to its own " + f.name)

print("JAIL_OK blocked=%d own=%d" % (checked, own) if not bad
      else "JAIL_BAD " + "; ".join(bad[:6]))
'''
r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
line = (r.stdout + r.stderr).strip()
if "JAIL_OK" not in r.stdout:
    sys.exit(f"⚠️  VERIFICATION FAILED — restore the backup:\n{line[-600:]}")

print(f"""
verified on the real docs/ directory: {line.split('JAIL_OK ')[-1]}

  blocked = cross-product reads that used to succeed and now raise PathEscape
  own     = files each product still reaches, unchanged

Also worth running:
  python3 scripts/doctor.py     'a document is only served to its owner'
""")
