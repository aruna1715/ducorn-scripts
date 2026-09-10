#!/usr/bin/env python3
"""
A blank tool call is not a write, and `overwrite` was only ever a trap.

    cd ~/DC && python3 scripts/patch_blank_tool_calls.py            show
    cd ~/DC && python3 scripts/patch_blank_tool_calls.py --apply    do it

Needs scripts/patchlib.py. Apply when no pipeline is running.

── WHAT THE LOG ACTUALLY SAYS ───────────────────────────────────────────────

    Args: {'filename': '', 'content': '', 'overwrite': ''}

qwen2.5:32b emits the tool's SHAPE with every value blank. Not once — twelve
times in one phase log. It is what a small model does when it has finished
its work and does not know how to say so: the most available action is the
tool it has been using, with nothing in it.

Two different failures come out of that one behaviour:

  overwrite=''   pydantic refuses to parse '' as a boolean, the call dies
                 before _run, CrewAI feeds the error back, and the model —
                 which cannot fix what it does not understand — sends the
                 identical blank again. Twelve validation errors.

  filename=''    when the blank lands elsewhere the call reaches _run, and
  content=''     an empty filename is RECORDED IN THE WRITE LEDGER as a
                 legitimate write. Three of those and the loop guard fires.
                 Eight of the twelve aborts in this log have an empty
                 filename — none of them were real writes, and the guard was
                 reporting a write loop that never happened.

── THE TWO FIXES ────────────────────────────────────────────────────────────

1. `overwrite` GOES.

   Nothing in the stack has ever passed it. Its entire effect is
   `'w' if overwrite else 'x'`, and every real call takes the 'w' branch. A
   parameter with one used value is not a parameter — it is a third field a
   small model has to type correctly, and the only thing it has ever done
   here is turn a working call into an unrecoverable validation error.

   The schema becomes two required strings, which is a shape a 32B model can
   fill.

2. A BLANK CALL IS REFUSED, NOT RECORDED.

   Checked before the jail and before the ledger, because an empty filename
   is not a path and an empty write is not a write. The refusal says what was
   wrong AND names the thing the model is failing to do — reply with a final
   answer — because that is what a blank call is usually trying to be.

   Repeated blanks still abort; an agent that cannot form a call would
   otherwise burn max_iter. But it aborts as what it is, so the log stops
   claiming a file was written three times when no file was named.

── WHAT THIS DOES NOT CLAIM ─────────────────────────────────────────────────

That the run will now pass. It removes two of the three ways this phase
failed; whether qwen then produces a final answer is the next measurement,
not a prediction. The third mode — re-sending a REAL file it has already
written — is untouched here and is what killed skill 03 on APPROVED_DESIGN
.html.
"""
from __future__ import annotations

import argparse
import ast
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
WRITER = DC / "ducorn" / "tools" / "DuCornWriterTool.py"
LIB = DC / "scripts" / "patchlib.py"
TAG = "blankcalls"

# ── 1. the exception learns to say what kind of loop it stopped ─────────────
EXC_OLD = '''    def __init__(self, filename, count):
        self.filename = filename
        self.count = count
        super().__init__(f"{filename} was written identically {count} times; "
                         f"the agent ignored the refusal, so the tool stopped "
                         f"it. The file on disk is complete.")'''

EXC_NEW = '''    def __init__(self, filename, count, blank=False):
        self.filename = filename
        self.count = count
        # A blank-call abort and a duplicate-write abort are different events
        # and must not read the same. The log used to announce that a file
        # had been "written identically 3 times" when no filename was ever
        # sent — eight times in one phase.
        self.blank = blank
        if blank:
            super().__init__(
                f"the agent sent {count} empty tool calls in a row and could "
                f"not form a valid one, so the tool stopped it. Nothing was "
                f"written by those calls; any deliverable already on disk is "
                f"complete.")
        else:
            super().__init__(
                f"{filename} was written identically {count} times; the agent "
                f"ignored the refusal, so the tool stopped it. The file on "
                f"disk is complete.")'''

# ── 2. a blank counter, reset with the ledger ───────────────────────────────
LEDGER_OLD = '''def reset_writes():
    """Clear the ledger. For tests, and for anything that reuses the process."""
    _WRITES.clear()'''

LEDGER_NEW = '''# Blank tool calls, per topic. Counted SEPARATELY from writes, because a
# blank call is not a write and must not be recorded as one.
_BLANKS: dict = {}


def reset_writes():
    """Clear the ledger. For tests, and for anything that reuses the process."""
    _WRITES.clear()
    _BLANKS.clear()


def blank_call(topic, filename, content):
    """
    Handle a tool call with nothing in it. Returns the refusal to show the
    agent, or raises WriteLoopAborted once the agent has proved it cannot do
    better.

    Separate and module-level so it can be tested without CrewAI: the tool
    class cannot be instantiated without the framework, and a rule that can
    only be exercised by running the pipeline is a rule nobody checks.
    """
    n = _BLANKS.get(topic or "", 0) + 1
    _BLANKS[topic or ""] = n
    if n >= ABORT_AFTER:
        print(f"[DuCornWriterTool] 🛑 {n} empty tool calls in a row — "
              f"aborting the agent loop", flush=True)
        raise WriteLoopAborted("an empty tool call", n, blank=True)
    missing = []
    if not (filename or "").strip():
        missing.append("filename")
    if not (content or "").strip():
        missing.append("content")
    return (f"Error: {' and '.join(missing)} came through empty, so there is "
            f"nothing to write. Both must be real strings: the file's name, "
            f"and the file's full text.\\n"
            f"If you have finished writing files, do NOT call this tool "
            f"again — reply with your final answer now.")'''

