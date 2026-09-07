#!/usr/bin/env python3
"""
node_qa and node_qa_fix must ask the pathway, like every other node already does.

    cd ~/DC && python3 scripts/patch_qa_pathway.py            show
    cd ~/DC && python3 scripts/patch_qa_pathway.py --apply    do it

── THE DEFECT ───────────────────────────────────────────────────────────────

node_build asks product_pathways which skills to run. A document gets
("01", "04", "07") — no code review, no QA + Run Test. That works.

node_qa and node_qa_fix are separate graph nodes. The pathway never reaches
them, and they run:

    "--skill", "06"        node_qa
    "--skill", "05"        node_qa_fix

unconditionally, for every kind of product. So the last document run — the
one whose whole point was that documents skip the code path — went to gate 3
via IRIS running QA + Run Test on a Markdown file, four attempts, at roughly
$0.40. Skill 07 had already reviewed it, in the build, and passed.

This is the same shape as everything else here: a control that exists, is
correct in isolation, and does not reach the thing it governs.

── THE FIX ──────────────────────────────────────────────────────────────────

Two fields on Pathway — qa_skill and fix_skill — sitting beside skills, in
the file that already knows what kind of product this is. Empty means the
pathway has no such step, and the node returns without spending anything.

  document                    qa_skill ""     fix_skill ""     (07 reviewed it)
  webpage / api / cli / software   "06"           "05"

A sixth pathway added next month gets these the same way it gets everything
else: by being a Pathway.

── AND ONE DUPLICATE FACT ───────────────────────────────────────────────────

node_build carries an inline dict mapping "01".."07" to display names. Both
QA nodes needed the same mapping, and adding a second copy of it to make
them dynamic would be the exact defect this codebase keeps producing. It
moves to product_pathways.SKILL_NAMES, and node_build reads it from there.

── WHAT THIS DOES NOT CHANGE ────────────────────────────────────────────────

Nothing about software, webpage, api or cli products: they still run 06 and
05, at the same points, with the same arguments. Only the pathways that
declare no QA step behave differently, and today that is documents alone.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
FLOW = DC / "ducorn" / "flows" / "langgraph_flow.py"
PATHWAYS = DC / "scripts" / "product_pathways.py"
TAG = "qapathway"

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

edits = []          # (path, description, old, new)


def edit(path: Path, what: str, old: str, new: str) -> None:
    edits.append((path, what, old, new))


# ─────────────────────────────────────────────────────────────────────────────
# 1. product_pathways.py — the two fields, and the name table
# ─────────────────────────────────────────────────────────────────────────────
edit(PATHWAYS, "Pathway gains qa_skill and fix_skill",
     """    skills: tuple                  # e.g. ("01", "04", "07")
    design_skills: tuple = ()      # added when the founder asked for a UI
""",
     """    skills: tuple                  # e.g. ("01", "04", "07")
    design_skills: tuple = ()      # added when the founder asked for a UI

    # ── the post-build loop ──────────────────────────────────────────────
    # node_qa and node_qa_fix are separate graph nodes: the skills above are
    # chosen in node_build and never reach them. They hardcoded "06" and
    # "05", so a document — already reviewed by 07 during the build — was put
    # through QA + Run Test anyway, four attempts, about $0.40, every run.
    # "" means this kind of product has no such step.
    qa_skill: str = "06"           # what node_qa runs
    fix_skill: str = "05"          # what node_qa_fix runs after a failure
""")

edit(PATHWAYS, "document declares no QA and no fix step",
     """        publish_to="docs",
        max_review_iterations=1,""",
     """        publish_to="docs",
        # 07 reviewed the prose during the build and can fail the run. There
        # is nothing for QA + Run Test to execute and nothing for a code
        # review to read.
        qa_skill="",
        fix_skill="",
        max_review_iterations=1,""")

edit(PATHWAYS, "SKILL_NAMES moves here, one definition",
     """PATHWAYS = {
    # ── prose. the reason this module exists. ────────────────────────────""",
     """# What each skill is called, for the dashboard and the logs. Lived inline in
# node_build; both QA nodes need it too, and a second copy is how two names
# for one skill start disagreeing.
SKILL_NAMES = {
    "01": "Skill 01 — PRD Analysis",
    "02": "Skill 02 — Design Consultation",
    "03": "Skill 03 — Design Review",
    "04": "Skill 04 — Build",
    "05": "Skill 05 — Code Review",
    "06": "Skill 06 — QA + Run Test",
    "07": "Skill 07 — Content Review",
}


def skill_name(num: str) -> str:
    return SKILL_NAMES.get(num, f"Skill {num}")


PATHWAYS = {
    # ── prose. the reason this module exists. ────────────────────────────""")


