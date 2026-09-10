#!/usr/bin/env python3
"""
A review skill's verdict is what it WROTE DOWN, not only what it said last.

    cd ~/DC && python3 scripts/patch_verdict_from_deliverable.py            show
    cd ~/DC && python3 scripts/patch_verdict_from_deliverable.py --apply    do it

Needs scripts/patchlib.py. Apply when no pipeline is running.

── WHAT FAILED ──────────────────────────────────────────────────────────────

    🛑 G-Stack_Design_Review_zz-plumbing-check-p1-status.md sent identically
       3 times — aborting the agent loop
    💸 Skill 03 — Design Review: $0.00
    ❌ Skill 03 — Design Review FAILED
    VERDICT: FAIL — no explicit VERDICT line in output

The document on disk is 23 lines, complete, and its LAST LINE is

    VERDICT: PASS

The agent did the work, wrote the review, reached a verdict and recorded it.
Then it did not know how to stop, sent the identical file a third time, and
the writer tool ended the loop — which it can only do AFTER a successful
write, so the deliverable was already finished. No final answer was produced,
parse_verdict had only the abort notice to read, and a completed skill was
recorded as a failure.

── THE ROOT CAUSE ───────────────────────────────────────────────────────────

The verdict is stored in two places and the code reads the ephemeral one.

The G-Stack convention puts a VERDICT line at the end of the review document.
The task's expected_output ALSO demands a VERDICT line as the final answer.
Two copies of one fact — the recurring shape of nearly every defect found in
this pipeline — and parse_verdict consults only the copy that evaporates when
the agent loop breaks.

The document is the durable artifact. It is what the next skill reads, what
the operator opens, and what survives the process. Reading the verdict from
it is not a fallback or a guess; it is reading the deliverable instead of the
chat transcript.

── THE RULE ─────────────────────────────────────────────────────────────────

    both present, agreeing     that verdict
    both present, disagreeing  FAIL, naming both — a disagreement is never
                               a pass
    only one present           that one, and the log says which
    neither                    FAIL, exactly as today

Nothing is invented. A document with no VERDICT line supplies no verdict, and
the skill fails as it does now. The only outcome that changes is the one where
the agent wrote its verdict down and the runner refused to look.

── WHY THIS IS SAFE FOR SKILL 06 ────────────────────────────────────────────

The abort handler's comment argued the opposite: "A QA verdict invented after
the agent lost the thread is worse than a failure." That is right about
INVENTION and this does not invent. It is also no longer the only control —
the tests-decide short circuit means pytest runs BEFORE the model is called
and a failing suite exits without spending anything, and the `06` override
below still downgrades a pass when tests or the UI check fail. Those run after
this resolution and can only lower it.

── SCOPE ────────────────────────────────────────────────────────────────────

Only .md files the writer tool recorded for THIS process, and only a VERDICT
line inside the last few non-empty lines — the convention says the verdict is
last, and skill 01's own template contains a literal "VERDICT: FAIL —
<reason>" example mid-document that must never be mistaken for a decision.

One skill_runner process runs one skill (skill_key is computed once and the
failure path exits), so the writer's ledger is already scoped to this skill.
"""
from __future__ import annotations

import argparse
import ast
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
RUNNER = DC / "ducorn" / "skill_runner.py"
WRITER = DC / "ducorn" / "tools" / "DuCornWriterTool.py"
LIB = DC / "scripts" / "patchlib.py"
TAG = "verdictdoc"

# ── 1. the writer tool learns to say what it wrote ───────────────────────────
WRITER_OLD = '''def writes_for(topic, filename) -> list:
    """The content hashes written to this file so far, oldest first."""
    return list(_WRITES.get((topic or "", filename), []))'''

WRITER_NEW = '''def writes_for(topic, filename) -> list:
    """The content hashes written to this file so far, oldest first."""
    return list(_WRITES.get((topic or "", filename), []))


def files_written(topic) -> list:
    """
    Every filename this process wrote for `topic`, in first-write order.

    The ledger has always known this and nothing could ask it. A review
    skill's verdict lives in the document it produced, and locating that
    document by guessing at its name would be a second copy of a fact this
    dict already holds — which is the exact mistake the verdict itself was
    suffering from.
    """
    return [fn for (tp, fn) in _WRITES if tp == (topic or "")]'''