# ── 3. the signature loses the trap; blanks are refused first ───────────────
DESC_OLD = '''    description: str = (
        "Write text to a file belonging to this product. Args: filename "
        "(relative to the product directory), content, overwrite (default True)."
    )'''

DESC_NEW = '''    description: str = (
        "Write text to a file belonging to this product. Two arguments, both "
        "required, both strings: filename (relative to the product "
        "directory) and content (the file's full text)."
    )'''

RUN_OLD = '''    def _run(self, filename: str, content: str, overwrite: bool = True) -> str:
        if self.topic:'''

RUN_NEW = '''    def _run(self, filename: str, content: str) -> str:
        # `overwrite` used to be a third argument, defaulting to True, that no
        # caller in this stack has ever set. Its whole effect was choosing
        # 'w' over 'x'. What it actually did was give a small model a boolean
        # to get wrong: overwrite='' fails pydantic's bool parsing before
        # _run is even reached, and the model re-sends the identical broken
        # call because the error names a type it does not understand.

        # A blank call is refused BEFORE the jail and BEFORE the ledger.
        # An empty filename is not a path, and an empty write is not a write
        # — recording one as a write is what made the loop guard report three
        # identical writes of a file that was never named.
        if not (filename or "").strip() or not (content or "").strip():
            return blank_call(self.topic, filename, content)

        if self.topic:'''

OPEN_OLD = """            with open(full, 'w' if overwrite else 'x', encoding='utf-8') as f:"""
OPEN_NEW = """            with open(full, 'w', encoding='utf-8') as f:"""

EXISTS_OLD = '''        except FileExistsError:
            return f"Error: file already exists at {filename} (overwrite=False)"
'''
EXISTS_NEW = ''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in (WRITER, LIB):
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

sys.path.insert(0, str(DC / "scripts"))
from patchlib import code_only, py_ok, PatchCheckFailed   # noqa: E402

src = WRITER.read_text(encoding="utf-8")
print("patch_blank_tool_calls\n")

if "def blank_call" in src:
    sys.exit("NOTHING DONE — blank calls are already refused.")

bad = False
for label, anchor in [("WriteLoopAborted.__init__", EXC_OLD),
                      ("reset_writes", LEDGER_OLD),
                      ("the tool description", DESC_OLD),
                      ("the _run signature", RUN_OLD),
                      ("the open() mode", OPEN_OLD),
                      ("the FileExistsError branch", EXISTS_OLD)]:
    n = src.count(anchor)
    print(f"  {'ok ' if n == 1 else '!! '}{label}  ({n} match)")
    bad |= n != 1
if bad:
    sys.exit("\nNOTHING DONE — an anchor did not match exactly once.")

