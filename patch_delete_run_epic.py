#!/usr/bin/env python3
"""
delete_run must ask where a product lives, not assume slug == directory.

    cd ~/DC && python3 scripts/patch_delete_run_epic.py            show
    cd ~/DC && python3 scripts/patch_delete_run_epic.py --apply    do it

Needs scripts/patchlib.py.

── THE BUG ──────────────────────────────────────────────────────────────────

    product_dir = PRODUCTS / "products" / slug

True only when a run's slug equals its product's name. Under the epic layout
it does not: phase `zz-plumbing-check-p1-status` builds into
`products/zz-plumbing-check`.

So delete_run looks for a directory that does not exist, finds nothing, and
happily clears the database, the checkpoints and the docs — leaving every
built file on disk. Recreate the run and the builder meets a complete product
with nothing left to write, and the build gate fails it for changing nothing.
That is the loop this stack is in right now.

The file's own docstring says the checkpoint case is "the nastiest: delete a
test product, make another with the same name, and it silently resumes
mid-pipeline from the old run." This is the same failure with the halves
swapped — the state cleared and the files kept.

── THE FIX, AND THE SECOND HALF OF IT ───────────────────────────────────────

product_dir.for_topic is the one resolver; this asks it.

But an epic's phases SHARE one build directory, so removing phase 1's run
must not carry phase 2's work off with it. Sibling runs are found the way
delete_run already finds everything — from pipeline_runs, "so the rule
derives from reality rather than from me guessing at naming conventions".
A shared directory is spared and reported, and `--shared-product` is the
deliberate act that removes it anyway.

── CONTEXT ──────────────────────────────────────────────────────────────────

An AST sweep found seven sites building a product path from the topic. Three
are real: this one, DuCornCursorTool's escape quarantine, and
product_paths.product_dir — a second resolver, epic-unaware, that doctor.py
and prove_deploy.py both use. This patch fixes the one blocking a clean run.
"""
from __future__ import annotations

import argparse
import ast
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
TARGET = DC / "scripts" / "delete_run.py"
LIB = DC / "scripts" / "patchlib.py"
TAG = "deleteepic"

ARGS_OLD = '''    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    slug, apply = args.slug, args.apply'''

ARGS_NEW = '''    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--shared-product", action="store_true",
                    help="also remove a build directory shared with other "
                         "phases of the same epic. Their files go too.")
    args = ap.parse_args()
    slug, apply = args.slug, args.apply
    shared_ok = args.shared_product'''

HELPER_OLD = '''def find_processes(slug):'''

HELPER_NEW = '''def resolve_product_dir(slug):
    """
    Where this run actually builds, or None if it cannot be determined.

    Never `PRODUCTS / "products" / slug`. That is true only when a slug
    equals a product name, and under the epic layout a phase slug does not:
    zz-plumbing-check-p1-status builds into products/zz-plumbing-check. The
    derived path pointed at nothing, so the files survived a delete that
    cleared the database — and the next build had nothing left to write.

    None is returned rather than a guess. Clearing state while leaving files
    is the failure being fixed; doing it because a resolver was unavailable
    would be the same failure with a different cause.
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from product_dir import for_topic
        return Path(for_topic(slug)).resolve()
    except Exception as e:
        print(f"⚠️  cannot resolve the product directory for {slug!r}: {e}")
        return None


def shares_product_dir(slug, others, prod_dir):
    """
    Other runs that build into the same directory — an epic's other phases.

    Found from pipeline_runs, the way this file finds everything else, so the
    answer comes from what exists rather than from a naming convention.
    """
    out = []
    for other in others:
        if other == slug:
            continue
        d = resolve_product_dir(other)
        if d is not None and d == prod_dir:
            out.append(other)
    return sorted(out)


def find_processes(slug):'''

BLOCK_OLD = '''    product_dir = PRODUCTS / "products" / slug
    if product_dir.is_dir():
        moves.append(product_dir)'''

