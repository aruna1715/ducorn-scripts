#!/usr/bin/env python3
"""
One definition of what kind of product this is, consulted everywhere.

    python3 scripts/patch_pathways.py

── WHAT THIS ENDS ───────────────────────────────────────────────────────────

"Does this product have an interface?" was answered in four places, four ways.
For the technology-stack document three of them said no and the fourth said
yes — and the fourth was the only one that could fail a run:

    ui_test_coverage()   are there any .html files in the directory?

REX wrote .html renderings of the documents, exactly as asked. So a finished
document was failed for shipping no Playwright tests, three times, and a
Chromium binary was installed into its venv to run a test suite that does not
exist. That is most of the $11.

After this patch every one of those questions is a field on a Pathway, and
there are five pathways:

    document   01 → 04 → 07     no tests, no UI gate, no code review, no deploy
    webpage    01 →(02,03)→ 04 → 05 → 06
    api        01 → 04 → 05 → 06        tests yes, UI gate no
    cli        01 → 04 → 05 → 06        tests yes, no deploy
    software   01 →(02,03)→ 04 → 05 → 06

Design skills are added when the founder asked for a UI *and* the pathway can
have one. Complexity still matters; it no longer decides on its own, which is
what sent a document through code review.

── WHAT IT DOES NOT DO ──────────────────────────────────────────────────────

It does not touch the six launch sites, the budget endpoint, or the jail's
prefix matching. Those are separate defects with separate patches — bundling
them would make this one impossible to revert cleanly.

── PREREQUISITES ────────────────────────────────────────────────────────────

    scripts/product_pathways.py            the definition
    gstack/skills/07-content-review.md     the document reviewer
    scripts/migrations/008_product_type.sql   applied

This refuses to write anything if any of them is missing.
"""
import ast
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Overridable so this can be rehearsed against copies before it touches the
# real tree. The anchors below still contain the literal /Users/ducorn/DC
# paths that appear INSIDE the source files, which is correct — a verbatim
# copy still has them.
DC = Path(os.environ.get("DUCORN_ROOT", "/Users/ducorn/DC"))
SKILL = DC / "ducorn" / "skill_runner.py"
FLOW = DC / "ducorn" / "flows" / "langgraph_flow.py"
PATHWAYS = DC / "scripts" / "product_pathways.py"
SKILL07 = DC / "gstack" / "skills" / "07-content-review.md"

# ── prerequisites, before anything is touched ────────────────────────────────
missing = [str(p) for p in (PATHWAYS, SKILL07) if not p.is_file()]
if missing:
    sys.exit("NOTHING WRITTEN — copy these into place first:\n  "
             + "\n  ".join(missing))

sys.path.insert(0, str(DC / "scripts"))
try:
    import product_pathways as _pw
except Exception as e:
    sys.exit(f"NOTHING WRITTEN — product_pathways.py will not import: {e}")
for _t in ("document", "webpage", "api", "cli", "software"):
    if _t not in _pw.PATHWAYS:
        sys.exit(f"NOTHING WRITTEN — product_pathways.py has no {_t!r} pathway.")

sk = SKILL.read_text(encoding="utf-8")
fl = FLOW.read_text(encoding="utf-8")

if "product_pathways" in sk and "product_pathways" in fl:
    print("Already patched — one definition, consulted everywhere.")
    sys.exit(0)

applied = []


def swap(label, text, old, new):
    n = text.count(old)
    if n != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {n}, expected 1. NOTHING WRITTEN.")
    applied.append(label)
    return text.replace(old, new, 1)


# ═════════════════════════════════════════════════════════════════════════════
# skill_runner.py
# ═════════════════════════════════════════════════════════════════════════════

# ── 1. skill 07 exists ───────────────────────────────────────────────────────
sk = swap("07 in SKILL_NAMES", sk,
          '''    "06": "Skill 06 — QA + Run Test",
}''',
          '''    "06": "Skill 06 — QA + Run Test",
    "07": "Skill 07 — Content Review",
}''')

sk = swap("07 in SKILL_FILES", sk,
          '''    "06": "06-qa-run-test.md",
}''',
          '''    "06": "06-qa-run-test.md",
    "07": "07-content-review.md",
}''')

sk = swap("07 in SKILL_AGENTS", sk,
          '''    "06": "IRIS",
}''',
          '''    "06": "IRIS",
    "07": "IRIS",
}''')

sk = swap("07 accepted on the CLI", sk,
          "choices=['01','02','03','04','05','06']",
          "choices=['01','02','03','04','05','06','07']")

