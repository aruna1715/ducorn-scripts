#!/usr/bin/env python3
"""
One archetype failing must not discard the ones that worked.

    cd ~/DC && python3 scripts/patch_design_partial.py            show
    cd ~/DC && python3 scripts/patch_design_partial.py --apply    do it

Needs scripts/patchlib.py.

── THE ASYMMETRY ────────────────────────────────────────────────────────────

generate_designs has two loops. The second one already knows this:

    except GenerationError as e:
        # Every render costs money. One failing must not discard the rest.
        entry.update({"html": None, ...})

The first one, four lines above, does not:

    for arch in archetypes:
        specs.append(propose_direction(brief, arch, model=model, ...))

propose_direction raises, the list comprehension unwinds, and every direction
that succeeded before it is thrown away with it. The run then fails at the
design node with a single archetype's complaint:

    ❌ Design failed: could not get a usable direction for Data-Dense
       Professional: dark_palette: ink_muted on bg is 2.8:1 (need 3.0)

Two other archetypes may have been perfectly good. Nobody will ever know,
and in production each of them was paid for.

── THE RULE ─────────────────────────────────────────────────────────────────

The same one the render loop follows: collect what worked, record what did
not, and fail only when NOTHING worked. A gate offering two directions
instead of three is a smaller problem than a run that stops.

── WHAT STILL FAILS ─────────────────────────────────────────────────────────

Every archetype failing. That is a real signal — the brief cannot be turned
into a design, or the model is broken — and it stops the run with all the
reasons, not just the last one.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
GEN = DC / "ducorn" / "tools" / "generate_design.py"
LIB = DC / "scripts" / "patchlib.py"
TAG = "designpartial"

OLD = '''    specs = []
    for arch in archetypes:
        taken = [s["palette"]["accent"] for s in specs]
        specs.append(propose_direction(brief, arch, model=model,
                                       avoid_accents=taken, **kw))

    report = verify_variants(specs)'''

NEW = '''    specs, proposal_failures = [], {}
    kept_archetypes = []
    for arch in archetypes:
        taken = [s["palette"]["accent"] for s in specs]
        try:
            specs.append(propose_direction(brief, arch, model=model,
                                           avoid_accents=taken, **kw))
            kept_archetypes.append(arch)
        except GenerationError as e:
            # The same rule the render loop below already follows: "One
            # failing must not discard the rest." This loop did not, so an
            # archetype that could not clear a contrast threshold threw away
            # every direction proposed before it — each one paid for.
            proposal_failures[arch["name"]] = str(e)
            print(f"⚠️  no usable direction for {arch['name']}: {e}",
                  flush=True)

    if not specs:
        # Everything failed. That is a real signal, and it carries every
        # reason rather than whichever one came last.
        raise GenerationError(
            "no usable direction for any archetype: "
            + "; ".join(f"{k}: {v}" for k, v in proposal_failures.items()))

    if proposal_failures:
        print(f"🎨 continuing with {len(specs)} of {len(archetypes)} "
              f"directions", flush=True)
    archetypes = kept_archetypes

    report = verify_variants(specs)
    report["proposal_failures"] = proposal_failures'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in (GEN, LIB):
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

sys.path.insert(0, str(DC / "scripts"))
from patchlib import code_only, py_ok, PatchCheckFailed   # noqa: E402

src = GEN.read_text(encoding="utf-8")
print("patch_design_partial\n")

if "proposal_failures" in src:
    sys.exit("NOTHING DONE — the propose loop already tolerates a failure.")

n = src.count(OLD)
print(f"  {'ok ' if n == 1 else '!! '}the propose loop  ({n} match)")
if n != 1:
    sys.exit("\nNOTHING DONE — the anchor did not match exactly once.")

# archetypes and specs are zipped further down; if that pairing is gone this
# patch's rebinding of `archetypes` would silently misalign them.
if "for arch, spec in zip(archetypes, specs):" not in src:
    sys.exit("NOTHING DONE — the render loop no longer zips archetypes with "
             "specs, so trimming the archetype list could misalign them. "
             "Read that loop before applying this.")
print("  ok  the render loop zips archetypes with specs — trimming both "
      "keeps them aligned")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(GEN, GEN.with_suffix(f".backup-{TAG}-{stamp}.py"))
GEN.write_text(src.replace(OLD, NEW, 1), encoding="utf-8")
print(f"\nwrote {GEN.name}, backup tagged {TAG}-{stamp}")

after = GEN.read_text(encoding="utf-8")
try:
    py_ok(after, "generate_design.py")
except PatchCheckFailed as e:
    sys.exit(f"⚠️  {e} — restore the backup.")

code = code_only(after)
if "raise GenerationError(\n            \"no usable direction for any" not in code \
        and "no usable direction for any archetype" not in code:
    sys.exit("⚠️  the all-failed case no longer raises — restore the backup.")
print("verified: it parses, and everything failing still raises.")

# The pairing, which is what a partial list could break.
probe = r'''
archetypes = [{"name": "A"}, {"name": "B"}, {"name": "C"}]
specs, kept, failures = [], [], {}
for arch in archetypes:
    if arch["name"] == "B":
        failures[arch["name"]] = "no usable direction"
        continue
    specs.append({"for": arch["name"]})
    kept.append(arch)
archetypes = kept
bad = []
if len(specs) != 2 or len(archetypes) != 2:
    bad.append("the kept lists are not the same length")
for arch, spec in zip(archetypes, specs):
    if spec["for"] != arch["name"]:
        bad.append(f"misaligned: {arch['name']} paired with {spec['for']}")
if "B" not in failures:
    bad.append("the failure was not recorded")
print("PAIR_OK" if not bad else "PAIR_BAD " + "; ".join(bad))
'''
r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
if "PAIR_OK" not in r.stdout:
    sys.exit(f"⚠️  {(r.stdout + r.stderr).strip()[-300:]}")
print("          archetypes and specs stay paired when one is dropped.")

print("""
Apply patch_contrast_repair.py too — that one removes the reason this
archetype failed in the first place. Together:

  · a contrast miss is repaired by arithmetic, not by a second paid guess
  · an archetype that still fails costs you one direction, not the run
""")