# Removing a parameter is only safe because nothing PASSES it.
#
# "Does anything pass overwrite?" is a question about call sites, and a text
# search cannot answer it. The first version grepped for "overwrite=" across
# ducorn/ and scripts/ and matched FOUR lines inside this very file — the
# paragraph explaining the pydantic failure, the comment in RUN_NEW, the
# error string in EXISTS_OLD, and the grep filter itself. It refused to apply
# a correct patch because it had read its own prose.
#
# That is the sixth time a check in this project has done that, and it is
# why patchlib exists. So: the parse tree. A Call node carrying a keyword
# argument named `overwrite` is a caller. A string that mentions the word is
# not, and neither is the tool's own def or its `'w' if overwrite` line.
offenders = []
for _root in (DC / "ducorn", DC / "scripts"):
    if not _root.is_dir():
        continue
    for _p in sorted(_root.rglob("*.py")):
        _rel = _p.relative_to(DC).as_posix()
        if ".venv" in _rel or ".backup-" in _rel or "/applied/" in _rel:
            continue
        try:
            _t = ast.parse(_p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for _n in ast.walk(_t):
            if isinstance(_n, ast.Call) and any(
                    k.arg == "overwrite" for k in _n.keywords):
                offenders.append(f"{_rel}:{_n.lineno}")
if offenders:
    sys.exit("NOTHING DONE — something passes overwrite as an argument, so "
             "removing it would break a caller:\n  " + "\n  ".join(offenders))
print("  ok  no call site anywhere passes overwrite")

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
shutil.copy2(WRITER, WRITER.with_suffix(f".backup-{TAG}-{stamp}.py"))
WRITER.write_text(src
                  .replace(EXC_OLD, EXC_NEW, 1)
                  .replace(LEDGER_OLD, LEDGER_NEW, 1)
                  .replace(DESC_OLD, DESC_NEW, 1)
                  .replace(RUN_OLD, RUN_NEW, 1)
                  .replace(OPEN_OLD, OPEN_NEW, 1)
                  .replace(EXISTS_OLD, EXISTS_NEW, 1), encoding="utf-8")
print(f"\nwrote DuCornWriterTool.py, backup tagged {TAG}-{stamp}")

after = WRITER.read_text(encoding="utf-8")
try:
    py_ok(after, "DuCornWriterTool.py")
except PatchCheckFailed as e:
    sys.exit(f"⚠️  {e} — restore the backup.")

code = code_only(after)
if "overwrite" in code:
    leftover = [l.strip() for l in code.splitlines() if "overwrite" in l]
    sys.exit(f"⚠️  overwrite survives in code — restore the backup:\n  "
             + "\n  ".join(leftover))
print("verified: it parses, and `overwrite` is gone from the code entirely.")

tree = py_ok(after, "DuCornWriterTool.py")
run = next((n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_run"), None)
if run is None:
    sys.exit("⚠️  _run is gone — restore the backup.")
params = [a.arg for a in run.args.args if a.arg != "self"]
if params != ["filename", "content"]:
    sys.exit(f"⚠️  _run takes {params} — the schema the model sees must be "
             f"exactly filename and content. Restore the backup.")
print(f"          the tool schema is now exactly {params}.")

# ── the blank-call rule, run against the SHIPPED function ───────────────────
# ABORT_AFTER reads os.environ, so the extracted namespace needs os. Seeded
# explicitly rather than exec'ing the whole module — importing it would pull
# in CrewAI, and a verification that needs the framework is one that stops
# running the day the framework moves.
ns: dict = {"os": os}
wanted = ("ABORT_AFTER", "_BLANKS", "WriteLoopAborted", "blank_call")


def _bound(node):
    """
    The name a top-level statement binds, or None.

    AnnAssign is here because `_BLANKS: dict = {}` is an ANNOTATED assignment
    and ast.Assign does not match it. Without this the extraction silently
    missed _BLANKS and this verification would have reported a correct patch
    as broken — the fifth time a check in this project has done that.
    """
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return node.name
    if isinstance(node, ast.Assign) and node.targets:
        return getattr(node.targets[0], "id", None)
    if isinstance(node, ast.AnnAssign):
        return getattr(node.target, "id", None)
    return None


body = [n for n in tree.body if _bound(n) in wanted]
names = {_bound(n) for n in body}
if set(wanted) - names:
    sys.exit(f"⚠️  not at module level: {sorted(set(wanted) - names)} — "
             f"restore the backup.")
exec(compile(ast.Module(body=body, type_ignores=[]), "<shipped>", "exec"), ns)
blank, Aborted = ns["blank_call"], ns["WriteLoopAborted"]
limit = ns["ABORT_AFTER"]

problems = []
ns["_BLANKS"].clear()
first = blank("t", "", "")
if "final answer" not in first:
    problems.append("the refusal does not tell the agent to finish")
if "filename" not in first or "content" not in first:
    problems.append("the refusal does not name what was empty")

# It must abort, and as a BLANK abort, not as a phantom write loop.
ns["_BLANKS"].clear()
hit = None
for i in range(1, limit + 2):
    try:
        blank("t", "", "")
    except Aborted as e:
        hit = e
        break
if hit is None:
    problems.append(f"{limit + 1} blank calls never aborted")
else:
    if not getattr(hit, "blank", False):
        problems.append("the abort is not marked as a blank-call abort")
    if "written identically" in str(hit):
        problems.append("a blank abort still claims a file was written")
    if hit.count != limit:
        problems.append(f"aborted after {hit.count}, expected {limit}")

# Only one field empty is still a blank call, and names the right field.
ns["_BLANKS"].clear()
only_content = blank("t", "report.md", "")
if "content" not in only_content or "filename and" in only_content:
    problems.append("an empty content is misreported")
ns["_BLANKS"].clear()
only_name = blank("t", "", "hello")
if "filename" not in only_name or "and content" in only_name:
    problems.append("an empty filename is misreported")

# Topics are counted apart — one product's blanks must not abort another's.
ns["_BLANKS"].clear()
for _ in range(limit - 1):
    blank("a", "", "")
try:
    blank("b", "", "")
except Aborted:
    problems.append("one topic's blank calls aborted a different topic")

if problems:
    sys.exit("⚠️  restore the backup:\n  " + "\n  ".join(problems))
print(f"          blank calls: refused with instructions, counted per topic, "
      f"abort at {limit} as a blank abort.")

print("""
Two of the three failure modes in that log are gone: the validation error
that the model could not recover from, and the phantom write loops recorded
against an empty filename.

The third — re-sending a file it has genuinely already written — is what
stopped skill 03 on APPROVED_DESIGN.html, and this patch does not touch it.

Recover and resume. What to watch:

  no "arguments validation failed" at all
  any blank call now reads "empty tool calls in a row", never a filename
  💸 still $0.00
""")
