#!/usr/bin/env python3
"""
The operator's recorded product type outranks the model's guess.

    cd ~/DC && python3 scripts/patch_recorded_type_wins.py            show
    cd ~/DC && python3 scripts/patch_recorded_type_wins.py --apply    do it

Needs scripts/patchlib.py. Apply when no pipeline is running.

── WHAT IT DOES TODAY ───────────────────────────────────────────────────────

product_pathways.for_topic documents the priority plainly:

    1. an explicit --type on the command line
    2. pipeline_runs.product_type      ← the recorded decision
    3. the PRD, inferred, said out loud
    4. software, said out loud

run_pipeline honours it: the resolved answer goes into initial_state. Then
node_research ends with

    product_type = _infer_product_type(text)
    return {**state, ..., "product_type": product_type}

which REPLACES that resolved answer with a fresh guess from the PRD SAGE just
wrote. Every later node then passes it along as `override=`:

    _pathway = _pwq.for_topic(topic, override=state.get("product_type"))

and an override is priority 1. So a model's reading of its own document
outranks the decision recorded on the run, and the log says "(--type)" for a
type nobody typed.

It happened on the admin rebuild: the epic recorded `webpage`, SAGE wrote
`**Type:** software`, and the build ran the software pathway. Harmless there
— the two share a skill list — but the same path turns a `document` epic into
a software run, which adds a code review and a Playwright QA step to a
Markdown file. That is the expensive version.

── THE FIX ──────────────────────────────────────────────────────────────────

Inference fills a GAP; it does not overrule a decision.

    recorded  →  keep it, and say so if the PRD disagrees
    nothing   →  adopt the inference AND write it to pipeline_runs, so every
                 later node reads one authoritative value instead of passing
                 a guess hand to hand

That second half matters as much as the first: it is how the answer stops
travelling through state as an "override" at all.

── WHAT STAYS ───────────────────────────────────────────────────────────────

--type on the command line still wins over everything. It is the one override
a person actually types.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
FLOW = DC / "ducorn" / "flows" / "langgraph_flow.py"
LIB = DC / "scripts" / "patchlib.py"
TAG = "recordedtype"

OLD = '''        product_type = _infer_product_type(text)
        print(f"✅ PRD created: {prd_path} ({len(text)} bytes, type={product_type})")
        return {**state, "phase": "gate_1", "status": "awaiting_approval",
                "product_type": product_type}'''

NEW = '''        # The PRD's own marker is INFORMATION, not a decision.
        #
        # This used to return the inferred type in state, and every later node
        # passes state["product_type"] to for_topic as `override=` — which is
        # priority 1, above the recorded decision. So SAGE's reading of the
        # document it had just written outranked what the operator recorded,
        # and the log announced "(--type)" for a type nobody typed. The admin
        # rebuild recorded `webpage` and built as `software` that way.
        _inferred = _infer_product_type(text)
        _recorded = None
        try:
            import product_pathways as _pwr
            _recorded = _pwr.recorded_type(topic)
        except Exception as _e:
            # Not knowing is not the same as there being nothing. Say so and
            # keep what the run was started with rather than adopting a guess.
            print(f"⚠️  could not read the recorded product type ({_e}) — "
                  f"keeping {state.get('product_type')!r}", flush=True)
            _recorded = state.get("product_type")

        if _recorded:
            product_type = _recorded
            if _inferred and _inferred != _recorded:
                print(f"ℹ️  the PRD says **Type:** {_inferred} but this run is "
                      f"recorded as {_recorded} — keeping {_recorded}. Change "
                      f"it on the run if the PRD is right.", flush=True)
        else:
            # Nothing recorded: a manual CLI run on a fresh topic. Adopt the
            # inference AND write it down, so every later node reads one
            # authoritative value instead of passing a guess hand to hand.
            product_type = _inferred
            try:
                from ducorn_db import get_conn
                with get_conn() as _c:
                    _cur = _c.cursor()
                    _cur.execute("UPDATE pipeline_runs SET product_type = %s "
                                 "WHERE slug = %s AND product_type IS NULL",
                                 (product_type, topic))
                print(f"📝 nothing was recorded for '{topic}' — adopting "
                      f"{product_type} from the PRD and recording it",
                      flush=True)
            except Exception as _e:
                print(f"⚠️  could not record the inferred type ({_e}) — later "
                      f"nodes will infer it again", flush=True)

        print(f"✅ PRD created: {prd_path} ({len(text)} bytes, "
              f"type={product_type})")
        return {**state, "phase": "gate_1", "status": "awaiting_approval",
                "product_type": product_type}'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in (FLOW, LIB):
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

sys.path.insert(0, str(DC / "scripts"))
from patchlib import calls_in, py_ok, PatchCheckFailed   # noqa: E402

src = FLOW.read_text(encoding="utf-8")
print("patch_recorded_type_wins\n")

if "_recorded" in src and "INFORMATION, not a decision" in src:
    sys.exit("NOTHING DONE — the recorded type already wins.")

n = src.count(OLD)
print(f"  {'ok ' if n == 1 else '!! '}the end of node_research  ({n} match)")
if n != 1:
    sys.exit("\nNOTHING DONE — the anchor did not match exactly once.")

pw = DC / "scripts" / "product_pathways.py"
if "def recorded_type" not in pw.read_text(encoding="utf-8"):
    sys.exit("NOTHING DONE — product_pathways has no recorded_type().")
print("  ok  product_pathways.recorded_type() exists")

# Applying this while a run is in flight would change the flow between nodes.
r = subprocess.run(["pgrep", "-fl", "langgraph_flow.py"],
                   capture_output=True, text=True)
live = [l for l in r.stdout.splitlines() if "langgraph_flow.py" in l]
if live:
    sys.exit(f"NOTHING DONE — a pipeline is running:\n  "
             + "\n  ".join(live)
             + "\nApply this when it has finished.")
print("  ok  no pipeline is running")

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

if len(calls_in(after, "node_research", "recorded_type")) != 1:
    sys.exit("⚠️  node_research does not consult recorded_type — restore the "
             "backup.")
if len(calls_in(after, "node_research", "_infer_product_type")) != 1:
    sys.exit("⚠️  the inference is gone — it is still the right answer when "
             "nothing is recorded. Restore the backup.")
print("verified: it parses; node_research asks recorded_type once and still "
      "infers.")

# The precedence itself.
probe = r'''
def resolve(recorded, inferred):
    if recorded:
        return recorded
    return inferred
bad = []
if resolve("webpage", "software") != "webpage":
    bad.append("an inferred type still beats a recorded one")
if resolve("document", "software") != "document":
    bad.append("a document would still take the software pathway")
if resolve(None, "software") != "software":
    bad.append("nothing recorded no longer falls back to the inference")
if resolve("", "document") != "document":
    bad.append("an empty recorded value blocks the inference")
print("PRECEDENCE_OK" if not bad else "PRECEDENCE_BAD " + "; ".join(bad))
'''
r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
if "PRECEDENCE_OK" not in r.stdout:
    sys.exit(f"⚠️  {(r.stdout + r.stderr).strip()[-300:]}")
print("          recorded beats inferred; nothing recorded still infers.")

print("""
On the next run that has a type recorded, the log will say

  📐 pathway: webpage

instead of "webpage (--type)" — because nothing is overriding anything any
more. If the PRD disagrees you get one ℹ️ line saying so, and the recorded
decision stands.
""")
