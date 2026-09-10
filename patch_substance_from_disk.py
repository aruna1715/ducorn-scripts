#!/usr/bin/env python3
"""
A skill is graded on what it wrote, not on the length of our error message.

    cd ~/DC && python3 scripts/patch_substance_from_disk.py            show
    cd ~/DC && python3 scripts/patch_substance_from_disk.py --apply    do it

Needs scripts/patchlib.py, and patch_blank_tool_calls applied first.
Apply when no pipeline is running.

── WHAT THE LOG SAID ────────────────────────────────────────────────────────

    🛑 G-Stack_Design_Specification_….md sent identically 3 times
    ✅ Skill 02 — Design Consultation PASSED
    VERDICT: PASS — 321 chars produced

321 is not the agent's work. It is the exact length of the WRITE LOOP
ABORTED notice that skill_runner returns when the guard fires. The
substance gate measured our own sentence and called it a pass.

The outcome happened to be right — the duplicate-write abort can only fire
AFTER a successful write, so the specification really was complete on disk.
Right answer, wrong reason, and the wrong reason is load-bearing.

── THE HOLE THIS OPENS ──────────────────────────────────────────────────────

patch_blank_tool_calls added a second kind of abort: three empty tool calls
in a row, where NOTHING was written. Its notice is 280 characters. The gate's
floor is 200.

So a skill that produced no file at all would have been graded PASS on the
length of a message saying it produced nothing. Skill 04 is backstopped by
build_produced_code and the review skills go through the verdict path, but
01 and 02 are not, and that is exactly the "half-baked run" that must not be
possible.

The handler also states, for a blank abort, that "its file output is on disk
and complete" — which is false. Nothing was written by those calls.

── THE FIX ──────────────────────────────────────────────────────────────────

Grade by the WRITE LEDGER, not by the notice.

deliverables(topic) asks the writer tool what this process actually wrote,
resolves each name through the jail exactly as the writer did, and reports
the files and their sizes. When the output is an abort notice, that is what
decides — and a blank abort with nothing on disk fails, as it must.

The same helper now serves verdict_in_deliverables, which had its own copy of
that resolution loop. Two places asking "what did this skill write?" in two
different pieces of code is the shape of nearly every defect in this
pipeline; there is one answer now.

── WHAT DOES NOT CHANGE ─────────────────────────────────────────────────────

The ordinary path. A skill that returns a real final answer is still judged
on its length, with the same floor and the same else — the else that the
dangling-else defect detached once already, and which the regression suite
watches.
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
LIB = DC / "scripts" / "patchlib.py"
TAG = "substancedisk"

# ── 1. one answer to "what did this skill write?" ───────────────────────────
HELPER_OLD = '''def verdict_in_deliverables(topic):
    """
    The verdict the skill WROTE DOWN. (status, line, filename), or None.

    Only .md files this process recorded, and only a VERDICT line near the
    end of one. Two documents that disagree resolve to a failure rather than
    to whichever was written first.
    """
    try:
        from tools.DuCornWriterTool import files_written
        from tools.product_jail import resolve_in_jail
    except Exception:
        return None

    found = []
    for fn in files_written(topic):
        if not fn.lower().endswith(".md"):
            continue
        # Through the jail, never around it.
        #
        # This used to be `_product_dir(topic) / fn`, and pathlib discards the
        # left side of a join when the right side is absolute — so an agent
        # that passed an absolute filename would have had one product read
        # another product's file. resolve_in_jail is the containment rule
        # itself; re-checking the path here would be a second copy of it,
        # free to drift from the real one.
        try:
            p = resolve_in_jail(topic, fn)
        except Exception:
            # PathEscape, or anything else: a name that does not resolve
            # inside this product is not this product's deliverable.
            continue
        try:
            body = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = [l for l in body.splitlines() if l.strip()]
        got = explicit_verdict("\\n".join(lines[-DELIVERABLE_TAIL_LINES:]))
        if got:
            found.append((got[0], got[1], fn))
'''

HELPER_NEW = '''# The first line of the notice skill_runner returns when a write loop is
# stopped. ONE spelling, because the handler writes it and the substance gate
# recognises it — and two copies of a sentinel drift.
ABORT_NOTICE = "WRITE LOOP ABORTED"

# Bytes on disk below which a set of deliverables is not a deliverable. A
# different quantity from the prose floor in main(): that one counts
# characters an agent said, this one counts bytes it wrote.
DELIVERABLE_FLOOR = 200


def deliverables(topic):
    """
    What this process actually wrote for `topic`: [(filename, path, bytes)].

    Resolved through the jail, exactly as the writer tool resolved each name
    when it created the file — same resolver, same answer, and an agent-chosen
    name that lands outside this product is not this product's deliverable.

    One helper because two callers need it: the verdict lookup, and the
    substance gate. Each having its own copy of this loop is the defect shape
    that produced eleven build directories and two verdicts.
    """
    try:
        from tools.DuCornWriterTool import files_written
        from tools.product_jail import resolve_in_jail
    except Exception:
        return []

    out = []
    for fn in files_written(topic):
        try:
            p = resolve_in_jail(topic, fn)
        except Exception:
            # PathEscape, or anything else: not this product's file.
            continue
        try:
            out.append((fn, p, p.stat().st_size))
        except OSError:
            continue
    return out


def verdict_in_deliverables(topic):
    """
    The verdict the skill WROTE DOWN. (status, line, filename), or None.

    Only .md files this process recorded, and only a VERDICT line near the
    end of one. Two documents that disagree resolve to a failure rather than
    to whichever was written first.
    """
    found = []
    for fn, p, _size in deliverables(topic):
        if not fn.lower().endswith(".md"):
            continue
        try:
            body = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = [l for l in body.splitlines() if l.strip()]
        got = explicit_verdict("\\n".join(lines[-DELIVERABLE_TAIL_LINES:]))
        if got:
            found.append((got[0], got[1], fn))
'''

# ── 2. the abort notice stops lying about a blank abort ─────────────────────
ABORT_OLD = '''        print(f"🛑 {loop}", flush=True)
        return (f"WRITE LOOP ABORTED — the agent sent {loop.filename} "
                f"identically {loop.count} times and ignored the refusal. Its "
                f"file output is on disk and complete; it produced no final "
                f"answer, so the verdict is read from the document it wrote. "
                f"If that document carries no VERDICT line, this skill fails.")'''

ABORT_NEW = '''        print(f"🛑 {loop}", flush=True)
        # Two kinds of abort, and they are not interchangeable.
        #
        # A duplicate-write abort can only fire AFTER a successful write, so
        # the deliverable is finished. A blank-call abort wrote nothing at
        # all — and this used to tell both of them that "its file output is
        # on disk and complete", which for the blank case is simply false.
        #
        # Either way the notice is OUR text, not the agent's, and what
        # follows it grades the FILES. See ABORT_NOTICE.
        if getattr(loop, "blank", False):
            return (f"{ABORT_NOTICE} — the agent sent {loop.count} empty tool "
                    f"calls in a row and could not form a valid one. Those "
                    f"calls wrote nothing. This skill passes only if it had "
                    f"already written its deliverable.")
        return (f"{ABORT_NOTICE} — the agent sent {loop.filename} "
                f"identically {loop.count} times and ignored the refusal. Its "
                f"file output is on disk and complete; it produced no final "
                f"answer, so the verdict is read from the document it wrote. "
                f"If that document carries no VERDICT line, this skill fails.")'''

# ── 3. the substance gate measures the disk, not our sentence ───────────────
GATE_OLD = '''            if len(body) >= 200:
                status, verdict = "pass", f"VERDICT: PASS — {len(body)} chars produced"
            else:
                status, verdict = "fail", f"VERDICT: FAIL — produced only {len(body)} chars of substance"'''

GATE_NEW = '''            if body.startswith(ABORT_NOTICE):
                # Our own notice is not the agent's work.
                #
                # Skill 02 was recorded "PASS — 321 chars produced", and 321
                # is the exact length of the duplicate-write notice. The
                # blank-call notice is 280, comfortably over the 200 floor,
                # so a skill that wrote NOTHING would have passed on the
                # length of a message saying it wrote nothing.
                _files = deliverables(topic)
                _bytes = sum(sz for _f, _p, sz in _files)
                if _bytes >= DELIVERABLE_FLOOR:
                    status, verdict = "pass", (
                        f"VERDICT: PASS — no final answer, but {len(_files)} "
                        f"file(s) and {_bytes:,} bytes written")
                    print(f"📄 graded on what is on disk: "
                          + ", ".join(f"{f} ({sz:,}B)"
                                      for f, _p, sz in _files), flush=True)
                else:
                    status, verdict = "fail", (
                        f"VERDICT: FAIL — the agent produced no final answer "
                        f"and wrote {_bytes:,} bytes across {len(_files)} "
                        f"file(s); there is no deliverable")
            elif len(body) >= 200:
                status, verdict = "pass", f"VERDICT: PASS — {len(body)} chars produced"
            else:
                status, verdict = "fail", f"VERDICT: FAIL — produced only {len(body)} chars of substance"'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in (RUNNER, LIB):
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

sys.path.insert(0, str(DC / "scripts"))
from patchlib import calls_in, code_only, py_ok, PatchCheckFailed   # noqa: E402

src = RUNNER.read_text(encoding="utf-8")
print("patch_substance_from_disk\n")

if "def deliverables" in src:
    sys.exit("NOTHING DONE — the substance gate already reads the disk.")
if "blank=False" not in (DC / "ducorn" / "tools" / "DuCornWriterTool.py"
                         ).read_text(encoding="utf-8"):
    sys.exit("NOTHING DONE — apply patch_blank_tool_calls first; without it "
             "there is no blank-abort to distinguish.")

bad = False
for label, anchor in [("verdict_in_deliverables", HELPER_OLD),
                      ("the write-loop abort handler", ABORT_OLD),
                      ("the substance gate", GATE_OLD)]:
    n = src.count(anchor)
    print(f"  {'ok ' if n == 1 else '!! '}{label}  ({n} match)")
    bad |= n != 1
if bad:
    sys.exit("\nNOTHING DONE — an anchor did not match exactly once.")

r = subprocess.run(["pgrep", "-f", "ducorn/skill_runner.py"],
                   capture_output=True, text=True)
if r.stdout.strip():
    sys.exit(f"NOTHING DONE — skill_runner is running (pid "
             f"{r.stdout.split()[0]}). Apply this when the run has finished.")
print("  ok  skill_runner is not running")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(RUNNER, RUNNER.with_suffix(f".backup-{TAG}-{stamp}.py"))
RUNNER.write_text(src.replace(HELPER_OLD, HELPER_NEW, 1)
                     .replace(ABORT_OLD, ABORT_NEW, 1)
                     .replace(GATE_OLD, GATE_NEW, 1), encoding="utf-8")
print(f"\nwrote skill_runner.py, backup tagged {TAG}-{stamp}")

after = RUNNER.read_text(encoding="utf-8")
try:
    py_ok(after, "skill_runner.py")
except PatchCheckFailed as e:
    sys.exit(f"⚠️  {e} — restore the backup.")

tree = py_ok(after, "skill_runner.py")

# One resolver, two callers.
if len(calls_in(after, "verdict_in_deliverables", "deliverables")) != 1:
    sys.exit("⚠️  verdict_in_deliverables does not use the shared helper — "
             "restore the backup.")
if len(calls_in(after, "verdict_in_deliverables", "files_written")) != 0:
    sys.exit("⚠️  verdict_in_deliverables still resolves names itself — that "
             "is the duplication being removed. Restore the backup.")
if not calls_in(after, "main", "deliverables"):
    sys.exit("⚠️  main() never asks what was written, so the abort branch "
             "cannot grade the disk. Restore the backup.")
print("verified: one resolver, used by the verdict lookup and by main().")

# The dangling else must not come back: the length test keeps its else, and
# the BUILD_SKILL test still has none. This is the defect the suite watches.
def _ifs(scope_name, needle):
    scope = next(n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == scope_name)
    return sorted((n.lineno, bool(n.orelse)) for n in ast.walk(scope)
                  if isinstance(n, ast.If) and needle in ast.dump(n.test))

length = _ifs("main", "200")
build = _ifs("main", "BUILD_SKILL")
if len(length) != 1 or not length[0][1]:
    sys.exit(f"⚠️  the length test is now {length} — it must exist exactly "
             f"once and keep its else. Restore the backup.")
if len(build) != 1 or build[0][1]:
    sys.exit(f"⚠️  the BUILD_SKILL test is now {build} — it must have no "
             f"else. Restore the backup.")
abort_branch = _ifs("main", "ABORT_NOTICE")
if len(abort_branch) != 1 or not abort_branch[0][1]:
    sys.exit("⚠️  the abort branch is missing or has no alternative — "
             "restore the backup.")
print("          branch structure intact: abort → elif length → else.")

# ── the grading rule, against the SHIPPED constants ─────────────────────────
def _const(name):
    for node in tree.body:
        if isinstance(node, ast.Assign) and node.targets \
                and getattr(node.targets[0], "id", None) == name:
            return ast.literal_eval(node.value)
        if isinstance(node, ast.AnnAssign) \
                and getattr(node.target, "id", None) == name:
            return ast.literal_eval(node.value)
    sys.exit(f"⚠️  {name} is not a module-level literal — restore the backup.")

notice = _const("ABORT_NOTICE")
floor = _const("DELIVERABLE_FLOOR")

# Both notices the handler can return must be recognised by the gate.
handler = next(n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "run_with_crewai")
returns = [n for n in ast.walk(handler) if isinstance(n, ast.Return)]
notices = []
for rn in returns:
    txt = "".join(v.value for v in ast.walk(rn)
                  if isinstance(v, ast.Constant) and isinstance(v.value, str))
    if "empty tool calls" in txt or "ignored the refusal" in txt:
        notices.append(txt)
if len(notices) != 2:
    sys.exit(f"⚠️  expected two abort notices in run_with_crewai, found "
             f"{len(notices)} — restore the backup.")
for txt in notices:
    # Each is built as f"{ABORT_NOTICE} — …", so the literal parts start with
    # the em-dash. What matters is that neither hardcodes a different opener.
    if "WRITE LOOP ABORTED" in txt and notice not in txt:
        sys.exit("⚠️  an abort notice hardcodes its own opener instead of "
                 "using ABORT_NOTICE — restore the backup.")
blank_notice = next((t for t in notices if "empty tool calls" in t), "")
if "on disk and complete" in blank_notice:
    sys.exit("⚠️  the blank-abort notice still claims files are on disk — "
             "that is the false statement being removed. Restore the backup.")
print(f"          two distinct notices; the blank one no longer claims a "
      f"file was written.")

# The floor, exercised the way main() will use it.
def grade(total_bytes, n_files):
    if total_bytes >= floor:
        return "pass"
    return "fail"

problems = []
if grade(0, 0) != "fail":
    problems.append("a blank abort with nothing on disk would still pass")
if grade(floor - 1, 1) != "fail":
    problems.append("a file below the floor passes")
if grade(floor, 1) != "pass":
    problems.append("a file at the floor fails")
if grade(21000, 2) != "pass":
    problems.append("real deliverables fail")
if problems:
    sys.exit("⚠️  " + "; ".join(problems))
print(f"          floor {floor} bytes: nothing written fails, real "
      f"deliverables pass.")

print("""
Skill 02 would now read

  📄 graded on what is on disk: G-Stack_Design_Specification_….md (4,812B)
  VERDICT: PASS — no final answer, but 1 file(s) and 4,812 bytes written

instead of counting our own error message as 321 characters of work. And a
blank abort that wrote nothing now fails, which is what it always should
have done.

Re-run scripts/regress.py afterwards — the length test and the BUILD_SKILL
branch are both checked here too, but the suite is the thing that keeps
checking them.
""")
