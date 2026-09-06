#!/usr/bin/env python3
"""
Put scripts/ducorn_env.py back. I overwrote it.

    cd ~/DC && python3 scripts/fix_env_collision.py            show
    cd ~/DC && python3 scripts/fix_env_collision.py --apply    do it

── WHAT HAPPENED ────────────────────────────────────────────────────────────

scripts/ducorn_env.py already existed. It holds load_ducorn_env(), which is
imported by doctor.py, langgraph_flow.py, skill_runner.py, slack_bot.py,
create_remotes.py, generate_design.py, DuCornCursorTool.py, test_pipeline.py
and products/ducorn-activity-api/main.py.

I wrote a new env-file manager and gave it that same name without checking
whether the name was taken. The new file does not define load_ducorn_env, so
every one of those importers now dies with:

    ImportError: cannot import name 'load_ducorn_env' from 'ducorn_env'

The pipeline, the Slack bot, the activity API and doctor are all down. This
is not a subtle interaction — it is a file I clobbered.

── WHY NOTHING IS LOST ──────────────────────────────────────────────────────

The overwrite was never committed. `git status` shows ducorn_env.py as
modified, and HEAD still holds the original in full. Restoring is one
checkout. This script does that checkout, but first proves that the file in
HEAD is the one we want and that the file on disk is the one I wrote — so it
cannot silently discard something else you changed in the meantime.

── AFTER THIS ───────────────────────────────────────────────────────────────

The env-file manager returns as scripts/ducorn_envfile.py, a name nothing
uses. admin_main.py and install_admin.py are updated to import that.

The class is closed separately by scripts/prove_module_names.py, which
resolves every cross-module import in the tree statically and fails on any
name that is imported but not defined. Run that and this defect could not
have reached you.
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

DC = Path(os.environ.get("DUCORN_ROOT", "/Users/ducorn/DC"))
SCRIPTS = DC / "scripts"
TARGET = SCRIPTS / "ducorn_env.py"
NEWNAME = SCRIPTS / "ducorn_envfile.py"

WANTED = "load_ducorn_env"        # must come back
MINE = "effective"                # my module's marker


def die(msg: str) -> None:
    sys.exit(f"NOTHING DONE — {msg}")


def toplevel_names(src: str, where: str) -> set:
    """Names a module defines, without importing it."""
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        die(f"{where} does not parse: {e}")
    out = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out.add(node.target.id)
    return out


ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

if not TARGET.exists():
    die(f"{TARGET} is not there at all — stop and look before running anything")

# ── a lock will stop the checkout, so say so before doing anything else ──────
# The first --apply run died here with git's own message, after printing a
# full report that implied it was about to work. A precondition belongs at
# the top, in words that say what to do about it.
lock = SCRIPTS / ".git" / "index.lock"
if lock.exists():
    try:
        age = int(time.time() - lock.stat().st_mtime)
    except OSError:
        age = -1
    # -x on the process NAME, not -f on the command line: `pgrep -f "git "`
    # matches the shell that invoked this script, and reporting "a git process
    # IS running" when none is would leave you waiting on nothing.
    running = ""
    for name in ("git", "git-remote-http", "git-remote-https"):
        out = subprocess.run(["pgrep", "-lx", name],
                             capture_output=True, text=True).stdout.strip()
        if out:
            running += out + "\n"
    running = running.strip()
    print(f"⛔ {lock} exists — git will refuse to touch this repo.\n")
    print(f"   written {age}s ago" if age >= 0 else "   (cannot stat it)")
    if running:
        print("   a git process IS running — wait for it, do not delete "
              "the lock:\n")
        for line in running.splitlines()[:5]:
            print(f"       {line}")
    else:
        print("   no git process is running, so the lock is stale — most "
              "likely an interrupted commit_all.py.\n")
        print(f"       rm {lock}")
    die("the lock has to go first. Re-run this afterwards.")

# ── what is in HEAD ──────────────────────────────────────────────────────────
r = subprocess.run(["git", "show", "HEAD:ducorn_env.py"],
                   cwd=str(SCRIPTS), capture_output=True, text=True)
if r.returncode != 0:
    die("git has no HEAD copy of scripts/ducorn_env.py:\n  "
        + (r.stderr or "").strip()[:300]
        + "\n  Do not run --apply. The original may only exist in a backup.")

head_src = r.stdout
head_names = toplevel_names(head_src, "HEAD:ducorn_env.py")
disk_src = TARGET.read_text(encoding="utf-8")
disk_names = toplevel_names(disk_src, str(TARGET))

print(f"scripts/ducorn_env.py\n")
print(f"  in HEAD    {len(head_src.splitlines()):>5} lines   "
      f"defines {WANTED}: {'yes' if WANTED in head_names else 'NO'}")
print(f"  on disk    {len(disk_src.splitlines()):>5} lines   "
      f"defines {WANTED}: {'yes' if WANTED in disk_names else 'NO'}")

if WANTED not in head_names:
    die(f"the copy in HEAD does not define {WANTED} either. Restoring it "
        f"would not fix the ImportError. Stop and find the real original.")

if WANTED in disk_names:
    print(f"\n{WANTED} is already back on disk. Nothing to restore.")
    raise SystemExit(0)

if MINE not in disk_names:
    die(f"the file on disk is not the one I wrote (no top-level {MINE}()). "
        f"Something else changed it. Restoring would throw that away — "
        f"look at `git diff scripts/ducorn_env.py` first.")

lost = sorted(head_names - disk_names)
print(f"\n  restoring brings back {len(lost)} name(s): "
      + ", ".join(lost[:8]) + (" …" if len(lost) > 8 else ""))

# ── the importers ────────────────────────────────────────────────────────────
# .backup-<tag>-<timestamp>.py snapshots reference it too, in their dozens.
# Nothing imports or runs them; listing them buries the files that matter.
BACKUP = re.compile(r"\.backup-[^.]*\.py$")
SKIP = {".venv", "__pycache__", "_backups", ".git", ".superseded"}
# An actual import, not the mere string — otherwise this script, the checker
# and every patch script that mentions the name list themselves as importers.
IMPORTS = re.compile(r"^\s*(from\s+ducorn_env\s+import|import\s+ducorn_env)\b",
                     re.M)

roots = [DC / "scripts", DC / "ducorn", DC / "ducorn-products"]
importers, snapshots = [], 0
for root in roots:
    if not root.is_dir():
        continue
    for f in root.rglob("*.py"):
        if any(p in SKIP for p in f.parts) or f in (TARGET, NEWNAME):
            continue
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not IMPORTS.search(src):
            continue
        if BACKUP.search(f.name):
            snapshots += 1
        else:
            importers.append(f)

print(f"\n  {len(importers)} live file(s) import ducorn_env"
      + (f"  (+{snapshots} .backup-* snapshots, ignored)" if snapshots else "")
      + ":")
for f in sorted(importers):
    print(f"      {f.relative_to(DC)}")

# ── my module needs somewhere to live ────────────────────────────────────────
if not NEWNAME.exists():
    print(f"\n  ⚠️  {NEWNAME.name} is not beside this script yet. Copy it in "
          f"before re-running install_admin.py, or the admin service will "
          f"lose its env module.")

if not args.apply:
    print("\nRe-run with --apply to restore.")
    raise SystemExit(0)

# ── restore ──────────────────────────────────────────────────────────────────
# The checkout destroys the file on disk. If ducorn_envfile.py is already
# beside it, that same content is safe and no copy is needed — leaving a
# stray untracked file for commit_all.py to pick up would be its own mess.
# If it is NOT there, the file on disk is the only copy, so keep one.
stash = None
if not NEWNAME.exists():
    stash = SCRIPTS / "ducorn_envfile.py"
    try:
        shutil.copy2(TARGET, stash)
        print(f"\n  {NEWNAME.name} was missing — the file on disk is the only "
              f"copy, so it is moved there rather than discarded.")
    except OSError as e:
        die(f"could not preserve the overwriting file as {stash}: {e}")

r = subprocess.run(["git", "checkout", "HEAD", "--", "ducorn_env.py"],
                   cwd=str(SCRIPTS), capture_output=True, text=True)
if r.returncode != 0:
    die("git checkout failed:\n  " + (r.stdout + r.stderr).strip()[:400])

# stale bytecode of the wrong module would survive the checkout
removed = 0
for pyc in SCRIPTS.rglob("__pycache__/ducorn_env.*.pyc"):
    try:
        pyc.unlink()
        removed += 1
    except OSError:
        pass

# ── prove it ─────────────────────────────────────────────────────────────────
back = toplevel_names(TARGET.read_text(encoding="utf-8"), str(TARGET))
if WANTED not in back:
    sys.exit(f"RESTORED, BUT WRONG — {TARGET} still does not define {WANTED}. "
             f"Do not trust this. Look at the file.")

r = subprocess.run([sys.executable, "-c",
                    "import sys; sys.path.insert(0, %r); "
                    "import ducorn_env; ducorn_env.load_ducorn_env" % str(SCRIPTS)],
                   capture_output=True, text=True, timeout=60)
imported = r.returncode == 0

print(f"\nrestored. {len(head_src.splitlines())} lines, {WANTED} present, "
      f"{removed} stale .pyc removed.")
print(f"  import check: {'passes' if imported else 'FAILED'}")
if not imported:
    tail = (r.stderr or "").strip().splitlines()
    print("    " + (tail[-1][:200] if tail else "(no stderr)"))
    print("    (a missing third-party package here is fine — the name is back;\n"
          "     re-check with the venv python if this is a dependency error)")
print(f"  the env-file manager lives at {NEWNAME.name}.")
print(f"""
Next:
  python3 scripts/prove_module_names.py        # closes the class
  python3 scripts/install_admin.py --apply     # picks up ducorn_envfile.py
  python3 scripts/doctor.py                    # should return JSON again
""")
