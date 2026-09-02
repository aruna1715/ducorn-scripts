#!/usr/bin/env python3
"""
Give the writer tool a way to say "you are finished".

── THE LOOP ─────────────────────────────────────────────────────────────────

flow_pipeline-test-product-e2e.log, tool calls #6 through #15:

    Tool: du_corn_writer_tool
    Args: {'filename': 'docs/...-PRD.md', 'content': '# pipeline-test-product-e2e...'}
    → Content successfully written to docs/pipeline-test-product-e2e-PRD.md
    Tool: du_corn_writer_tool
    Args: {'filename': 'docs/...-PRD.md', 'content': '# pipeline-test-product-e2e...'}
    → Content successfully written to docs/pipeline-test-product-e2e-PRD.md
    ... ten times, then max_iter, then the 600s timeout.

The task says "one write, complete, first time". The tool says "Content
successfully written". Neither of those is a signal that the work is DONE —
the agent gets an acknowledgement and an empty next turn, and writing the file
again is the most obviously available action. A stronger model reads the
instruction and stops. llama3.1 does not, and llama3.1 is what every test run
uses.

This is the same shape as the last several: an instruction that is correct and
a mechanism that never enforces it. The enforcement belongs in the tool,
because the tool is the only thing that knows the file is already written.

── TWO CHANGES ──────────────────────────────────────────────────────────────

1. The success message ends the task rather than acknowledging a step:

       Saved docs/x-PRD.md (4,182 bytes). This is the deliverable and it is
       now on disk. Do NOT write it again — reply with your final answer.

2. A repeat write of IDENTICAL content is refused, and the refusal says so
   plainly, with the count. A repeat write of DIFFERENT content is allowed —
   revising a draft is legitimate — but the message says how many times the
   file has been rewritten and tells the agent to finish.

Deliberately not a hard cap. A cap would turn a loop into a crash; the point is
to end the turn, not to kill the stage. The runaway guard remains the LiteLLM
per-key budget.

Also writes scripts/test_writer_done.py — the tests run the tool, they do not
read it.
"""
import ast
import shutil
import sys
from datetime import datetime
from pathlib import Path

TOOL = Path("/Users/ducorn/DC/ducorn/tools/DuCornWriterTool.py")
TEST = Path("/Users/ducorn/DC/scripts/test_writer_done.py")

s = TOOL.read_text(encoding="utf-8")
if "_WRITES" in s:
    sys.exit("Already patched — the writer tracks its writes.")


