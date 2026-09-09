#!/usr/bin/env python3
"""
Three phases would deploy three services. An epic is one product.

    cd ~/DC && python3 scripts/patch_deploy_label.py            show
    cd ~/DC && python3 scripts/patch_deploy_label.py --apply    do it

Needs scripts/product_dir.py and scripts/patchlib.py.

── WHAT WOULD HAVE HAPPENED ─────────────────────────────────────────────────

node_deploy calls the deploy tool with the TOPIC:

    result = tool._run(topic, "main.py", None, product_type)

and the tool builds its launchd label from what it is given:

    "label": f"com.ducorn.{slug}"

So the admin rebuild would have produced

    com.ducorn.ducorn-admin-rebuild-p1-config     phase 1
    com.ducorn.ducorn-admin-rebuild-p2-services   phase 2
    com.ducorn.ducorn-admin-rebuild-p3-health     phase 3

three services on three ports, all running out of the SAME directory, each
one a slightly older copy of the product than the next. Phase 2 would not
replace phase 1; it would sit beside it. Whichever you opened would be
whichever port you remembered.

The point of an epic is one product built over several runs. One product is
one service.

── THE FIX ──────────────────────────────────────────────────────────────────

Deploy is told the product, not the run. product_dir.for_topic(topic).name is
the directory the phase built into — ducorn-admin-rebuild — so phase 2
redeploys the same label over the same port, which is what a redeploy is.

For a standalone product the name IS the topic, so nothing changes for
anything built before epics existed.

── WHAT STAYS WITH THE RUN ──────────────────────────────────────────────────

_store_product_url keeps the topic. The URL is recorded against the run that
produced it, and each phase is its own run — that is the record you want when
asking which phase put the current thing live.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
FLOW = DC / "ducorn" / "flows" / "langgraph_flow.py"
PD = DC / "scripts" / "product_dir.py"
LIB = DC / "scripts" / "patchlib.py"
TAG = "deploylabel"

OLD = '''            from tools.DuCornDeployTool import DuCornDeployTool
            tool = DuCornDeployTool()
            if product_type == "api":
                result = tool._run(topic, "main:app", None, "api")
            else:
                result = tool._run(topic, "main.py", None, product_type)'''

NEW = '''            from tools.DuCornDeployTool import DuCornDeployTool
            tool = DuCornDeployTool()

            # The PRODUCT, not the run. The deploy tool builds its launchd
            # label as com.ducorn.<what it is given>, so passing the topic
            # would have given an epic one service per phase — three
            # services on three ports out of one directory, each an older
            # copy than the next, and phase 2 sitting beside phase 1 rather
            # than replacing it.
            #
            # For a standalone product the directory name IS the topic, so
            # nothing changes for anything built before epics existed.
            _deploy_as = _product_dir(topic).name
            if _deploy_as != topic:
                print(f"⚙️  deploying as '{_deploy_as}' — {topic} is a phase "
                      f"of it", flush=True)
            if product_type == "api":
                result = tool._run(_deploy_as, "main:app", None, "api")
            else:
                result = tool._run(_deploy_as, "main.py", None, product_type)'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in (FLOW, PD, LIB):
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

sys.path.insert(0, str(DC / "scripts"))
from patchlib import calls_in, py_ok, PatchCheckFailed   # noqa: E402

src = FLOW.read_text(encoding="utf-8")
print("patch_deploy_label\n")

if "_deploy_as" in src:
    sys.exit("NOTHING DONE — deploy already uses the product directory.")

if "def _product_dir" not in src:
    sys.exit("NOTHING DONE — apply patch_build_dir_everywhere.py first; "
             "this uses the _product_dir helper it adds.")
print("  ok  _product_dir() is in this file")

n = src.count(OLD)
print(f"  {'ok ' if n == 1 else '!! '}the deploy call  ({n} match)")
if n != 1:
    sys.exit("\nNOTHING DONE — the anchor did not match exactly once.")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(FLOW, FLOW.with_suffix(f".backup-{TAG}-{stamp}.py"))
FLOW.write_text(src.replace(OLD, NEW, 1), encoding="utf-8")
print(f"\nwrote {FLOW.name}, backup tagged {TAG}-{stamp}")

after = FLOW.read_text(encoding="utf-8")
try:
    py_ok(after, "langgraph_flow.py")
except PatchCheckFailed as e:
    sys.exit(f"⚠️  {e} — restore the backup.")

# Scoped to the function changed — not a count over the file, which reported
# a correct patch as broken twice today.
runs = calls_in(after, "node_deploy", "_run")
if len(runs) != 2:
    sys.exit(f"⚠️  node_deploy has {len(runs)} deploy calls, expected 2 — "
             f"restore the backup.")
if any("(topic," in c for c in runs):
    sys.exit("⚠️  a deploy call still passes the topic — restore the backup.")
if len(calls_in(after, "node_deploy", "_product_dir")) != 1:
    sys.exit("⚠️  node_deploy does not resolve the product once — restore "
             "the backup.")
print("verified: both deploy calls pass the resolved product, and it is "
      "resolved once.")

print("""
At deploy you should see, for a phase:

  ⚙️  deploying as 'ducorn-admin-rebuild' — ducorn-admin-rebuild-p1-config
     is a phase of it

and one service, com.ducorn.ducorn-admin-rebuild, that phases 2 and 3
redeploy rather than multiply.
""")
