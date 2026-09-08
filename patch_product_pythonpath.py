#!/usr/bin/env python3
"""
A deployed product must not have DuCorn's internals on its import path.

    cd ~/DC && python3 scripts/patch_product_pythonpath.py            show
    cd ~/DC && python3 scripts/patch_product_pythonpath.py --apply    do it

── THE LEAK ─────────────────────────────────────────────────────────────────

Every product the deployer ships gets this in its launchd plist:

    PYTHONPATH = /Users/ducorn/DC/scripts

which puts ducorn_env.py on the product's import path. So any deployed
product can do

    import ducorn_env; ducorn_env.load_ducorn_env()

and read all 39 entries of shared/.env — every LLM key, the database URL,
the Slack bot token, the dashboard password. It does not have to be
malicious; a generated product that copies a pattern from somewhere else in
the tree gets there by accident.

The build-time jail is not involved. product_jail.py constrains the AGENT
while it writes the product. This is the product afterwards, running as a
launchd service, with the whole scripts directory importable.

Six products carry it today. NONE of them imports anything from it — checked
by parsing every .py in each product directory for imports of ducorn_env,
ducorn_db, product_paths, product_pathways, stack_context or ducorn_spend.
So this line has never been load-bearing; it is a default that grants
everything and is used by nothing.

── WHAT THIS DOES ───────────────────────────────────────────────────────────

  1. Stops the deployer emitting it, so products built from now on never
     have it. This is the actual fix — the plists are output.

  2. Rewrites the existing product plists to drop it, but ONLY where the
     product provably does not import those modules. Anything that would
     break is left alone and reported.

  3. Leaves the stack services alone. admin, api, pdf and slack are DuCorn's
     own code and are supposed to import DuCorn's own modules.

── WHAT IT DOES NOT FIX ─────────────────────────────────────────────────────

Products still run as the user `ducorn`, so a product can still read
shared/.env by its absolute path. Closing THAT needs a separate user or a
container, which is the next task. This closes the accidental route — the
one a generated product falls into without trying — not the deliberate one.

scripts/prove_isolation.py reports both, and is honest about which is which.
"""
from __future__ import annotations

import argparse
import ast
import plistlib
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
DEPLOY = DC / "ducorn" / "tools" / "DuCornDeployTool.py"
LAUNCHD = DC / "launchd"
AGENTS = Path.home() / "Library" / "LaunchAgents"
PRODUCTS = DC / "ducorn-products" / "products"
TAG = "nopypath"

# DuCorn's own modules. A product importing one of these is reaching into the
# company's plumbing, not using a library.
INTERNAL = {"ducorn_env", "ducorn_db", "product_paths", "product_pathways",
            "stack_context", "ducorn_spend", "bootstrap_python", "product_jail",
            "drive_routing", "stack_facts"}

# Stack services: DuCorn's own code, deployed the same way. These SHOULD have
# the scripts directory — it is where they live.
STACK = {"com.ducorn.admin", "com.ducorn.api", "com.ducorn.pdf",
         "com.ducorn.slack", "com.ducorn.dashboard", "com.ducorn.router",
         "com.ducorn.litellm", "com.ducorn.ollama", "com.ducorn.cloudflare"}

OLD = '''            env_entries = {"HOME": "/Users/ducorn",
                           "PYTHONPATH": "/Users/ducorn/DC/scripts",
                           **product_env}'''

NEW = '''            # NO PYTHONPATH.
            #
            # This used to put /Users/ducorn/DC/scripts on every deployed
            # product's import path, which made ducorn_env importable — and
            # `ducorn_env.load_ducorn_env()` reads all of shared/.env. Every
            # product shipped with the ability to read every key DuCorn owns,
            # by accident rather than by need: of the six products deployed
            # when this was found, not one imported anything from it.
            #
            # A product needing a DuCorn module is a design smell, not a path
            # problem — it means the product is reaching into the company's
            # plumbing. Vendor what it needs into the product instead.
            env_entries = {"HOME": "/Users/ducorn",
                           **product_env}'''


BACKUP = re.compile(r"\.backup-[^.]*\.py$")


def product_dir_for(label: str):
    """
    The directory a product job owns, or None.

    NOT WorkingDirectory. com.ducorn.ducorn-spend-status-web runs from
    /Users/ducorn/DC, so scanning WorkingDirectory walked the whole repo and
    reported that one product imported nine DuCorn internals — it had found
    every internal import in the codebase, and the plist was left unpatched
    on the strength of it.
    """
    short = label.replace("com.ducorn.", "")
    names = [short]
    for suffix in ("-web", "-api"):
        if short.endswith(suffix):
            names.append(short[: -len(suffix)])
    for name in names:
        d = PRODUCTS / name
        if d.is_dir():
            return d
    return None