def swap(label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {text.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    return text.replace(old, new, 1)


# ── the ledger ───────────────────────────────────────────────────────────────
s = swap("ledger", s, '''class DuCornWriterTool(BaseTool):''',
         '''# ── write ledger ─────────────────────────────────────────────────────────────
# What has been written this process, so the tool can tell an agent it is done.
# One pipeline phase is one process, so process scope is exactly run scope.
_WRITES: dict = {}


def reset_writes():
    """Clear the ledger. For tests, and for anything that reuses the process."""
    _WRITES.clear()


def writes_for(topic, filename) -> list:
    """The content hashes written to this file so far, oldest first."""
    return list(_WRITES.get((topic or "", filename), []))


def _remember(topic, filename, content):
    """Record a write; return (times_written_before, was_identical_before)."""
    import hashlib
    key = (topic or "", filename)
    digest = hashlib.sha1(content.encode("utf-8", "replace")).hexdigest()
    seen = _WRITES.setdefault(key, [])
    repeat = digest in seen
    before = len(seen)
    seen.append(digest)
    return before, repeat


class DuCornWriterTool(BaseTool):''')

# ── the messages ─────────────────────────────────────────────────────────────
s = swap("success message", s, '''        full.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(full, 'w' if overwrite else 'x', encoding='utf-8') as f:
                f.write(content)
            return f"Content successfully written to {filename}"''',
         '''        before, identical = _remember(self.topic, filename, content)

        if identical:
            # The file already holds exactly this. Writing it again cannot
            # change anything, and an agent that does it once will do it until
            # max_iter — ten identical writes of one PRD is what this is for.
            # Refused BEFORE the write, so a loop costs no disk churn.
            return (f"STOP — {filename} already contains exactly this content. "
                    f"You have now sent it {before + 1} times. The file is "
                    f"saved and the task is complete. Do not call this tool "
                    f"again; reply with your final answer.")

        full.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(full, 'w' if overwrite else 'x', encoding='utf-8') as f:
                f.write(content)
            # An acknowledgement is not a finish line. "Content successfully
            # written" left the agent with a done step and an empty next turn,
            # and writing the file again was the most available action.
            done = (f"Saved {filename} ({len(content):,} bytes). This is the "
                    f"deliverable and it is now on disk. Do NOT write it again "
                    f"— reply with your final answer.")
            if before:
                done = (f"Saved {filename} ({len(content):,} bytes), replacing "
                        f"what you wrote before — that is {before + 1} versions "
                        f"of this file in one task. It is on disk now. Stop "
                        f"revising and reply with your final answer.")
            return done''')

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = TOOL.with_name(f"DuCornWriterTool.backup-done-{stamp}.py")
shutil.copy2(TOOL, backup)
TOOL.write_text(s, encoding="utf-8")

try:
    ast.parse(s)
except SyntaxError as e:
    shutil.copy2(backup, TOOL)
    sys.exit(f"SYNTAX ERROR ({e}) — reverted from {backup}")

TEST.write_text('''#!/usr/bin/env python3
"""
The writer tool ends the task instead of acknowledging a step.

    cd ~/DC/ducorn && .venv/bin/python ../scripts/test_writer_done.py

Every check here RUNS the tool. The loop this covers survived a suite that
string-matched the source, because the source was correct — it said "one write,
complete, first time" — and nothing enforced it.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/Users/ducorn/DC/ducorn")

from tools.DuCornWriterTool import DuCornWriterTool, reset_writes, writes_for  # noqa

passed, failed = [], []


def test(name):
    def deco(fn):
        try:
            fn()
            print(f"  ok   {name}")
            passed.append(name)
        except AssertionError as e:
            print(f"  FAIL {name}\\n         {e}")
            failed.append(name)
        except Exception as e:
            print(f"  FAIL {name}\\n         {type(e).__name__}: {e}")
            failed.append(name)
        return fn
    return deco


SLUG = "zz-writer-done-canary"
NAME = f"docs/{SLUG}-PRD.md"
PRD = Path("/Users/ducorn/DC/ducorn-products") / NAME


def _tool():
    reset_writes()
    PRD.unlink(missing_ok=True)
    return DuCornWriterTool(topic=SLUG)


print("\\n── the first write finishes the job ────────────────────────────────")


@test("a successful write tells the agent to stop")
def _():
    t = _tool()
    out = t._run(NAME, "# canary\\n\\nBody text long enough to be a document.\\n")
    assert PRD.exists(), "nothing was written"
    low = out.lower()
    assert "final answer" in low, (
        f"the success message gives the agent no finish line: {out!r}")
    assert "do not write it again" in low, (
        f"the success message does not tell the agent to stop: {out!r}")
    PRD.unlink(missing_ok=True)


print("\\n── the loop that cost a 600s timeout ───────────────────────────────")


@test("an identical repeat write is refused, not acknowledged")
def _():
    # 1 Sept: SAGE sent the same PRD ten times, got "Content successfully
    # written" ten times, and ran out of iterations.
    t = _tool()
    body = "# canary\\n\\nIdentical content sent twice.\\n"
    first = t._run(NAME, body)
    second = t._run(NAME, body)
    assert "final answer" in first.lower(), f"first write: {first!r}"
    assert second.startswith("STOP"), (
        f"the second identical write was accepted again: {second!r}")
    assert "2 times" in second, f"the refusal does not say how many: {second!r}"
    PRD.unlink(missing_ok=True)


@test("ten identical writes are refused nine times, and the count is right")
def _():
    t = _tool()
    body = "# canary\\n\\nSent ten times, as it was on 1 September.\\n"
    outs = [t._run(NAME, body) for _ in range(10)]
    stops = [o for o in outs if o.startswith("STOP")]
    assert len(stops) == 9, f"expected 9 refusals, got {len(stops)}"
    assert "10 times" in stops[-1], f"last refusal: {stops[-1]!r}"
    PRD.unlink(missing_ok=True)


print("\\n── revision is still allowed ───────────────────────────────────────")


@test("a genuine rewrite goes through, and says it is a rewrite")
def _():
    t = _tool()
    t._run(NAME, "# canary\\n\\nfirst draft\\n")
    out = t._run(NAME, "# canary\\n\\nsecond draft, materially different\\n")
    assert not out.startswith("STOP"), f"a real revision was refused: {out!r}"
    assert "second draft" in PRD.read_text(), "the revision did not reach disk"
    assert "2 versions" in out, f"the message does not count versions: {out!r}"
    PRD.unlink(missing_ok=True)


@test("the ledger separates files, so one file cannot block another")
def _():
    t = _tool()
    other = f"docs/{SLUG}-QA.md"
    body = "# canary\\n\\nsame text, two different files\\n"
    a = t._run(NAME, body)
    b = t._run(other, body)
    assert not b.startswith("STOP"), (
        f"writing a DIFFERENT file was refused because the text matched: {b!r}")
    assert len(writes_for(SLUG, NAME)) == 1
    assert len(writes_for(SLUG, other)) == 1
    PRD.unlink(missing_ok=True)
    (Path("/Users/ducorn/DC/ducorn-products") / other).unlink(missing_ok=True)


@test("a refused repeat does not touch the file on disk")
def _():
    t = _tool()
    body = "# canary\\n\\noriginal\\n"
    t._run(NAME, body)
    mtime = PRD.stat().st_mtime_ns
    t._run(NAME, body)
    assert PRD.stat().st_mtime_ns == mtime, (
        "the refused write still rewrote the file — a loop should cost nothing")
    PRD.unlink(missing_ok=True)


print()
print(f"{len(passed)} passed, {len(failed)} failed")
if failed:
    print("FAILED: " + ", ".join(failed))
    sys.exit(1)
print("the writer can end a task")
''', encoding="utf-8")

print(f"applied: {TOOL.name} — write ledger, terminal success message, "
      f"identical-repeat refusal")
print(f"created: {TEST}")
print(f"backup:  {backup.name}")
print()
print("Run the new tests:")
print("  cd ~/DC/ducorn && .venv/bin/python ../scripts/test_writer_done.py")
