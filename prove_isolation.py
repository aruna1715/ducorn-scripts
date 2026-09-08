#!/usr/bin/env python3
"""
What one deployed product can reach that belongs to another.

    cd ~/DC && python3 scripts/prove_isolation.py
    cd ~/DC && python3 scripts/prove_isolation.py --quiet

Exit 0 when every ENFORCED boundary holds. Exit 1 when one is broken.

── WHY THIS EXISTS ──────────────────────────────────────────────────────────

"I DONOT want product 1 to read product2's file EVER" is a showstopper
requirement, and product_jail.py is usually offered as the answer. It is not.
The jail constrains the AGENT while it writes a product. This file is about
the product afterwards: a launchd service, running as the user `ducorn`, with
whatever its plist gives it.

The gap was found by measurement, not by reasoning: every deployed product's
plist carried PYTHONPATH=/Users/ducorn/DC/scripts, which made
`import ducorn_env; load_ducorn_env()` — and therefore all 39 secrets in
shared/.env — available to any of them.

── ENFORCED vs NOT ENFORCED ─────────────────────────────────────────────────

This script reports two different things and does not blur them, because a
security check that implies more than it verifies is worse than none.

  ENFORCED   a boundary something actually stops. These FAIL the run.
  OPEN       a boundary nothing stops today, listed so it is a decision
             rather than a surprise. These do not fail the run; they are
             printed every time so they stay uncomfortable.

Today the only enforced boundary is the import path. Everything else on the
OPEN list needs a separate UNIX user or a container, and pretending otherwise
would be the exact "control that exists and does not reach the thing it
governs" pattern this codebase keeps producing.
"""
from __future__ import annotations

import argparse
import ast
import os
import plistlib
import re
import sys
from pathlib import Path

DC = Path(os.environ.get("DUCORN_ROOT", "/Users/ducorn/DC"))
LAUNCHD = DC / "launchd"
PRODUCTS = DC / "ducorn-products" / "products"
SHARED_ENV = DC / "shared" / ".env"

# .backup-<tag>-<timestamp>.py snapshots. Nothing imports them and nothing
# runs them. The first version of this file counted them, and reported that
# ducorn-activity-api "reaches into DuCorn's plumbing" seventeen times — all
# of them backups of one stack service that has exactly one live file.
BACKUP = re.compile(r"\.backup-[^.]*\.py$")

INTERNAL = {"ducorn_env", "ducorn_db", "product_paths", "product_pathways",
            "stack_context", "ducorn_spend", "bootstrap_python", "product_jail",
            "drive_routing", "stack_facts"}

STACK = {"com.ducorn.admin", "com.ducorn.api", "com.ducorn.pdf",
         "com.ducorn.slack", "com.ducorn.dashboard", "com.ducorn.router",
         "com.ducorn.litellm", "com.ducorn.ollama", "com.ducorn.cloudflare"}

ap = argparse.ArgumentParser()
ap.add_argument("--quiet", action="store_true")
args = ap.parse_args()

failures, open_items, notes = [], [], []


def jobs():
    for f in sorted(LAUNCHD.glob("com.ducorn.*.plist")):
        if ".backup-" in f.name:
            continue
        try:
            d = plistlib.loads(f.read_bytes())
        except Exception as e:
            notes.append(f"{f.name}: cannot parse ({e})")
            continue
        label = d.get("Label", "")
        if not label:
            continue
        yield f, label, d


def product_jobs():
    for f, label, d in jobs():
        if label not in STACK:
            yield f, label, d


def stack_dirs() -> set:
    """
    Directories under products/ that are actually STACK services.

    ducorn-activity-api and ducorn-admin live in products/ because that is
    where the deployer puts things, but they are DuCorn's own code and are
    supposed to import DuCorn's own modules. Judging by the folder's location
    would file them as products and report every import as a violation —
    which is what the first version of this file did.

    Derived from the plists: whatever a stack job runs out of is stack.
    """
    out = set()
    for f, label, d in jobs():
        if label not in STACK:
            continue
        wd = d.get("WorkingDirectory")
        if not wd:
            continue
        p = Path(wd)
        try:
            if p.resolve().parent == PRODUCTS.resolve():
                out.add(p.name)
        except OSError:
            pass
    return out


def product_dir_for(label: str):
    """
    The directory a product job actually owns, or None.

    NOT WorkingDirectory: com.ducorn.ducorn-spend-status-web runs from
    /Users/ducorn/DC, and scanning that walks the entire repo. The first
    version did, and reported that one product imported nine DuCorn
    internals — it had found every internal import in the codebase.

    The deployer names a job after the product it deploys, with -web / -api
    for the two halves of a page+api product.
    """
    short = label.replace("com.ducorn.", "")
    for name in (short, short[:-4] if short.endswith("-web") else None,
                 short[:-4] if short.endswith("-api") else None):
        if not name:
            continue
        d = PRODUCTS / name
        if d.is_dir():
            return d
    return None


def secret_names() -> set:
    try:
        return {l.split("=", 1)[0].strip()
                for l in SHARED_ENV.read_text(errors="replace").splitlines()
                if "=" in l and not l.lstrip().startswith("#")}
    except OSError:
        return set()


# ═════════════════════════════════════════════════════════════════════════════
# ENFORCED
# ═════════════════════════════════════════════════════════════════════════════

