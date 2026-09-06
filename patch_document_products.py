#!/usr/bin/env python3
"""
A document is not a web app, and its files must reach where the pipeline looks.

── ONE: the code reviewer was handed a UI checklist ─────────────────────────

    ❌ Skill 05 — Code Review FAILED
    VERDICT: FAIL — no test suite (0 tests collected; pipeline requires
    Playwright UI tests for HTML products)

For a document. There is no code, no interface, and nothing to test with a
browser. The reviewer was not being unreasonable — it was told to be:

    if skill_num not in UI_REVIEW_SKILLS:      # {"03", "05"}
        return text
    ... 8 KB of interface guidelines: focus states, hit targets, motion ...

Skill 04 asks _has_ui(topic) before it demands browser tests. Skills 03 and 05
never ask. So a code reviewer reading a checklist about focus rings, looking at
two .html files, concluded it was reviewing a web product — and failed the
build for not testing an interface that does not exist.

The asymmetry is the bug. The same question 04 asks, 03 and 05 now ask.

And for a product with no UI, skill 05 is told so explicitly rather than merely
not told otherwise. Silence is not an instruction; a model fills it.

── TWO: the documents were written where nothing looks for them ─────────────

REX wrote four good files:

    products/ducorn-technology-stack-documentation/
        ducorn-tech-stack-internal.md      33 KB, 3 diagrams
        ducorn-tech-stack-overview.md      16 KB, 2 diagrams
        …and both as .html

He had no choice — the product jail permits products/<topic>/ and nothing else.
But node_build, for a document, commits docs/, and the PDF step globs
docs/*.md filtered by topic. So the documents are not committed, not converted,
and not synced to Drive. They exist and the pipeline cannot see them.

Two correct behaviours, in different directories, and nothing carrying one to
the other. The jail is right and the publish target is right; the bridge was
missing.

publish_documents(topic) copies the product's markdown into docs/ with the slug
prefix the rest of the pipeline expects, before the commit. Pipeline artifacts —
README, the review and QA reports — are left where they are; they are not the
deliverable.
"""
import ast
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SKILL = Path("/Users/ducorn/DC/ducorn/skill_runner.py")
FLOW = Path("/Users/ducorn/DC/ducorn/flows/langgraph_flow.py")

sk = SKILL.read_text(encoding="utf-8")
fl = FLOW.read_text(encoding="utf-8")

if "def publish_documents" in fl:
    print("Already patched — documents reach docs/ and reviewers ask about UI.")
    sys.exit(0)
if "_has_ui" not in sk:
    sys.exit("Apply patch_build_ui_tests.py first. NOTHING WRITTEN.")

applied = []