BLOCK_NEW = '''    prod_dir = resolve_product_dir(slug)
    if prod_dir is None:
        print("    products/ left untouched — clearing state without the "
              "files is what makes a rebuilt run fail for changing nothing.")
    elif prod_dir.is_dir():
        siblings = shares_product_dir(slug, others, prod_dir)
        if siblings and not shared_ok:
            print(f"\\n⚠️  {prod_dir.name}/ is an epic build directory shared "
                  f"with {len(siblings)} other run(s): {', '.join(siblings)}")
            print("    Left in place. --shared-product removes it anyway, "
                  "and takes their files with it.")
        else:
            moves.append(prod_dir)'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in (TARGET, LIB, DC / "scripts" / "product_dir.py"):
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

sys.path.insert(0, str(DC / "scripts"))
from patchlib import calls_in, code_only, py_ok, PatchCheckFailed   # noqa: E402

src = TARGET.read_text(encoding="utf-8")
print("patch_delete_run_epic\n")

if "def resolve_product_dir" in src:
    sys.exit("NOTHING DONE — delete_run already asks the resolver.")

bad = False
for label, anchor in [("the argparse block", ARGS_OLD),
                      ("find_processes", HELPER_OLD),
                      ("the derived product path", BLOCK_OLD)]:
    n = src.count(anchor)
    print(f"  {'ok ' if n == 1 else '!! '}{label}  ({n} match)")
    bad |= n != 1
if bad:
    sys.exit("\nNOTHING DONE — an anchor did not match exactly once.")

if "def for_topic" not in (DC / "scripts" / "product_dir.py").read_text(
        encoding="utf-8"):
    sys.exit("NOTHING DONE — product_dir has no for_topic().")
print("  ok  product_dir.for_topic() exists")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(TARGET, TARGET.with_suffix(f".backup-{TAG}-{stamp}.py"))
TARGET.write_text(src.replace(ARGS_OLD, ARGS_NEW, 1)
                     .replace(HELPER_OLD, HELPER_NEW, 1)
                     .replace(BLOCK_OLD, BLOCK_NEW, 1), encoding="utf-8")
print(f"\nwrote delete_run.py, backup tagged {TAG}-{stamp}")

after = TARGET.read_text(encoding="utf-8")
try:
    py_ok(after, "delete_run.py")
except PatchCheckFailed as e:
    sys.exit(f"⚠️  {e} — restore the backup.")

code = code_only(after)
if 'PRODUCTS / "products" / slug' in code:
    sys.exit("⚠️  the derived path is still in the code — restore the backup.")
if len(calls_in(after, "main", "resolve_product_dir")) != 1:
    sys.exit("⚠️  main() does not resolve the product directory — restore the "
             "backup.")
if len(calls_in(after, "resolve_product_dir", "for_topic")) != 1:
    sys.exit("⚠️  the resolver is not consulted — restore the backup.")
if len(calls_in(after, "main", "shares_product_dir")) != 1:
    sys.exit("⚠️  the shared-epic guard is missing — deleting one phase would "
             "take another phase's files. Restore the backup.")
print("verified: it parses, the derived path is gone, and the epic guard is "
      "wired in.")

# ── behaviour, against the SHIPPED functions ───────────────────────────────
tree = py_ok(after, "delete_run.py")


def _bound(node):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return node.name
    if isinstance(node, ast.Assign) and node.targets:
        return getattr(node.targets[0], "id", None)
    if isinstance(node, ast.AnnAssign):
        return getattr(node.target, "id", None)
    return None


wanted = ("resolve_product_dir", "shares_product_dir")
body = [n for n in tree.body if _bound(n) in wanted]
if {_bound(n) for n in body} != set(wanted):
    sys.exit("⚠️  the helpers are not module-level — restore the backup.")

import tempfile
import types

base = Path(tempfile.mkdtemp())
epic = base / "zz-plumbing-check"
epic.mkdir()
solo = base / "standalone-thing"
solo.mkdir()

# A stand-in for product_dir.for_topic with the real contract: a phase slug
# resolves to its EPIC's directory; anything else to its own.
MAP = {"zz-plumbing-check-p1-status": epic,
       "zz-plumbing-check-p2-detail": epic,
       "standalone-thing": solo}
mod = types.ModuleType("product_dir")
mod.for_topic = lambda s: MAP.get(s, base / s)
sys.modules["product_dir"] = mod

# __file__ is seeded because resolve_product_dir uses it to find scripts/ on
# sys.path. An exec'd namespace has no __file__, so without this the function
# raises NameError, returns None, and this check calls a correct patch broken
# — which is the seventh time a verification in this project has done that.
# The value mirrors where the function really runs from.
ns = {"sys": sys, "Path": Path, "print": lambda *a, **k: None,
      "__file__": str(TARGET)}
exec(compile(ast.Module(body=body, type_ignores=[]), "<shipped>", "exec"), ns)
resolve = ns["resolve_product_dir"]
sharing = ns["shares_product_dir"]

ALL = ["zz-plumbing-check-p1-status", "zz-plumbing-check-p2-detail",
       "standalone-thing"]
problems = []

got = resolve("zz-plumbing-check-p1-status")
if got != epic.resolve():
    problems.append(f"a phase slug resolved to {got}, not its epic directory "
                    f"— this is the whole bug")
if resolve("standalone-thing") != solo.resolve():
    problems.append("an ordinary slug no longer resolves to its own directory")

sib = sharing("zz-plumbing-check-p1-status", ALL, epic.resolve())
if sib != ["zz-plumbing-check-p2-detail"]:
    problems.append(f"sibling detection returned {sib} — deleting one phase "
                    f"would take another phase's files")
if sharing("standalone-thing", ALL, solo.resolve()) != []:
    problems.append("a standalone product was reported as shared, so it would "
                    "never be cleaned")
if sharing("zz-plumbing-check-p1-status", ALL, epic.resolve()) == ALL:
    problems.append("a run was reported as sharing with itself")

# A resolver that raises must yield None, never a guess.
mod.for_topic = lambda s: (_ for _ in ()).throw(RuntimeError("no epics"))
if resolve("anything") is not None:
    problems.append("a failing resolver produced a path instead of None")

if problems:
    sys.exit("⚠️  restore the backup:\n  " + "\n  ".join(problems))
print("          a phase resolves to its epic dir; siblings are detected; a "
      "failed resolve returns None.")

print("""
Now a dry run will actually list the product directory:

  python3 scripts/delete_run.py zz-plumbing-check-p1-status

Read what it says. If zz-plumbing-check has other phase runs recorded it will
spare the shared directory and name them — for a throwaway test epic you want
--shared-product so the whole thing goes.

Files are MOVED to ~/DC/_deleted/<slug>-<timestamp>/, never unlinked.
""")