# 1. No product may have DuCorn's own modules on its import path.
guilty = []
for f, label, d in product_jobs():
    env = d.get("EnvironmentVariables") or {}
    pp = env.get("PYTHONPATH", "")
    if not pp:
        continue
    for part in pp.split(":"):
        p = Path(part)
        if not part:
            continue
        try:
            p.resolve().relative_to(DC.resolve())
        except (ValueError, OSError):
            continue          # outside ~/DC — not ours to police
        guilty.append(f"{label.replace('com.ducorn.','')}  →  {part}")
if guilty:
    failures.append(
        ("a product can import DuCorn's internals",
         "PYTHONPATH points inside ~/DC for:\n      " + "\n      ".join(guilty)
         + "\n    That makes ducorn_env importable, and load_ducorn_env() "
           "reads every key in shared/.env.\n"
           "    Fix: python3 scripts/patch_product_pythonpath.py --apply"))

# 2. No product's own source may import a DuCorn internal.
_stack_dirs = stack_dirs()
importers = []
for d in (sorted(PRODUCTS.iterdir()) if PRODUCTS.is_dir() else []):
    if not d.is_dir() or d.name in _stack_dirs or d.name == "_shared":
        continue
    for p in d.rglob("*.py"):
        if ".venv" in p.parts or "__pycache__" in p.parts:
            continue
        if BACKUP.search(p.name):
            continue
        try:
            tree = ast.parse(p.read_text(errors="replace"))
        except (OSError, SyntaxError):
            continue
        for n in ast.walk(tree):
            mods = []
            if isinstance(n, ast.Import):
                mods = [a.name.split(".")[0] for a in n.names]
            elif isinstance(n, ast.ImportFrom):
                mods = [(n.module or "").split(".")[0]]
            hit = [m for m in mods if m in INTERNAL]
            if hit:
                importers.append(f"{d.name}/{p.relative_to(d)}:{n.lineno}  "
                                 f"imports {', '.join(hit)}")
if importers:
    failures.append(
        ("a product's code reaches into DuCorn's plumbing",
         "\n      ".join(importers[:12])
         + ("\n      …" if len(importers) > 12 else "")
         + "\n    A product needing a DuCorn module is a design problem: "
           "vendor what it needs into the product."))

# 3. No product plist may carry a value that is a secret from shared/.env.
#    Names, not values — this script never prints a secret.
shared = secret_names()
SECRETISH = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
carried = []
for f, label, d in product_jobs():
    env = d.get("EnvironmentVariables") or {}
    for k in env:
        if k in shared and any(s in k.upper() for s in SECRETISH):
            carried.append(f"{label.replace('com.ducorn.','')}  →  {k}")
if carried:
    failures.append(
        ("a product plist carries a shared secret",
         "\n      ".join(carried)
         + "\n    Each of these is a key from shared/.env copied into a "
           "product's environment. Give the product its own credential, or "
           "remove it."))


# ═════════════════════════════════════════════════════════════════════════════
# OPEN — nothing stops these today
# ═════════════════════════════════════════════════════════════════════════════

open_items.append((
    "every product runs as the same UNIX user",
    "A product can open /Users/ducorn/DC/shared/.env by absolute path, read "
    "any other product's directory, and write anywhere `ducorn` can write. "
    "Closing this needs a separate user per product, or a container."))

ports = []
for f, label, d in jobs():
    env = d.get("EnvironmentVariables") or {}
    for k, v in env.items():
        if k.endswith("_PORT") and str(v).isdigit():
            ports.append((label.replace("com.ducorn.", ""), str(v)))
open_items.append((
    "every service shares localhost",
    f"{len(ports)} service(s) listen on 127.0.0.1 with no authentication "
    f"between them. Any product can call any other product's API, and the "
    f"activity API on :8000, directly."))

dburl = [label.replace("com.ducorn.", "")
         for f, label, d in product_jobs()
         if any("DATABASE_URL" in k or "postgres" in str(v).lower()
                for k, v in (d.get("EnvironmentVariables") or {}).items())]
if dburl:
    open_items.append((
        "products share one PostgreSQL role",
        f"{', '.join(dburl)} connect as the same role DuCorn uses, so a "
        f"product with a database URL can read pipeline_runs, "
        f"approval_requests and LiteLLM_SpendLogs — not only its own data. "
        f"Needs a per-product role with a grant on its own schema."))

# Port headroom is a capacity fact, not a security one, but it decides when
# this architecture stops working at all.
used = {int(v) for _, v in ports if v.isdigit() and 8090 <= int(v) <= 8099}
open_items.append((
    "the port range is nearly full",
    f"products are allocated from 8090; {len(used)} of 10 slots are taken. "
    f"At ten products the deployer has nowhere to put the eleventh."))


# ═════════════════════════════════════════════════════════════════════════════
# report
# ═════════════════════════════════════════════════════════════════════════════
print("DuCorn product isolation\n")

if not args.quiet:
    print("ENFORCED — these fail this check\n")
if failures:
    for title, detail in failures:
        print(f"  ❌ {title}")
        print(f"     {detail}\n")
else:
    print("  ✅ no product can import DuCorn's modules")
    print("  ✅ no product's code reaches into DuCorn's plumbing")
    print("  ✅ no product plist carries a shared secret\n")

print("OPEN — nothing stops these today. Listed so they are decisions.\n")
for title, detail in open_items:
    print(f"  ⚠️  {title}")
    print(f"     {detail}\n")

for n in notes:
    print(f"  note: {n}")

if failures:
    print(f"{len(failures)} enforced boundary/boundaries broken.")
    raise SystemExit(1)

print("Every enforced boundary holds. The OPEN list is the real work:\n"
      "a container or a separate user per product closes all four at once.")