# ─────────────────────────────────────────────────────────────────────────────
# 2. langgraph_flow.py — node_build reads the shared table
# ─────────────────────────────────────────────────────────────────────────────
edit(FLOW, "node_build uses the shared skill-name table",
     """            for skill_num in skills:
                skill_name = {
                    "01": "Skill 01 — PRD Analysis",
                    "02": "Skill 02 — Design Consultation",
                    "03": "Skill 03 — Design Review",
                    "04": "Skill 04 — Build",
                    "05": "Skill 05 — Code Review",
                    "07": "Skill 07 — Content Review",
                    "06": "Skill 06 — QA + Run Test",
                }.get(skill_num, f"Skill {skill_num}")
""",
     """            for skill_num in skills:
                skill_name = _pw.skill_name(skill_num)
""")


# ─────────────────────────────────────────────────────────────────────────────
# 3. node_qa — ask the pathway, and skip when there is nothing to run
# ─────────────────────────────────────────────────────────────────────────────
edit(FLOW, "node_qa asks the pathway which skill verifies this product",
     '''def node_qa(state: DuCornState) -> DuCornState:
    """IRIS reviews the built product via isolated subprocess."""
    topic = state["topic"]
    attempts = state.get("qa_attempts", 0) + 1
    coder = state.get("coder", "crewai")
    engine = state.get("build_engine", "fast")
    print(f"\\n🔍 IRIS: QA review for '{topic}' (attempt {attempts})")
    _update_db_status(topic, "running", "Skill 06 — QA + Run Test")
''',
     '''def node_qa(state: DuCornState) -> DuCornState:
    """IRIS reviews the built product via isolated subprocess."""
    topic = state["topic"]
    attempts = state.get("qa_attempts", 0) + 1
    coder = state.get("coder", "crewai")
    engine = state.get("build_engine", "fast")

    # Which skill verifies this product is a property of the KIND of product.
    # This node used to run 06 whatever it was looking at, which is how a
    # Markdown document was put through QA + Run Test.
    import product_pathways as _pwq
    _pathway = _pwq.for_topic(topic, override=state.get("product_type"),
                              quiet=True)
    if not _pathway.qa_skill:
        reviewed = [s for s in _pathway.skills if s in ("05", "06", "07")]
        print(f"\\n⏭️  no QA step for a {_pathway.prompt_noun} — "
              f"{_pwq.skill_name(reviewed[-1]) if reviewed else 'the build'} "
              f"already reviewed it and can fail the run")
        _update_db_status(topic, "complete",
                          f"no QA step for a {_pathway.prompt_noun}")
        return {**state,
                "qa_verdict": "PASS",
                "qa_attempts": state.get("qa_attempts", 0),
                "phase": "gate_3",
                "status": "running"}

    _qa_name = _pwq.skill_name(_pathway.qa_skill)
    print(f"\\n🔍 IRIS: QA review for '{topic}' (attempt {attempts})")
    _update_db_status(topic, "running", _qa_name)
''')

edit(FLOW, "node_qa runs the pathway's skill, not a literal 06",
     '''        result = subprocess.run(
            [PYTHON, SKILL_RUNNER,
             "--skill", "06",
             "--topic", topic,
             "--coder", coder],
            capture_output=True,
            text=True,
            timeout=900,
            env=env,
            cwd="/Users/ducorn/DC/ducorn"
        )

        output = result.stdout
        if output:
            print(output[-1000:])

        passed = result.returncode == 0

        if passed:
            _update_db_status(topic, "complete", "Skill 06 — QA + Run Test")''',
     '''        result = subprocess.run(
            [PYTHON, SKILL_RUNNER,
             "--skill", _pathway.qa_skill,
             "--topic", topic,
             "--coder", coder],
            capture_output=True,
            text=True,
            timeout=900,
            env=env,
            cwd="/Users/ducorn/DC/ducorn"
        )

        output = result.stdout
        if output:
            print(output[-1000:])

        passed = result.returncode == 0

        if passed:
            _update_db_status(topic, "complete", _qa_name)''')

edit(FLOW, "node_qa failure status names the skill that failed",
     '''        else:
            _update_db_status(topic, "failed", "Skill 06 — QA + Run Test")
            return {**state,
                    "qa_verdict": "FAIL",''',
     '''        else:
            _update_db_status(topic, "failed", _qa_name)
            return {**state,
                    "qa_verdict": "FAIL",''')