# ── 2. detection separated from the failure default ──────────────────────────
RUNNER_PARSE_OLD = '''def parse_verdict(output: str):
    """An explicit VERDICT line, or it's a failure. No fuzzy matching."""
    for line in reversed(output.strip().splitlines()):
        s = line.strip().upper()
        if s.startswith("VERDICT:"):
            if "PASS" in s: return "pass", line.strip()
            if "FAIL" in s: return "fail", line.strip()
    return "fail", "VERDICT: FAIL — no explicit VERDICT line in output"'''

RUNNER_PARSE_NEW = '''# How far from the end of a document a VERDICT line may sit and still count.
#
# The G-Stack convention is that the verdict is the last line. Skill 01's own
# template contains a literal "VERDICT: FAIL — <reason>" as an EXAMPLE, and a
# scan of the whole document would read that example as a decision.
DELIVERABLE_TAIL_LINES = 5


def explicit_verdict(text: str):
    """
    (status, line) if an explicit VERDICT line is present, else None.

    Separated from parse_verdict so that ABSENT and FAIL stop being the same
    answer. They were indistinguishable before, which is why a missing final
    answer and a genuine rejection produced the same record.
    """
    for line in reversed(text.strip().splitlines()):
        s = line.strip().upper()
        if s.startswith("VERDICT:"):
            if "PASS" in s: return "pass", line.strip()
            if "FAIL" in s: return "fail", line.strip()
    return None


def parse_verdict(output: str):
    """An explicit VERDICT line, or it's a failure. No fuzzy matching."""
    return explicit_verdict(output) or (
        "fail", "VERDICT: FAIL — no explicit VERDICT line in output")


def verdict_in_deliverables(topic):
    """
    The verdict the skill WROTE DOWN. (status, line, filename), or None.

    Only .md files this process recorded, and only a VERDICT line near the
    end of one. Two documents that disagree resolve to a failure rather than
    to whichever was written first.
    """
    try:
        from tools.DuCornWriterTool import files_written
    except Exception:
        return None
    try:
        d = _product_dir(topic)
    except Exception:
        return None

    found = []
    for fn in files_written(topic):
        if not fn.lower().endswith(".md"):
            continue
        try:
            body = (d / fn).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = [l for l in body.splitlines() if l.strip()]
        got = explicit_verdict("\\n".join(lines[-DELIVERABLE_TAIL_LINES:]))
        if got:
            found.append((got[0], got[1], fn))

    if not found:
        return None
    if len({s for s, _v, _f in found}) > 1:
        names = ", ".join(f for _s, _v, f in found)
        return ("fail",
                f"VERDICT: FAIL — the documents disagree ({names}); a "
                f"disagreement is not a pass", names)
    return found[0]


def resolve_review_verdict(said, wrote):
    """
    One verdict out of the two places it can be written.

    `said`  = explicit_verdict(final answer)   -> (status, line) or None
    `wrote` = verdict_in_deliverables(topic)   -> (status, line, file) or None

    Returns (status, verdict, note). Nothing here invents a verdict: with
    neither source present the answer is the same failure as before.
    """
    if said and wrote:
        if said[0] == wrote[0]:
            return said[0], said[1], f"verdict agrees in the answer and in {wrote[2]}"
        return ("fail",
                f"VERDICT: FAIL — the final answer says {said[0].upper()} but "
                f"{wrote[2]} says {wrote[0].upper()}; a disagreement is not a "
                f"pass", None)
    if wrote:
        return wrote[0], wrote[1], (f"no verdict in the final answer — read "
                                    f"from {wrote[2]}, which the agent wrote")
    if said:
        return said[0], said[1], None
    return "fail", "VERDICT: FAIL — no explicit VERDICT line in output", None'''

