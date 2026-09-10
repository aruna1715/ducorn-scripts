#!/usr/bin/env python3
"""
The deliverable lookup must go through the jail, not around it.

    cd ~/DC && python3 scripts/patch_verdict_jail.py            show
    cd ~/DC && python3 scripts/patch_verdict_jail.py --apply    do it

Needs scripts/patchlib.py, and patch_verdict_from_deliverable applied first.

── MY BUG, FROM AN HOUR AGO ─────────────────────────────────────────────────

verdict_in_deliverables locates the document like this:

    d = _product_dir(topic)
    body = (d / fn).read_text(...)

`fn` comes from the writer tool's ledger — a filename an AGENT chose. In
pathlib, a `/` join with an ABSOLUTE right-hand side throws the left-hand
side away:

    Path("/…/products/foo") / "/Users/ducorn/DC/products/bar/x.md"
      -> PosixPath("/Users/ducorn/DC/products/bar/x.md")

So an agent that passed an absolute filename would have one product reading
another product's file. Read-only, and only .md, but "no product reads
another product's files, EVER" does not have a size exemption.

── WHY THE JAIL, RATHER THAN A CHECK ────────────────────────────────────────

The obvious patch is to reject absolute paths and `..` here. That would be a
SECOND COPY of the containment rule, sitting next to the real one and free to
drift from it — the same defect shape as the eleven copies of the build
directory, and as the verdict living in two places, which is what the patch
this one repairs was about.

resolve_in_jail IS the rule. It already resolves a filename exactly the way
the writer tool resolved it when the file was created, collapses `..`,
follows symlinks, and raises PathEscape for anything that lands outside. Same
input, same resolver, same answer — and if containment is ever tightened,
this follows automatically.

── A REAL EXAMPLE FROM THE PLUMBING RUN ─────────────────────────────────────

The test run produced this, inside the product directory:

    products/zz-plumbing-check/~/DC/gstack/skills/01-prd-analysis.md

An agent tried to write to `~/DC/gstack/skills/01-prd-analysis.md` — the
G-Stack PRD skill definition itself. The jail contained it, so nothing
outside the product was touched. Going through resolve_in_jail here means the
lookup sees exactly what the writer saw, whatever shape the agent invented.

(That the jail treated a leading `~` as a subdirectory instead of refusing it
is a separate gap, and a loud one is worth having. Not this patch.)
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
RUNNER = DC / "ducorn" / "skill_runner.py"
LIB = DC / "scripts" / "patchlib.py"
TAG = "verdictjail"

OLD = '''    try:
        from tools.DuCornWriterTool import files_written
    except Exception:
        return None
    try:
        d = _product_dir(topic)
    except Exception:
        return None

    found = []
    for fn in files_written(topic):
        if not fn.lower().endswith(".md"):
            continue
        try:
            body = (d / fn).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue'''

NEW = '''    try:
        from tools.DuCornWriterTool import files_written
        from tools.product_jail import resolve_in_jail
    except Exception:
        return None

    found = []
    for fn in files_written(topic):
        if not fn.lower().endswith(".md"):
            continue
        # Through the jail, never around it.
        #
        # This used to be `_product_dir(topic) / fn`, and pathlib discards the
        # left side of a join when the right side is absolute — so an agent
        # that passed an absolute filename would have had one product read
        # another product's file. resolve_in_jail is the containment rule
        # itself; re-checking the path here would be a second copy of it,
        # free to drift from the real one.
        try:
            p = resolve_in_jail(topic, fn)
        except Exception:
            # PathEscape, or anything else: a name that does not resolve
            # inside this product is not this product's deliverable.
            continue
        try:
            body = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in (RUNNER, LIB):
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

sys.path.insert(0, str(DC / "scripts"))
from patchlib import calls_in, code_only, py_ok, PatchCheckFailed   # noqa: E402

src = RUNNER.read_text(encoding="utf-8")
print("patch_verdict_jail\n")

if "def verdict_in_deliverables" not in src:
    sys.exit("NOTHING DONE — apply patch_verdict_from_deliverable first.")
if "resolve_in_jail(topic, fn)" in src:
    sys.exit("NOTHING DONE — the lookup already goes through the jail.")

n = src.count(OLD)
print(f"  {'ok ' if n == 1 else '!! '}the deliverable lookup  ({n} match)")
if n != 1:
    sys.exit("\nNOTHING DONE — the anchor did not match exactly once.")

jail = DC / "ducorn" / "tools" / "product_jail.py"
if "def resolve_in_jail" not in jail.read_text(encoding="utf-8"):
    sys.exit("NOTHING DONE — product_jail has no resolve_in_jail().")
print("  ok  tools/product_jail.resolve_in_jail() exists")

r = subprocess.run(["pgrep", "-f", "ducorn/skill_runner.py"],
                   capture_output=True, text=True)
if r.stdout.strip():
    sys.exit(f"NOTHING DONE — skill_runner is running (pid "
             f"{r.stdout.split()[0]}). Apply this when it has finished.")
print("  ok  skill_runner is not running")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(RUNNER, RUNNER.with_suffix(f".backup-{TAG}-{stamp}.py"))
RUNNER.write_text(src.replace(OLD, NEW, 1), encoding="utf-8")
print(f"\nwrote skill_runner.py, backup tagged {TAG}-{stamp}")

after = RUNNER.read_text(encoding="utf-8")
try:
    py_ok(after, "skill_runner.py")
except PatchCheckFailed as e:
    sys.exit(f"⚠️  {e} — restore the backup.")

if len(calls_in(after, "verdict_in_deliverables", "resolve_in_jail")) != 1:
    sys.exit("⚠️  the lookup does not go through resolve_in_jail — restore "
             "the backup.")
if calls_in(after, "verdict_in_deliverables", "_product_dir"):
    sys.exit("⚠️  _product_dir is still used to build the path — that is the "
             "join being removed. Restore the backup.")
print("verified: it parses; the lookup resolves through the jail and no "
      "longer joins a product dir to an agent-chosen name.")

# ── the escape itself, against the SHIPPED function ─────────────────────────
# Extracted by ast and run with a resolver that enforces the real contract:
# inside -> a path, outside -> raise. That is what product_jail promises, and
# what this function must honour.
tree = py_ok(after, "skill_runner.py")
fn_node = next((n for n in tree.body if isinstance(n, ast.FunctionDef)
                and n.name == "verdict_in_deliverables"), None)
if fn_node is None:
    sys.exit("⚠️  verdict_in_deliverables is not module-level — restore the "
             "backup.")

import tempfile
import types

jail_root = Path(tempfile.mkdtemp()) / "products" / "mine"
(jail_root / "sub").mkdir(parents=True)
(jail_root / "review.md").write_text("ok\nVERDICT: PASS\n")
(jail_root / "sub" / "consult.md").write_text("x\nVERDICT: PASS\n")

outside = jail_root.parent / "theirs"
outside.mkdir(parents=True)
(outside / "secret.md").write_text("stolen\nVERDICT: FAIL — other product\n")


def fake_resolve(topic, path):
    p = Path(path)
    cand = p if p.is_absolute() else (jail_root / p)
    cand = cand.resolve()
    if jail_root.resolve() not in cand.parents and cand != jail_root.resolve():
        raise RuntimeError(f"BLOCKED: {path}")
    return cand


writer = types.ModuleType("tools.DuCornWriterTool")
jailmod = types.ModuleType("tools.product_jail")
jailmod.resolve_in_jail = fake_resolve
pkg = types.ModuleType("tools")
pkg.DuCornWriterTool, pkg.product_jail = writer, jailmod
sys.modules.update({"tools": pkg, "tools.DuCornWriterTool": writer,
                    "tools.product_jail": jailmod})

ns: dict = {"_product_dir": lambda t: jail_root}
for helper in ("explicit_verdict", "DELIVERABLE_TAIL_LINES"):
    node = next((n for n in tree.body
                 if (isinstance(n, ast.FunctionDef) and n.name == helper)
                 or (isinstance(n, ast.Assign)
                     and getattr(n.targets[0], "id", "") == helper)), None)
    if node is None:
        sys.exit(f"⚠️  {helper} is missing — restore the backup.")
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<s>", "exec"), ns)
exec(compile(ast.Module(body=[fn_node], type_ignores=[]), "<s>", "exec"), ns)
vid = ns["verdict_in_deliverables"]

problems = []

writer.files_written = lambda t: ["review.md"]
if (vid("mine") or (None,))[0] != "pass":
    problems.append("a legitimate in-jail document is no longer read")

writer.files_written = lambda t: ["sub/consult.md"]
if (vid("mine") or (None,))[0] != "pass":
    problems.append("a document in a subdirectory is no longer read")

# THE BUG: an absolute path belonging to another product.
writer.files_written = lambda t: [str(outside / "secret.md")]
if vid("mine") is not None:
    problems.append("AN ABSOLUTE PATH STILL ESCAPES — another product's "
                    "file was read")

writer.files_written = lambda t: ["../theirs/secret.md"]
if vid("mine") is not None:
    problems.append("a ../ traversal still escapes")

writer.files_written = lambda t: ["nope.md"]
if vid("mine") is not None:
    problems.append("a missing file no longer returns None")

if problems:
    sys.exit("⚠️  restore the backup:\n  " + "\n  ".join(problems))
print("          escape proven closed: absolute and ../ names are refused, "
      "in-jail names still read.")

print("""
The deliverable lookup now resolves a filename exactly the way the writer
resolved it when the file was created — same resolver, same answer.

Nothing to restart. Carry on with the run.
""")
