#!/usr/bin/env python3
"""
The jail's topic list must know every topic that ever ran, not only the tidy ones.

    cd ~/DC && python3 scripts/patch_jail_topics.py            show
    cd ~/DC && python3 scripts/patch_jail_topics.py --apply    do it

Apply patch_jail_exact.py first — this widens the topic list that one added.

── WHY ──────────────────────────────────────────────────────────────────────

patch_jail_exact decides who owns a file in docs/ by finding the LONGEST
known topic the filename starts with. That is only as good as "known".

It derives topics from two sources: a directory under products/, and a
"<topic>-gstack-checkpoint.json" in docs/. That set is 28 topics. The flow
logs show 46 have actually run — 18 topics left neither a directory nor a
checkpoint, because they failed early, were tests, or predate checkpointing.

The gap matters in one direction, and it is the direction that leaks.

Ownership is decided by the LONGER name. If the longer topic is unknown, the
shorter one wins by default and gets the files:

    docs/ducorn-technical-reference-guide-PRD.md

    'ducorn-technical-reference-guide'  unknown  → not a candidate
    'ducorn-technical-reference'        asking   → longest match → OWNER

so the shorter product is handed the longer product's document. Every one of
those 18 topics is a longer name that cannot currently defend its own files.

── THE FIX ──────────────────────────────────────────────────────────────────

Add logs/flow_<topic>.log as a third source. One is written for every run,
including the ones that died before writing anything else — which is exactly
the population the other two sources miss.

Costs nothing: the names are read once per process and cached, and a wider
topic list can only ever make ownership MORE specific. It cannot take a file
away from its real owner, because the owner is always the longest match and
the owner's own name is always a candidate.

── WHAT IT DOES NOT FIX ─────────────────────────────────────────────────────

A topic that has never run at all is still unknown, and a product whose name
is a prefix of it would win its files. That is unavoidable without an
authoritative registry — pipeline_runs in PostgreSQL is one, and reading it
from inside the agent's jail would mean a database connection in the hot path
of every file access. Worth doing only if this ever bites.
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
TAG = "jailtopics"

OLD = '''    try:
        for p in (PRODUCTS_DIR / "docs").glob("*" + _CHECKPOINT):
            topics.add(p.name[:-len(_CHECKPOINT)])
    except OSError:
        pass
    return frozenset(topics)'''

NEW = '''    try:
        for p in (PRODUCTS_DIR / "docs").glob("*" + _CHECKPOINT):
            topics.add(p.name[:-len(_CHECKPOINT)])
    except OSError:
        pass
    # Third source: one flow log per run, written before anything else and
    # kept even when the run dies early. Without it 18 topics that had really
    # run were unknown here — and an unknown LONGER topic loses its files to
    # a shorter one, because ownership goes to the longest name that matches.
    try:
        for p in (PRODUCTS_DIR.parent / "logs").glob("flow_*.log"):
            topics.add(p.stem[len("flow_"):])
    except OSError:
        pass
    return frozenset(topics)'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

if not JAIL.is_file():
    sys.exit(f"NOTHING DONE — {JAIL} is not there")

src = JAIL.read_text(encoding="utf-8")

print("patch_jail_topics\n")
if "_known_topics" not in src:
    sys.exit("NOTHING DONE — apply patch_jail_exact.py first; "
             "there is no topic list to widen.")
n = src.count(OLD)
print(f"  {'ok ' if n == 1 else '!! '}the checkpoint source block  ({n} match)")
if n != 1:
    sys.exit("\nNOTHING DONE — the anchor did not match exactly once.")

# Measure the gap on the real machine.
P = DC / "ducorn-products"
CK = "-gstack-checkpoint.json"
dirs = ck = flow = set()
try:
    dirs = {d.name for d in (P / "products").iterdir() if d.is_dir()}
except OSError:
    pass
try:
    ck = {p.name[:-len(CK)] for p in (P / "docs").glob("*" + CK)}
except OSError:
    pass
try:
    flow = {p.stem[len("flow_"):] for p in (DC / "logs").glob("flow_*.log")}
except OSError:
    pass

known, wider = dirs | ck, dirs | ck | flow
gained = sorted(wider - known)
print(f"\n  topics known now {len(known)}  ·  with flow logs {len(wider)}")
print(f"  {len(gained)} topic(s) that ran but cannot currently defend their files:")
for t in gained:
    at_risk = sorted(a for a in wider if a != t and t.startswith(a + "-"))
    files = [f.name for f in (P / "docs").glob(t + "-*") if f.is_file()]
    if at_risk and files:
        print(f"      {t}  —  {len(files)} file(s), claimable by "
              f"{', '.join(at_risk)}")
    elif at_risk:
        print(f"      {t}  —  no files yet, claimable by {', '.join(at_risk)}")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(JAIL, JAIL.with_suffix(f".backup-{TAG}-{stamp}.py"))
JAIL.write_text(src.replace(OLD, NEW, 1), encoding="utf-8")
print(f"\nwrote {JAIL.name}, backup tagged {TAG}-{stamp}")

r = subprocess.run([sys.executable, "-m", "py_compile", str(JAIL)],
                   capture_output=True, text=True)
if r.returncode != 0:
    sys.exit(f"⚠️  it does not parse — restore the backup:\n{r.stderr[-400:]}")

probe = f'''
import sys
sys.path.insert(0, "{DC}/ducorn/tools")
from product_jail import resolve_in_jail, PathEscape, docs_owner, _known_topics
import pathlib

topics = _known_topics()
docs = pathlib.Path("{DC}/ducorn-products/docs")
bad, blocked, own = [], 0, 0

for short in sorted(topics):
    for longer in sorted(topics):
        if longer == short or not longer.startswith(short + "-"):
            continue
        for f in sorted(docs.glob(longer + "-*")):
            if not f.is_file():
                continue
            blocked += 1
            try:
                resolve_in_jail(short, "docs/" + f.name)
                bad.append(short + " can still read " + f.name)
            except PathEscape:
                pass

for t in sorted(topics):
    for f in sorted(docs.glob(t + "-*")):
        if not f.is_file() or docs_owner(f.name) != t:
            continue
        own += 1
        try:
            resolve_in_jail(t, "docs/" + f.name)
        except PathEscape:
            bad.append(t + " lost its own " + f.name)

print("OK topics=%d blocked=%d own=%d" % (len(topics), blocked, own)
      if not bad else "BAD " + "; ".join(bad[:6]))
'''
r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
if not r.stdout.startswith("OK"):
    sys.exit(f"⚠️  VERIFICATION FAILED — restore the backup:\n"
             f"{(r.stdout + r.stderr).strip()[-600:]}")

print(f"""
verified on the real docs/ directory: {r.stdout.strip()[3:]}

  blocked = cross-product reads that now raise PathEscape
  own     = files each product still reaches, unchanged
""")