# ── 2. the pathway is importable from skill_runner ───────────────────────────
sk = swap("import the pathway", sk,
          '''PRODUCTS_DIR = Path("/Users/ducorn/DC/ducorn-products")
SKILLS_DIR   = Path("/Users/ducorn/DC/gstack/skills")''',
          '''# The one definition of what this kind of product needs. Everything below
# that used to work it out for itself — the reviewers' guidelines, the test
# runner, the UI coverage gate, the "did the build produce anything" check —
# asks here instead.
import product_pathways as pathways

PRODUCTS_DIR = Path("/Users/ducorn/DC/ducorn-products")
SKILLS_DIR   = Path("/Users/ducorn/DC/gstack/skills")''')

# ── 3. the reviewers are told what this product IS ───────────────────────────
sk = swap("reviewers ask the pathway", sk,
          '''    if skill_num not in UI_REVIEW_SKILLS:
        return text

    # The same question skill 04 asks. Without it, a code reviewer for a
    # DOCUMENT was handed a web interface checklist and failed the build for
    # having no Playwright tests — for a product with no interface. Skill 04
    # asked; 03 and 05 did not; that asymmetry was the whole defect.
    if not _has_ui(topic):
        if not quiet:
            print(f"📄 skill {skill_num}: this product has no interface — "
                  f"reviewing it as content, not as a UI", flush=True)
        # Said, not merely left unsaid. A model given no instruction about
        # tests will invent a standard and hold the build to it.
        return text + """

======================================================================
THIS PRODUCT HAS NO USER INTERFACE
======================================================================
There is no approved design and no page to drive. Do NOT require browser
tests, Playwright, a test suite, or interface conventions — none of them
apply here and the pipeline does not ask for them.

Review what this product actually is: for a document, whether it is
accurate, complete against its brief, well organised and honest about what
it does not know. "No tests" is not a defect in something that ships no
code.
======================================================================
"""
''',
          '''    # What this product actually is, said out loud to every reviewer. The
    # pathway carries the wording, so a new type is added in one file rather
    # than by appending another paragraph here.
    pw = pathways.for_topic(topic, quiet=True)
    if pw.prompt_rules:
        text = text + pw.prompt_rules

    if skill_num not in UI_REVIEW_SKILLS:
        return text

    # Interface guidelines go only to products that HAVE an interface. This
    # used to ask _has_ui(topic) — "does APPROVED_DESIGN.html exist" — which
    # is a fourth opinion about the same fact. Now the pathway decides, and
    # the founder's has_ui only matters where an interface is possible.
    if not (pw.ships_interface or _has_ui(topic)):
        if not quiet:
            print(f"📄 skill {skill_num}: this is a {pw.prompt_noun} — "
                  f"reviewing it as content, not as a UI", flush=True)
        return text
''')

# ── 4. the UI gate may only fail products that have a UI ─────────────────────
sk = swap("ui gate asks the pathway", sk,
          '''    import re
    d = PRODUCTS_DIR / "products" / topic
    html = [p for p in d.rglob("*")
            if p.is_file() and p.suffix.lower() in UI_EXT and ".venv" not in p.parts]
    if not html:
        return "pass", "no UI in this product"''',
          '''    import re

    # THE BUG THIS FIXES: this function decided "is there a UI here" by
    # counting .html files, and it is the only opinion that can fail a run.
    # A document rendered to .html — which is what a document SHOULD be
    # rendered to — was therefore judged a web product and failed for having
    # no Playwright tests. Three iterations of it.
    pw = pathways.for_topic(topic, quiet=True)
    if not pw.checks_ui:
        return "pass", f"not applicable — this is a {pw.prompt_noun}"

    d = PRODUCTS_DIR / "products" / topic
    html = [p for p in d.rglob("*")
            if p.is_file() and p.suffix.lower() in UI_EXT and ".venv" not in p.parts]
    if not html:
        return "pass", "no UI in this product"''')

# ── 5. no venv, no pip, no Chromium for a document ───────────────────────────
sk = swap("test suite asks the pathway", sk,
          '''    d = PRODUCTS_DIR / "products" / topic
    if not d.is_dir():
        return "fail", f"No product directory at {d}"''',
          '''    d = PRODUCTS_DIR / "products" / topic
    if not d.is_dir():
        return "fail", f"No product directory at {d}"

    # A document has no test suite, and building a venv and installing
    # Chromium to discover that costs minutes and megabytes every run.
    pw = pathways.for_topic(topic, quiet=True)
    if not pw.runs_tests:
        return "pass", (f"no test suite for a {pw.prompt_noun} — nothing to "
                        f"run, and nothing installed to find that out")''')

