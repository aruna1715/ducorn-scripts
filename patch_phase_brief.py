#!/usr/bin/env python3
"""
The phase run had no founder brief, because start_next never wrote one.

    cd ~/DC && python3 scripts/patch_phase_brief.py            show
    cd ~/DC && python3 scripts/patch_phase_brief.py --apply    do it

── WHAT HAPPENED ────────────────────────────────────────────────────────────

    🔬 SAGE: Starting research for 'ducorn-admin-rebuild-p1-config'
    🧠 SAGE model: claude-sonnet
    ❌ No founder brief found at .../ducorn-admin-rebuild-p1-config-PRD.md.
       Refusing to research from the product name alone.

── THE CAUSE ────────────────────────────────────────────────────────────────

/pipeline/start does TWO things before it launches the flow:

    1. INSERT the pipeline_runs row
    2. write docs/<slug>-PRD.md from the founder's brief

start_next did the first and not the second. Its own docstring explains at
length why the row must exist — and says nothing about the file, because I
did not notice there were two halves. node_research reads that file as its
first act and fails when it is empty, which is correct behaviour: researching
from a slug is how a dashboard rebuild came back as a Mixpanel competitor.

So a phase carried its brief in epic_phases.brief and in the skill-01 prompt,
and the run never reached skill 01.

── WHY MY PRE-FLIGHT DID NOT CATCH IT ───────────────────────────────────────

    --dry-run ran:  skill_runner.py --topic <slug> --skill 01 --dry-run

skill_runner is not where a run begins. langgraph_flow.node_research is. The
check exercised an entry point the run does not use, so it passed on code
that could not start. That is worse than having no check: it is a check that
reports on something else in the same words.

The dry run below no longer shells out to skill_runner. It prints the brief
start would write, and says plainly what it does and does not prove.

── THE FIX ──────────────────────────────────────────────────────────────────

start_next writes the brief where every run's brief lives, then launches.

No new marker constant. /pipeline/start writes a plain header and the brief
text with no "## Founder Brief" heading at all — node_research adds that
heading itself when it re-appends the brief after research. This writes the
file the same shape, so there is still exactly one definition of the heading
and it is in langgraph_flow.py.

On a re-run of a phase that already produced a PRD, the researched head is
kept and only the brief section is refreshed — located by
stack_context.BRIEF_MARKER, which is the module that already owns finding it.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
SP = DC / "scripts" / "start_phase.py"
FLOW = DC / "ducorn" / "flows" / "langgraph_flow.py"
TAG = "phasebrief"

# ── 1. the paths block gains DOCS ────────────────────────────────────────────
OLD_PATHS = '''VENV = DC / "ducorn" / ".venv" / "bin" / "python"
LOGS = DC / "logs"'''

NEW_PATHS = '''VENV = DC / "ducorn" / ".venv" / "bin" / "python"
LOGS = DC / "logs"
DOCS = DC / "ducorn-products" / "docs"'''

# ── 2. the writer ────────────────────────────────────────────────────────────
WRITER = '''

def brief_text(slug: str) -> str:
    """
    What this phase is asked to build, as prose.

    One source: product_epics.context_for reads the epic, the phase, the
    finished dependencies and the product directory. This adds no words of
    its own — a second description of a phase would drift from the first.
    """
    pe = _epics()
    return pe.context_for(slug).strip()


def write_phase_brief(slug: str) -> Path:
    """
    Put the phase brief where a run's brief lives: docs/<slug>-PRD.md.

    THIS IS THE HALF THAT WAS MISSING. /pipeline/start writes this file and
    then launches; start_next created the pipeline_runs row and launched
    without it, and node_research — which reads this file as its first act —
    failed the run before any skill ran.

    Shape matches /pipeline/start: a header and the brief, with no
    "## Founder Brief" heading. node_research adds that heading itself when
    it re-appends the brief after research, and it is defined there. Writing
    it here would be a second copy of it.

    A phase that has already produced a researched PRD keeps it; only the
    brief section is refreshed, because the manifest of what is in the
    product directory has changed since it was written.
    """
    import stack_context as sc

    text = brief_text(slug)
    if not text:
        raise NotStartable(
            f"no brief could be built for {slug!r} — product_epics.context_for "
            f"returned nothing, so there is no phase by that slug")

    DOCS.mkdir(parents=True, exist_ok=True)
    prd = DOCS / f"{slug}-PRD.md"

    if prd.exists():
        raw = prd.read_text(errors="replace")
        i = raw.find(sc.BRIEF_MARKER)
        if i >= 0:
            # Keep the research, refresh the brief. The file's OWN heading
            # line is reused verbatim rather than reconstructed.
            heading = raw[i:].splitlines()[0]
            prd.write_text(f"{raw[:i].rstrip()}\\n\\n{heading}\\n\\n{text}\\n",
                           encoding="utf-8")
            return prd

    prd.write_text(f"# {slug} — phase brief\\n\\n{text}\\n", encoding="utf-8")
    return prd

'''

# ── 3. start_next calls it before launching ──────────────────────────────────
OLD_LAUNCH = '''    LOGS.mkdir(parents=True, exist_ok=True)
    log = LOGS / f"flow_{slug}.log"'''

NEW_LAUNCH = '''    # The brief, BEFORE the launch. node_research reads docs/<slug>-PRD.md
    # as its first act and refuses an empty one; without this the run failed
    # in under two seconds, having created its row and its log.
    prd = write_phase_brief(slug)

    LOGS.mkdir(parents=True, exist_ok=True)
    log = LOGS / f"flow_{slug}.log"'''

OLD_RETURN = '''    return {"started": slug, "seq": plan["next"]["seq"],
            "title": plan["next"]["title"], "pid": proc.pid,
            "log": str(log), "budget": budget["message"]}'''

NEW_RETURN = '''    return {"started": slug, "seq": plan["next"]["seq"],
            "title": plan["next"]["title"], "pid": proc.pid,
            "log": str(log), "brief": str(prd), "budget": budget["message"]}'''

# ── 4. a dry run that does not test the wrong thing ──────────────────────────
OLD_DRY = '''    if a.dry_run:
        print("\\n── the prompt skill 01 would receive (nothing is spent) ──\\n")
        r = subprocess.run(
            [str(VENV) if VENV.exists() else sys.executable,
             str(DC / "ducorn" / "skill_runner.py"),
             "--topic", slug, "--skill", "01", "--dry-run"],
            cwd=str(DC / "ducorn"))
        return r.returncode'''

NEW_DRY = '''    if a.dry_run:
        # This used to run skill_runner --skill 01. skill_runner is not where
        # a run begins — langgraph_flow.node_research is — so the check
        # exercised an entry point the run does not use and passed on code
        # that could not start. It now shows the one thing node_research
        # reads, and claims nothing beyond that.
        try:
            text = brief_text(slug)
        except Exception as e:
            die(f"the brief could not be built: {e}")
        target = DOCS / f"{slug}-PRD.md"
        print(f"\\n── the brief start would write ({len(text):,} chars) ──")
        print(f"   to   {target}")
        print(f"   read by node_research as the founder brief, first act of "
              f"the run\\n")
        head = text.splitlines()
        for line in head[:40]:
            print("   " + line)
        if len(head) > 40:
            print(f"   … and {len(head) - 40} more lines")
        print(f"""