# ── 3. the branch consults both ──────────────────────────────────────────────
RUNNER_BRANCH_OLD = '''        if skill_num in ['03', '05', '06', '07']:
            status, verdict = parse_verdict(output)
            if skill_num == '06':'''

RUNNER_BRANCH_NEW = '''        if skill_num in ['03', '05', '06', '07']:
            # Two places carry the verdict; read both.
            #
            # Skill 03 wrote a complete review ending "VERDICT: PASS", then
            # looped, and the writer tool stopped it — after the write, so the
            # document was finished. There was no final answer to parse and a
            # done skill was recorded as failed.
            _said = explicit_verdict(output)
            _wrote = verdict_in_deliverables(topic)
            status, verdict, _note = resolve_review_verdict(_said, _wrote)
            if _note:
                print(f"🧾 {_note}", flush=True)
            if skill_num == '06':'''

# ── 4. the abort notice stops promising a missing verdict ────────────────────
ABORT_OLD = '''        return (f"WRITE LOOP ABORTED — the agent sent {loop.filename} "
                f"identically {loop.count} times and ignored the refusal. Its "
                f"file output is on disk and complete; it produced no final "
                f"answer, so any verdict this skill was meant to return is "
                f"missing.")'''

ABORT_NEW = '''        return (f"WRITE LOOP ABORTED — the agent sent {loop.filename} "
                f"identically {loop.count} times and ignored the refusal. Its "
                f"file output is on disk and complete; it produced no final "
                f"answer, so the verdict is read from the document it wrote. "
                f"If that document carries no VERDICT line, this skill fails.")'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in (RUNNER, WRITER, LIB):
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

sys.path.insert(0, str(DC / "scripts"))
from patchlib import calls_in, code_only, py_ok, PatchCheckFailed   # noqa: E402

runner_src = RUNNER.read_text(encoding="utf-8")
writer_src = WRITER.read_text(encoding="utf-8")
print("patch_verdict_from_deliverable\n")

if "def resolve_review_verdict" in runner_src:
    sys.exit("NOTHING DONE — the verdict already comes from the deliverable.")

bad = False
for label, hay, anchor in [
        ("writes_for, in DuCornWriterTool", writer_src, WRITER_OLD),
        ("parse_verdict", runner_src, RUNNER_PARSE_OLD),
        ("the 03/05/06/07 branch", runner_src, RUNNER_BRANCH_OLD),
        ("the write-loop abort notice", runner_src, ABORT_OLD)]:
    n = hay.count(anchor)
    print(f"  {'ok ' if n == 1 else '!! '}{label}  ({n} match)")
    bad |= n != 1
if bad:
    sys.exit("\nNOTHING DONE — an anchor did not match exactly once.")

# _product_dir is what verdict_in_deliverables resolves the document through.
if "def _product_dir" not in runner_src:
    sys.exit("NOTHING DONE — skill_runner has no _product_dir().")
print("  ok  _product_dir() exists")

# Applying mid-run would change the verdict logic between skills.
r = subprocess.run(["pgrep", "-f", "ducorn/skill_runner.py"],
                   capture_output=True, text=True)
if r.stdout.strip():
    sys.exit(f"NOTHING DONE — skill_runner is running (pid "
             f"{r.stdout.split()[0]}). Apply this when it has finished.")
print("  ok  skill_runner is not running")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
for f in (RUNNER, WRITER):
    shutil.copy2(f, f.with_suffix(f".backup-{TAG}-{stamp}.py"))

WRITER.write_text(writer_src.replace(WRITER_OLD, WRITER_NEW, 1),
                  encoding="utf-8")
RUNNER.write_text(runner_src
                  .replace(RUNNER_PARSE_OLD, RUNNER_PARSE_NEW, 1)
                  .replace(RUNNER_BRANCH_OLD, RUNNER_BRANCH_NEW, 1)
                  .replace(ABORT_OLD, ABORT_NEW, 1), encoding="utf-8")
print(f"\nwrote skill_runner.py and DuCornWriterTool.py, backups tagged "
      f"{TAG}-{stamp}")

after_runner = RUNNER.read_text(encoding="utf-8")
after_writer = WRITER.read_text(encoding="utf-8")
for label, src in (("skill_runner.py", after_runner),
                   ("DuCornWriterTool.py", after_writer)):
    try:
        py_ok(src, label)
    except PatchCheckFailed as e:
        sys.exit(f"⚠️  {e} — restore the backups.")

# Structure, from the parse tree — comments explaining the change cannot
# satisfy any of these.
code = code_only(after_runner)
for needed in ("def explicit_verdict", "def verdict_in_deliverables",
               "def resolve_review_verdict"):
    if needed not in code:
        sys.exit(f"⚠️  {needed} is missing — restore the backups.")
if len(calls_in(after_runner, "parse_verdict", "explicit_verdict")) != 1:
    sys.exit("⚠️  parse_verdict no longer delegates to explicit_verdict — "
             "two copies of the scan would drift. Restore the backups.")
if len(calls_in(after_runner, "verdict_in_deliverables", "files_written")) != 1:
    sys.exit("⚠️  verdict_in_deliverables does not ask the writer ledger — "
             "restore the backups.")
if "def files_written" not in code_only(after_writer):
    sys.exit("⚠️  files_written did not land in DuCornWriterTool — restore "
             "the backups.")
print("verified: all three functions exist as code; parse_verdict delegates "
      "rather than duplicating.")

# ── the precedence table, run against the SHIPPED function ───────────────────
# Extracted from the patched file by ast and executed on its own, so this
# proves the code that will run — not a restatement of it in this script.
tree = py_ok(after_runner, "skill_runner.py")
fn = next((n for n in tree.body
           if isinstance(n, ast.FunctionDef)
           and n.name == "resolve_review_verdict"), None)
if fn is None:
    sys.exit("⚠️  resolve_review_verdict is not a module-level function — "
             "restore the backups.")

ns: dict = {}
exec(compile(ast.Module(body=[fn], type_ignores=[]), "<shipped>", "exec"), ns)
resolve = ns["resolve_review_verdict"]

SAID_P = ("pass", "VERDICT: PASS")
SAID_F = ("fail", "VERDICT: FAIL — bad contrast")
WROTE_P = ("pass", "VERDICT: PASS", "G-Stack_Design_Review.md")
WROTE_F = ("fail", "VERDICT: FAIL — missing tests", "G-Stack_Design_Review.md")

problems = []
cases = [
    # (said, wrote, expected status, what it means)
    (None,   WROTE_P, "pass", "THE BUG: loop aborted, document says PASS"),
    (None,   WROTE_F, "fail", "loop aborted, document says FAIL"),
    (None,   None,    "fail", "nothing anywhere still fails"),
    (SAID_P, None,    "pass", "no document, answer says PASS"),
    (SAID_F, None,    "fail", "no document, answer says FAIL"),
    (SAID_P, WROTE_P, "pass", "both agree on PASS"),
    (SAID_F, WROTE_F, "fail", "both agree on FAIL"),
    (SAID_P, WROTE_F, "fail", "answer PASS, document FAIL — must not pass"),
    (SAID_F, WROTE_P, "fail", "document PASS, answer FAIL — must not pass"),
]
for said, wrote, want, why in cases:
    got = resolve(said, wrote)[0]
    if got != want:
        problems.append(f"{why}: expected {want}, got {got}")

# A verdict must never be manufactured out of nothing.
if "no explicit VERDICT line" not in resolve(None, None)[1]:
    problems.append("the empty case stopped reporting why it failed")

if problems:
    sys.exit("⚠️  the precedence is wrong — restore the backups:\n  "
             + "\n  ".join(problems))
print(f"          precedence proven on {len(cases)} cases, including both "
      f"disagreements.")

print("""
Nothing else to restart — skill_runner is read fresh each phase.

Recover and resume zz-plumbing-check phase 1 from the dashboard. Skill 03
re-runs; if the agent loops again the document it wrote is what decides, and
the log will say so:

  🧾 no verdict in the final answer — read from
     G-Stack_Design_Review_zz-plumbing-check-p1-status.md, which the agent wrote

Still free. Every 💸 line should stay $0.00.
""")