# ── 6. "did the build produce anything" depends on what it should produce ────
sk = swap("deliverable extensions", sk,
          "    src = [p for p in d.rglob(\"*\") if p.is_file() and p.suffix.lower() in SOURCE_EXT]",
          '''    # A document's deliverable is .md, not .py. This used to require a file
    # with a SOURCE_EXT extension, so a build that correctly produced only
    # markdown failed with "no source files".
    _ext = pathways.for_topic(topic, quiet=True).deliverable_ext
    src = [p for p in d.rglob("*") if p.is_file() and p.suffix.lower() in _ext]''')

# ── 7. skill 07 gets the same verdict handling as 03/05/06 ───────────────────
sk = swap("07 has a verdict", sk,
          "        if skill_num in ['03', '05', '06']:",
          "        if skill_num in ['03', '05', '06', '07']:")


# ═════════════════════════════════════════════════════════════════════════════
# langgraph_flow.py
# ═════════════════════════════════════════════════════════════════════════════

# ── 8. one inference algorithm, not two ──────────────────────────────────────
fl = swap("single inference", fl,
          '''def _infer_product_type(text: str) -> str:
    """Read the product type from the PRD, tolerating however the model
    formatted the marker. Defaults rather than failing — a markdown slip
    should not kill a run."""
    m = re.search(r"type\\W{0,6}(dashboard|document|api|software)", text, re.I)
    if m:
        return m.group(1).lower()
    low = text.lower()
    for t in ("dashboard", "api", "document"):
        if low.count(t) >= 3:
            return t
    return "software"''',
          '''def _infer_product_type(text: str) -> str:
    """
    Read the product type from the PRD.

    There used to be two of these — this one, and a different literal-match
    loop inside run_pipeline() over a different list in a different order.
    They could disagree about the same PRD between one phase and the next.
    Both now defer to product_pathways, which has one algorithm and one
    vocabulary built from the pathway definitions themselves.
    """
    import sys as _s
    if "/Users/ducorn/DC/scripts" not in _s.path:
        _s.path.insert(0, "/Users/ducorn/DC/scripts")
    import product_pathways as _pw
    return _pw.infer_from_text(text) or _pw.DEFAULT''')

# ── 9. run_pipeline stops re-deriving it ─────────────────────────────────────
fl = swap("run_pipeline defers", fl,
          '''    # Detect product type from PRD if not provided
    if not product_type:
        prd_path = PRODUCTS_DIR / "docs" / f"{topic}-PRD.md"
        if prd_path.exists():
            content = prd_path.read_text()
            for t in ["document", "dashboard", "api", "software"]:
                if f"**Type:** {t}" in content or f"Type: {t}" in content:
                    product_type = t
                    break
        product_type = product_type or "software"''',
          '''    # The recorded decision, then the PRD, then the default — and it says
    # which one it used. This was a second literal-match algorithm that did
    # not agree with _infer_product_type; nothing passes --type today, so
    # every resume re-derived the type here and could land somewhere else.
    import product_pathways as _pw
    _pathway = _pw.for_topic(topic, override=product_type)
    product_type = _pathway.name''')

# ── 10. the skill list follows the pathway, not complexity alone ─────────────
fl = swap("pathway picks the skills", fl,
          '''        if engine == "gstack":
            # G-Stack: run skills 01, 04, 05, 06 as isolated subprocesses
            # Skip 02/03 (design) for simple products
            skills = ["01", "04", "05", "06"]
            if state.get("complexity") in ["medium", "complex"]:
                skills = ["01", "02", "03", "04", "05", "06"]''',
          '''        if engine == "gstack":
            # Which skills run is a property of the KIND of product, not only
            # of its complexity. Complexity alone chose the list here, which
            # is why a document got a code review that demanded .env.example
            # and a QA step that demanded Playwright.
            import product_pathways as _pw
            _pathway = _pw.for_topic(topic, override=product_type)
            skills = _pw.skills_for(
                _pathway,
                has_ui=bool(state.get("has_ui")),
                complexity=state.get("complexity", "simple"),
            )
            print(f"🛤️  {_pathway.name}: running skills "
                  f"{', '.join(skills)}", flush=True)''')