def imports_internal(product_dir) -> set:
    """Which DuCorn internals this product's own code imports."""
    found = set()
    if product_dir is None or not product_dir.is_dir():
        return found
    for p in product_dir.rglob("*.py"):
        if ".venv" in p.parts or "__pycache__" in p.parts:
            continue
        if BACKUP.search(p.name):
            continue          # snapshots of previous versions; nothing runs them
        try:
            tree = ast.parse(p.read_text(errors="replace"))
        except (OSError, SyntaxError):
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                for a in n.names:
                    if a.name.split(".")[0] in INTERNAL:
                        found.add(a.name.split(".")[0])
            elif isinstance(n, ast.ImportFrom):
                mod = (n.module or "").split(".")[0]
                if mod in INTERNAL:
                    found.add(mod)
    return found


ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

if not DEPLOY.is_file():
    sys.exit(f"NOTHING DONE — {DEPLOY} is not there")

deploy_src = DEPLOY.read_text(encoding="utf-8")

print("patch_product_pythonpath\n")
n = deploy_src.count(OLD)
already = "NO PYTHONPATH." in deploy_src
if already:
    print("  ok  the deployer no longer emits PYTHONPATH (already patched)")
else:
    print(f"  {'ok ' if n == 1 else '!! '}the deployer's env_entries  ({n} match)")
    if n != 1:
        sys.exit("\nNOTHING DONE — the anchor did not match exactly once.")

# ── which plists carry it, and would any of them break ──────────────────────
rows = []
for f in sorted(LAUNCHD.glob("com.ducorn.*.plist")):
    try:
        d = plistlib.loads(f.read_bytes())
    except Exception as e:
        print(f"  !! {f.name}: cannot parse ({e})")
        continue
    label = d.get("Label", "")
    env = d.get("EnvironmentVariables") or {}
    if "PYTHONPATH" not in env:
        continue
    if label in STACK:
        continue                      # DuCorn's own code, deliberately
    pdir = product_dir_for(label)
    uses = imports_internal(pdir)
    rows.append((f, label, env["PYTHONPATH"], uses, pdir))

print(f"\n  {len(rows)} product plist(s) put DuCorn's scripts on the import path:")
for f, label, pp, uses, pdir in rows:
    if uses:
        verdict = "WOULD BREAK — imports " + ", ".join(sorted(uses))
    elif pdir is None:
        verdict = "no product directory — nothing of its own to import with"
    else:
        verdict = "safe to remove — imports nothing from it"
    print(f"      {label.replace('com.ducorn.',''):34} {verdict}")
if not rows:
    print("      (none)")

breaks = [r for r in rows if r[3]]
if breaks:
    print(f"\n  ⚠️  {len(breaks)} product(s) genuinely import DuCorn internals. "
          f"Those plists are left alone; the product needs the module vendored "
          f"into it before the path can go.")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

# ── 1. the deployer ─────────────────────────────────────────────────────────
if not already:
    shutil.copy2(DEPLOY, DEPLOY.with_suffix(f".backup-{TAG}-{stamp}.py"))
    DEPLOY.write_text(deploy_src.replace(OLD, NEW, 1), encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "py_compile", str(DEPLOY)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"⚠️  {DEPLOY.name} does not parse — restore the backup:\n"
                 f"{r.stderr[-400:]}")
    print(f"\nwrote {DEPLOY.name} — new products get no PYTHONPATH")

# ── 2. the existing plists ──────────────────────────────────────────────────
changed = []
for f, label, pp, uses, pdir in rows:
    if uses:
        continue
    backup = f.with_suffix(f".backup-{TAG}-{stamp}.plist")
    shutil.copy2(f, backup)
    d = plistlib.loads(f.read_bytes())
    d["EnvironmentVariables"].pop("PYTHONPATH", None)
    f.write_bytes(plistlib.dumps(d))
    # LaunchAgents holds a COPY, not a symlink — both have to change or the
    # running service keeps the old environment.
    live = AGENTS / f.name
    if live.is_file():
        shutil.copy2(f, live)
    changed.append(label)

print(f"rewrote {len(changed)} plist(s): {', '.join(l.replace('com.ducorn.','') for l in changed) or 'none'}")

# ── 3. restart them, and check they came back ───────────────────────────────
import os
import time

uid = os.getuid()
failed = []
for label in changed:
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{label}"],
                   capture_output=True, text=True)
    time.sleep(1)
    subprocess.run(["launchctl", "bootstrap", f"gui/{uid}",
                    str(AGENTS / f"{label}.plist")],
                   capture_output=True, text=True)
    subprocess.run(["launchctl", "kickstart", "-k", f"gui/{uid}/{label}"],
                   capture_output=True, text=True)

time.sleep(3)
for label in changed:
    r = subprocess.run(["launchctl", "list", label],
                       capture_output=True, text=True)
    if r.returncode != 0:
        failed.append(label)

if failed:
    print(f"\n⚠️  did not come back up: {', '.join(failed)}")
    print(f"    the plists are backed up as *.backup-{TAG}-{stamp}.plist")
    print(f"    tail -20 {DC}/logs/<name>.log")
    raise SystemExit(1)

print(f"""
all {len(changed)} restarted and running.

Next:
  python3 scripts/prove_isolation.py     what is still shared, honestly
  python3 scripts/doctor.py
""")