def swap(label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {text.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    applied.append(label)
    return text.replace(old, new, 1)


# ── 1. the reviewers ask the same question the builder asks ──────────────────
sk = swap("guidelines need a ui", sk,
          '''    if skill_num not in UI_REVIEW_SKILLS:
        return text''',
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
"""''')

# ── 2. the documents reach the directory the pipeline reads ──────────────────
fl = swap("publish helper", fl, "def _update_db_status(topic: str, status: str",
          '''# Files the pipeline itself writes into a product directory. They are process
# artifacts, not the thing that was commissioned.
_NOT_THE_DELIVERABLE = {
    "README.md", "code-review.md", "qa-report.md", "prd-analysis.md",
    "qa-report-skill-06.md",
}


def publish_documents(topic: str) -> list:
    """
    Copy a document product's markdown into docs/, where the rest of the
    pipeline looks for it.

    REX can only write products/<topic>/ — the product jail permits nothing
    else, and that is correct. node_build commits docs/ for a document, and
    the PDF step globs docs/*.md by topic. Both behaviours are right and
    nothing carried one to the other, so four finished documents sat in a
    directory the pipeline does not read.

    Named <slug>-<file>.md so the existing topic filter finds them.
    """
    # langgraph_flow has no module-level shutil. Imported here rather than
    # added to the header — a new module-level name in a file that does not
    # already have it is how the activity API went down earlier tonight.
    import shutil as _shutil

    src_dir = PRODUCTS_DIR / "products" / topic
    docs = PRODUCTS_DIR / "docs"
    if not src_dir.is_dir():
        return []
    docs.mkdir(parents=True, exist_ok=True)

    published = []
    for md in sorted(src_dir.glob("*.md")):
        if md.name in _NOT_THE_DELIVERABLE or md.name.startswith("skill-"):
            continue
        stem = md.stem
        # Do not end up with ducorn-tech-stack-ducorn-tech-stack-internal.md
        name = (f"{stem}.md" if stem.startswith(topic)
                else f"{topic}-{stem}.md")
        dest = docs / name
        try:
            _shutil.copy2(md, dest)
            published.append(dest.name)
        except OSError as e:
            print(f"⚠️  could not publish {md.name}: {e}", flush=True)

    if published:
        print(f"📄 published {len(published)} document(s) to docs/: "
              + ", ".join(published), flush=True)
    else:
        print(f"⚠️  no documents found in products/{topic}/ to publish — "
              f"the PDF step and Drive sync will have nothing", flush=True)
    return published


def _update_db_status(topic: str, status: str''')

fl = swap("publish before commit", fl,
          '''        if product_type == 'document':
            _git_publish("docs/", f"docs(rex): {topic}")''',
          '''        if product_type == 'document':
            # Before the commit, or the commit has nothing to commit: the
            # writer is jailed to products/<topic>/ and this publishes to the
            # directory the commit, the PDF step and the Drive sync all read.
            publish_documents(topic)
            _git_publish("docs/", f"docs(rex): {topic}")
            # The product's own directory holds the same files plus the review
            # and QA reports; committing it too keeps the working copy honest.
            _git_publish(f"products/{topic}/", f"feat(rex): {topic} sources")''')

# ── write both, or neither ───────────────────────────────────────────────────
stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
targets = [(SKILL, sk), (FLOW, fl)]
backups = {}
for path, _ in targets:
    b = path.with_name(f"{path.stem}.backup-docproducts-{stamp}{path.suffix}")
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

# ── exercise the publish against the real product ────────────────────────────
src = FLOW.read_text(encoding="utf-8")
tree = ast.parse(src)
seg = next((ast.get_source_segment(src, n) for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "publish_documents"),
           None)
if seg is None:
    die("publish_documents did not land")

import tempfile
root = Path(tempfile.mkdtemp())
prod = root / "products" / "ducorn-tech-doc"
prod.mkdir(parents=True)
(root / "docs").mkdir()
for n in ("ducorn-tech-stack-internal.md", "ducorn-tech-stack-overview.md",
          "README.md", "code-review.md", "qa-report.md",
          "ducorn-tech-doc-notes.md"):
    (prod / n).write_text("# x\n")
ns = {"PRODUCTS_DIR": root, "Path": Path,
      "_NOT_THE_DELIVERABLE": {"README.md", "code-review.md", "qa-report.md",
                               "prd-analysis.md", "qa-report-skill-06.md"}}
exec(seg, ns)
out = ns["publish_documents"]("ducorn-tech-doc")

print("\nwhat gets published:")
for name in sorted(out):
    print(f"  {name}")
checks = [
    ("the two deliverables are published", len(out) == 3),
    ("the slug prefix is added where missing",
     "ducorn-tech-doc-ducorn-tech-stack-internal.md" in out),
    ("a file already prefixed is not prefixed twice",
     "ducorn-tech-doc-notes.md" in out),
    ("README, code-review and qa-report are left alone",
     not any(n.endswith(("README.md", "code-review.md", "qa-report.md"))
             for n in out)),
]
print()
for name, ok in checks:
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")
    if not ok:
        die(name)

for must, why in [
    ("THIS PRODUCT HAS NO USER INTERFACE",
     "a non-UI review is told so explicitly"),
    ("if not _has_ui(topic):", "03 and 05 ask the question 04 asks"),
]:
    if must not in SKILL.read_text(encoding="utf-8"):
        die(f"missing: {why}")
    print(f"  ok   {why}")

print("\napplied: " + ", ".join(applied))
for path, b in backups.items():
    print(f"backup:  {b.name}")
print("""
Your four documents are already written and are good. Publish them and finish
the run — the build will replay from the checkpoint, skill 05 will review a
document as a document, and skill 06 needs IRIS's key budget raised first:

  python3 scripts/litellm_budget.py                       # see the per-key budgets
  python3 scripts/litellm_budget.py --key IRIS --budget 25 --apply
""")