# ── 11. skill 07 has a name in the flow's table ──────────────────────────────
fl = swap("07 named in the flow", fl,
          '''                    "05": "Skill 05 — Code Review",''',
          '''                    "05": "Skill 05 — Code Review",
                    "07": "Skill 07 — Content Review",''')


# ═════════════════════════════════════════════════════════════════════════════
# write both, or neither
# ═════════════════════════════════════════════════════════════════════════════
stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
targets = [(SKILL, sk), (FLOW, fl)]
backups = {}
for path, _ in targets:
    b = path.with_name(f"{path.stem}.backup-pathways-{stamp}{path.suffix}")
    shutil.copy2(path, b)
    backups[path] = b


def die(msg):
    for path, b in backups.items():
        shutil.copy2(b, path)
    sys.exit(f"{msg} — both files reverted")


for path, text in targets:
    path.write_text(text, encoding="utf-8")

for path, _ in targets:
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        die(f"SYNTAX ERROR in {path.name} ({e})")
    r = subprocess.run([sys.executable, "-m", "pyflakes", str(path)],
                       capture_output=True, text=True)
    u = [l for l in (r.stdout + r.stderr).splitlines() if "undefined name" in l]
    if u:
        die(f"{path.name}: " + "; ".join(u))
print("syntax and undefined-name checks: clean on both")

# ── the table, from the code that will actually run ──────────────────────────
print("\nwhat each kind of product now does:\n")
print(f"  {'type':10} {'skills':26} {'tests':6} {'ui gate':8} {'review':7} deploy")
print("  " + "─" * 66)
for name, pw in _pw.PATHWAYS.items():
    sk_list = ",".join(_pw.skills_for(pw, has_ui=True, complexity="medium"))
    print(f"  {name:10} {sk_list:26} "
          f"{'yes' if pw.runs_tests else 'no':6} "
          f"{'yes' if pw.checks_ui else 'no':8} "
          f"{'yes' if pw.reviews_code else 'no':7} "
          f"{'yes' if pw.deploys else 'no'}")

# ── the properties that matter, checked against the written files ────────────
sk_src = SKILL.read_text(encoding="utf-8")
fl_src = FLOW.read_text(encoding="utf-8")

print()
CHECKS = [
    (sk_src, "if not pw.checks_ui:",
     "the UI gate cannot fail a product that has no UI"),
    (sk_src, "if not pw.runs_tests:",
     "no venv, no pip, no Chromium for a document"),
    (sk_src, "pw.deliverable_ext" if "pw.deliverable_ext" in sk_src
     else "deliverable_ext",
     "a document's deliverable is .md, not .py"),
    (sk_src, '"07": "07-content-review.md"',
     "skill 07 exists and is loadable"),
    (fl_src, "_pw.skills_for(",
     "the skill list comes from the pathway"),
    (fl_src, "import product_pathways as _pw",
     "the flow reads the one definition"),
]
for src, must, why in CHECKS:
    if must not in src:
        die(f"missing: {why}")
    print(f"  ok   {why}")

# The old algorithms must be GONE, not merely bypassed. A second definition
# left in place is how two of these came to disagree in the first place.
for src, gone, why in [
    (fl_src, 'for t in ["document", "dashboard", "api", "software"]:',
     "run_pipeline no longer has its own type algorithm"),
    (fl_src, 'if state.get("complexity") in ["medium", "complex"]:\n'
             '                skills =',
     "complexity no longer decides the skill list by itself"),
    (sk_src, "THIS PRODUCT HAS NO USER INTERFACE\n=====",
     "the appended disclaimer is replaced by the pathway's own wording"),
]:
    if gone in src:
        die(f"still present: {why}")
    print(f"  ok   {why}")

print("\napplied: " + ", ".join(applied))
for path, b in backups.items():
    print(f"backup:  {b.name}")
print("""
Next, in order:

  1. apply the migration, so the type is a recorded decision:
       psql -d ducorn -f scripts/migrations/008_product_type.sql
       psql -d ducorn -c "SELECT product_type, count(*) FROM pipeline_runs \\
                          GROUP BY 1 ORDER BY 2 DESC"

  2. see what each product will now do:
       python3 scripts/product_pathways.py
       python3 scripts/product_pathways.py ducorn-technology-stack-documentation

  3. the tech-stack run can then finish. It will replay from the checkpoint,
     take the document pathway, and skip code review and the test suite
     entirely:
       python3 scripts/litellm_budget.py --key IRIS --budget 25 --apply
""")