# ─────────────────────────────────────────────────────────────────────────────
# 4. node_qa_fix — same question, same answer
# ─────────────────────────────────────────────────────────────────────────────
edit(FLOW, "node_qa_fix asks the pathway which skill fixes this product",
     '''def node_qa_fix(state: DuCornState) -> DuCornState:
    """REX auto-fixes QA issues via isolated subprocess."""
    topic = state["topic"]
    attempts = state.get("qa_attempts", 0)
    coder = state.get("coder", "crewai")
    engine = state.get("build_engine", "fast")
    print(f"\\n🔧 REX: Auto-fixing QA issues for '{topic}' (attempt {attempts})")
    _update_db_status(topic, "running", "Skill 05 — Code Review")
''',
     '''def node_qa_fix(state: DuCornState) -> DuCornState:
    """REX auto-fixes QA issues via isolated subprocess."""
    topic = state["topic"]
    attempts = state.get("qa_attempts", 0)
    coder = state.get("coder", "crewai")
    engine = state.get("build_engine", "fast")

    import product_pathways as _pwf
    _pathway = _pwf.for_topic(topic, override=state.get("product_type"),
                              quiet=True)
    if not _pathway.fix_skill:
        # Unreachable while node_qa skips too — kept because "the other node
        # makes this impossible" is exactly the reasoning that produced the
        # bug this patch fixes.
        print(f"\\n⏭️  no fix step for a {_pathway.prompt_noun}")
        return {**state, "phase": "gate_3", "status": "running"}

    _fix_name = _pwf.skill_name(_pathway.fix_skill)
    print(f"\\n🔧 REX: Auto-fixing QA issues for '{topic}' (attempt {attempts})")
    _update_db_status(topic, "running", _fix_name)
''')

edit(FLOW, "node_qa_fix invalidates and runs the pathway's skills",
     '''        subprocess.run(
            [PYTHON, SKILL_RUNNER, "--invalidate", "05,06", "--topic", topic],
            capture_output=True, text=True, timeout=30, env=env,
            cwd="/Users/ducorn/DC/ducorn"
        )

        result = subprocess.run(
            [PYTHON, SKILL_RUNNER,
             "--skill", "05",
             "--topic", topic,
             "--coder", coder],''',
     '''        subprocess.run(
            [PYTHON, SKILL_RUNNER, "--invalidate",
             ",".join(s for s in (_pathway.fix_skill, _pathway.qa_skill) if s),
             "--topic", topic],
            capture_output=True, text=True, timeout=30, env=env,
            cwd="/Users/ducorn/DC/ducorn"
        )

        result = subprocess.run(
            [PYTHON, SKILL_RUNNER,
             "--skill", _pathway.fix_skill,
             "--topic", topic,
             "--coder", coder],''')


# ─────────────────────────────────────────────────────────────────────────────
# apply
# ─────────────────────────────────────────────────────────────────────────────
def die(msg: str) -> None:
    sys.exit(f"NOTHING DONE — {msg}")


sources = {}
for path in {p for p, *_ in edits}:
    if not path.is_file():
        die(f"{path} is not there")
    sources[path] = path.read_text(encoding="utf-8")

print("patch_qa_pathway\n")
for path, what, old, new in edits:
    n = sources[path].count(old)
    mark = "ok " if n == 1 else "!! "
    print(f"  {mark}{path.name:22} {what}")
    if n == 0:
        print("       the anchor is not in the file — it has already changed")
    elif n > 1:
        print(f"       {n} matches; the anchor is not unique")

bad = [(p, w) for (p, w, o, _) in edits if sources[p].count(o) != 1]
if bad:
    die(f"{len(bad)} anchor(s) did not match exactly once. Nothing written.")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
for path in sources:
    shutil.copy2(path, path.with_suffix(f".backup-{TAG}-{stamp}.py"))

out = dict(sources)
for path, _what, old, new in edits:
    out[path] = out[path].replace(old, new, 1)

for path, text in out.items():
    path.write_text(text, encoding="utf-8")
print(f"\nwrote {len(out)} file(s), backups tagged {TAG}-{stamp}")

# ── verify: parse, import, and ask the pathways themselves ──────────────────
import subprocess

fails = []
for path in out:
    r = subprocess.run([sys.executable, "-m", "py_compile", str(path)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        fails.append(f"{path.name} does not parse:\n{r.stderr[-400:]}")

probe = f'''
import sys
sys.path.insert(0, "{DC}/scripts")
import product_pathways as pw
bad = []
for name, p in pw.PATHWAYS.items():
    if name == "document":
        if p.qa_skill or p.fix_skill:
            bad.append(name + " should have no QA/fix step")
    elif (p.qa_skill, p.fix_skill) != ("06", "05"):
        bad.append(name + " changed: " + repr((p.qa_skill, p.fix_skill)))
if pw.skill_name("07") != "Skill 07 — Content Review":
    bad.append("skill_name lost 07")
print("PATHWAYS_OK" if not bad else "PATHWAYS_BAD " + "; ".join(bad))
'''
r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
if "PATHWAYS_OK" not in r.stdout:
    fails.append((r.stdout + r.stderr).strip()[-500:])

if "--skill\", \"06\"" in out[FLOW] or '"--skill", "05",' in out[FLOW]:
    fails.append("a hardcoded skill number is still in langgraph_flow.py")

if fails:
    print("\n⚠️  VERIFICATION FAILED — the backups are beside each file:\n")
    for f in fails:
        print("   " + f + "\n")
    raise SystemExit(1)

print("""
verified: both files parse, document declares no QA or fix step, the other
four are unchanged at 06/05, and no skill number is hardcoded in the flow.

Free way to see it:
  cd ~/DC/ducorn && .venv/bin/python skill_runner.py \\
      --topic ducorn-technology-stack-documentation --skill 04 --dry-run
""")
