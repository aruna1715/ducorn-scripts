#!/usr/bin/env python3
"""
Fix a contrast ratio with arithmetic, not with another paid model call.

    cd ~/DC && python3 scripts/patch_contrast_repair.py            show
    cd ~/DC && python3 scripts/patch_contrast_repair.py --apply    do it

Needs scripts/patchlib.py.

── WHAT FAILED ──────────────────────────────────────────────────────────────

    ❌ Design failed: could not get a usable direction for Data-Dense
       Professional: dark_palette: ink_muted on bg is 2.8:1 (need 3.0)

The model proposed a palette. One colour missed a contrast threshold by 0.2.
The spec was discarded and the model asked again — up to three times, each a
paid call in production — to guess its way to a number that can be computed.

Contrast is arithmetic. _luminance and contrast_ratio are already in this
file. Moving ink_muted a few percent darker until it clears 3.0:1 is a loop
over integers, and it costs nothing.

── WHAT THIS CHANGES ────────────────────────────────────────────────────────

repair_contrast(spec) nudges the offending colour toward the palette's ink
until the ratio passes, then check_contrast re-runs. Only a palette that
CANNOT be repaired — because even full ink does not clear the threshold, so
the background itself is the problem — is sent back to the model.

The repair is bounded and reported. It moves ink_muted, never bg or accent:
the background is the design decision the archetype exists to make, and the
accent is what distinguishes one variant from another. Muted text is
supporting colour, and the WCAG floor for it is not negotiable anyway.

── WHY IT MATTERS BEYOND THIS RUN ───────────────────────────────────────────

It is the same waste as paying a model to restate a failing pytest: a free,
deterministic answer already existed and a paid guess was bought instead.
This one was found on a test run costing nothing, which is the argument for
test runs.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
SPEC = DC / "ducorn" / "tools" / "design_spec.py"
GEN = DC / "ducorn" / "tools" / "generate_design.py"
LIB = DC / "scripts" / "patchlib.py"
TAG = "contrastfix"

SPEC_OLD = '''def check_contrast(spec, min_body=4.5, min_muted=3.0):'''

SPEC_NEW = '''def _nudge(hexcolor, toward, amount):
    """Move a colour a fraction of the way toward another, in RGB."""
    a, b = _rgb(hexcolor), _rgb(toward)
    mixed = tuple(round(c1 + (c2 - c1) * amount) for c1, c2 in zip(a, b))
    return "#%02x%02x%02x" % mixed


def repair_contrast(spec, min_body=4.5, min_muted=3.0):
    """
    Make a palette pass, by arithmetic, and say what was changed.

    A design was rejected for "ink_muted on bg is 2.8:1 (need 3.0)" and the
    model was asked to try again — three times, paid, guessing at a number
    this module can compute. contrast_ratio is four lines above this one.

    Only ink_muted moves, and only toward ink. bg is the archetype's decision
    and accent is what tells two variants apart; muted text is supporting
    colour whose floor is a standard, not a preference.

    Returns a list of human-readable repairs. A palette that cannot be
    repaired is left alone for check_contrast to reject — if even full ink
    fails against this bg, the background is the problem and no nudge fixes
    that.
    """
    repairs = []
    for pal_name in ("palette", "dark_palette"):
        pal = spec.get(pal_name)
        if not isinstance(pal, dict):
            continue
        try:
            if contrast_ratio(pal["ink_muted"], pal["bg"]) >= min_muted:
                continue
            if contrast_ratio(pal["ink"], pal["bg"]) < min_muted:
                continue          # unrepairable: the bg is the problem
            before = pal["ink_muted"]
            # Twenty steps toward ink. Bounded, and the first one that clears
            # the threshold wins, so the colour moves as little as possible.
            for i in range(1, 21):
                cand = _nudge(before, pal["ink"], i / 20.0)
                if contrast_ratio(cand, pal["bg"]) >= min_muted:
                    pal["ink_muted"] = cand
                    repairs.append(
                        f"{pal_name}.ink_muted {before} → {cand} "
                        f"({contrast_ratio(before, pal['bg']):.1f}:1 → "
                        f"{contrast_ratio(cand, pal['bg']):.1f}:1)")
                    break
        except (KeyError, ValueError):
            continue
    return repairs


def check_contrast(spec, min_body=4.5, min_muted=3.0):'''

GEN_OLD = '''        problems = validate_spec(spec) + check_contrast(spec)'''

GEN_NEW = '''        # Repair what arithmetic can, before asking the model again.
        #
        # A direction was thrown away for being 0.2 short of a contrast
        # threshold, and the model was asked to guess again — three times, at
        # a price, for a number this code can compute. Only a palette that
        # cannot be repaired reaches the model a second time.
        _repairs = repair_contrast(spec)
        for _r in _repairs:
            print(f"🎨 contrast repaired: {_r}", flush=True)
        problems = validate_spec(spec) + check_contrast(spec)'''

GEN_IMPORT_OLD = '''        assign_archetypes, validate_spec, check_contrast, verify_variants,'''
GEN_IMPORT_NEW = '''        assign_archetypes, validate_spec, check_contrast, repair_contrast,
        verify_variants,'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in (SPEC, GEN, LIB):
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

sys.path.insert(0, str(DC / "scripts"))
from patchlib import calls_in, py_ok, PatchCheckFailed   # noqa: E402

spec_src = SPEC.read_text(encoding="utf-8")
gen_src = GEN.read_text(encoding="utf-8")
print("patch_contrast_repair\n")

if "def repair_contrast" in spec_src:
    sys.exit("NOTHING DONE — repair_contrast is already there.")

n_imports = gen_src.count(GEN_IMPORT_OLD)
bad = False
for label, hay, a, want in [("check_contrast", spec_src, SPEC_OLD, 1),
                            ("the validate line", gen_src, GEN_OLD, 1),
                            ("the imports", gen_src, GEN_IMPORT_OLD, 2)]:
    n = hay.count(a)
    print(f"  {'ok ' if n == want else '!! '}{label}  ({n} match, want {want})")
    bad |= n != want
if bad:
    sys.exit("\nNOTHING DONE — an anchor did not match as expected.")

for needed in ("def contrast_ratio", "def _rgb", "def _luminance"):
    if needed not in spec_src:
        sys.exit(f"NOTHING DONE — {needed} is not in design_spec.py.")
print("  ok  contrast_ratio, _rgb and _luminance are all in design_spec")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(SPEC, SPEC.with_suffix(f".backup-{TAG}-{stamp}.py"))
shutil.copy2(GEN, GEN.with_suffix(f".backup-{TAG}-{stamp}.py"))
SPEC.write_text(spec_src.replace(SPEC_OLD, SPEC_NEW, 1), encoding="utf-8")
# Both import sites — the module has a try/except pair of them.
GEN.write_text(gen_src.replace(GEN_IMPORT_OLD, GEN_IMPORT_NEW)
               .replace(GEN_OLD, GEN_NEW, 1), encoding="utf-8")
print(f"\nwrote design_spec.py and generate_design.py, backups tagged "
      f"{TAG}-{stamp}")

for f in (SPEC, GEN):
    try:
        py_ok(f.read_text(encoding="utf-8"), f.name)
    except PatchCheckFailed as e:
        sys.exit(f"⚠️  {e} — restore the backups.")

after = GEN.read_text(encoding="utf-8")
if len(calls_in(after, "propose_direction", "repair_contrast")) != 1:
    sys.exit("⚠️  propose_direction does not repair once before validating — "
             "restore the backups.")
# The repair must not have REPLACED the check. A palette that cannot be
# repaired still has to be rejected.
if len(calls_in(after, "propose_direction", "check_contrast")) != 1:
    sys.exit("⚠️  check_contrast is gone from propose_direction — repair is "
             "not a substitute for the check. Restore the backups.")
print("verified: both parse; propose_direction repairs once and STILL "
      "checks.")

# The arithmetic, on the exact failure that stopped the run.
probe = r'''
import sys
sys.path.insert(0, "/Users/ducorn/DC/ducorn/tools")
from design_spec import repair_contrast, check_contrast, contrast_ratio
# A dark palette whose muted ink lands just under the 3.0 floor.
# #585e66 on #12161a is 2.78:1 — the failure the plumbing run actually hit
# ("ink_muted on bg is 2.8:1"). Checked before shipping: an earlier fixture
# here already passed at 3.11:1, so this probe would have reported the patch
# broken while proving nothing.
spec = {"dark_palette": {"bg": "#12161a", "surface": "#1b2026",
                         "ink": "#e6edf3", "ink_muted": "#585e66",
                         "accent": "#4fd1c5"},
        "palette": {"bg": "#ffffff", "surface": "#f4f6f8", "ink": "#111418",
                    "ink_muted": "#6b7480", "accent": "#0f766e"}}
before = contrast_ratio(spec["dark_palette"]["ink_muted"],
                        spec["dark_palette"]["bg"])
reps = repair_contrast(spec)
after = contrast_ratio(spec["dark_palette"]["ink_muted"],
                       spec["dark_palette"]["bg"])
bad = []
if before >= 3.0:
    bad.append("the fixture does not reproduce a failing palette")
if after < 3.0:
    bad.append(f"the repair left it at {after:.2f}:1")
if not reps:
    bad.append("the repair was silent")
if check_contrast(spec):
    bad.append(f"check_contrast still objects: {check_contrast(spec)}")
# Unrepairable: ink itself fails, so nothing should move.
hopeless = {"palette": {"bg": "#808080", "ink": "#8a8a8a",
                        "ink_muted": "#858585", "accent": "#999999"}}
keep = hopeless["palette"]["ink_muted"]
repair_contrast(hopeless)
if hopeless["palette"]["ink_muted"] != keep:
    bad.append("an unrepairable palette was altered anyway")
print("REPAIR_OK " + f"{before:.2f} -> {after:.2f}" if not bad
      else "REPAIR_BAD " + "; ".join(bad))
'''
r = subprocess.run([str(DC / "ducorn" / ".venv" / "bin" / "python"), "-c", probe],
                   capture_output=True, text=True)
out = (r.stdout + r.stderr).strip()
if "REPAIR_OK" not in out:
    sys.exit(f"⚠️  {out[-400:]}")
print(f"          {out.splitlines()[-1]}")

print("""
The design step no longer buys a guess at a number it can compute.

Re-run phase 1 of zz-plumbing-check from the dashboard — TEST, still free.
Watch for:

  🎨 contrast repaired: dark_palette.ink_muted #... → #... (2.8:1 → 3.0:1)
""")