Nothing was written and nothing was spent.

This proves the brief exists and is not empty — the thing the failed run
tripped on. It does not prove the run succeeds; only starting it does.
""")
        return 0'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in (SP, FLOW):
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

src = SP.read_text(encoding="utf-8")
print("patch_phase_brief\n")

if "def write_phase_brief" in src:
    sys.exit("NOTHING DONE — start_phase already writes the brief.")

# The path this writes must be the path node_research reads. That equality is
# the whole bug, so it is checked against the flow's source rather than
# assumed — if node_research ever moves the file, this patch refuses.
flow_src = FLOW.read_text(encoding="utf-8")
expect = 'prd_path = PRODUCTS_DIR / "docs" / f"{topic}-PRD.md"'
if expect not in flow_src:
    sys.exit(f"""NOTHING DONE — node_research does not read the path this
writes. Expected to find in langgraph_flow.py:

    {expect}

It is not there. Tell me where the founder brief is read from now and I will
write to that instead of guessing.""")
print("  ok  node_research reads docs/<topic>-PRD.md — the path this writes")

anchors = [("the paths block", OLD_PATHS),
           ("the launch block in start_next", OLD_LAUNCH),
           ("the return of start_next", OLD_RETURN),
           ("the --dry-run block", OLD_DRY)]
bad = False
for label, a in anchors:
    n = src.count(a)
    print(f"  {'ok ' if n == 1 else '!! '}{label}  ({n} match)")
    bad |= n != 1
if bad:
    sys.exit("\nNOTHING DONE — an anchor did not match exactly once.")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(SP, SP.with_suffix(f".backup-{TAG}-{stamp}.py"))

out = src.replace(OLD_PATHS, NEW_PATHS, 1)
out = out.replace(OLD_LAUNCH, NEW_LAUNCH, 1)
out = out.replace(OLD_RETURN, NEW_RETURN, 1)
out = out.replace(OLD_DRY, NEW_DRY, 1)
# The writer goes in above start_next, after plan_next.
out = out.replace("\n\ndef start_next(", WRITER + "\ndef start_next(", 1)
SP.write_text(out, encoding="utf-8")
print(f"\nwrote {SP.name}, backup tagged {TAG}-{stamp}")

r = subprocess.run([sys.executable, "-m", "py_compile", str(SP)],
                   capture_output=True, text=True)
if r.returncode != 0:
    sys.exit(f"⚠️  it does not parse — restore the backup:\n{r.stderr[-400:]}")

after = SP.read_text(encoding="utf-8")

# Verify by ORDER, not by presence: writing the brief after the launch would
# be as broken as not writing it, and both spellings contain both lines.
body = after[after.find("def start_next("):after.find("def main(")]
i_brief = body.find("write_phase_brief(slug)")
i_launch = body.find("subprocess.Popen(")
if i_brief < 0 or i_launch < 0 or i_brief > i_launch:
    sys.exit("⚠️  the brief is not written before the launch — restore the "
             "backup.")
if "skill_runner.py" in body or "--skill" in after[after.find("if a.dry_run"):]:
    sys.exit("⚠️  the dry run still shells to skill_runner — restore the "
             "backup.")
print("verified: start_phase.py parses, the brief is written before the "
      "flow is launched,\n          and the dry run no longer tests "
      "skill_runner.")

print("""
Look, for free:

  python3 scripts/start_phase.py ducorn-admin-rebuild --dry-run

It should print the phase-1 brief and the docs/ path it goes to.
Then apply patch_phase_ctx_once.py before starting the phase.
""")
