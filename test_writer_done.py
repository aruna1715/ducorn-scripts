#!/usr/bin/env python3
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

from tools.DuCornWriterTool import (  # noqa
    DuCornWriterTool, WriteLoopAborted, reset_writes, writes_for, ABORT_AFTER)

passed, failed = [], []


def test(name):
    def deco(fn):
        try:
            fn()
            print(f"  ok   {name}")
            passed.append(name)
        except AssertionError as e:
            print(f"  FAIL {name}\n         {e}")
            failed.append(name)
        except Exception as e:
            print(f"  FAIL {name}\n         {type(e).__name__}: {e}")
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


print("\n── the first write finishes the job ────────────────────────────────")


@test("a successful write tells the agent to stop")
def _():
    t = _tool()
    out = t._run(NAME, "# canary\n\nBody text long enough to be a document.\n")
    assert PRD.exists(), "nothing was written"
    low = out.lower()
    assert "final answer" in low, (
        f"the success message gives the agent no finish line: {out!r}")
    assert "do not write it again" in low, (
        f"the success message does not tell the agent to stop: {out!r}")
    PRD.unlink(missing_ok=True)


print("\n── the loop that cost a 600s timeout ───────────────────────────────")


@test("an identical repeat write is refused, not acknowledged")
def _():
    # 1 Sept: SAGE sent the same PRD ten times, got "Content successfully
    # written" ten times, and ran out of iterations.
    t = _tool()
    body = "# canary\n\nIdentical content sent twice.\n"
    first = t._run(NAME, body)
    second = t._run(NAME, body)
    assert "final answer" in first.lower(), f"first write: {first!r}"
    assert second.startswith("STOP"), (
        f"the second identical write was accepted again: {second!r}")
    assert "2 times" in second, f"the refusal does not say how many: {second!r}"
    PRD.unlink(missing_ok=True)


@test("an agent that ignores the refusal is stopped by the tool")
def _():
    # llama3.1 read "STOP ... do not call this tool again" and called it again,
    # twice. The message is kept because a capable model does stop there, but
    # there has to be something underneath it for the model that does not.
    t = _tool()
    body = "# canary\n\nSent until the tool stops us.\n"
    outs = []
    try:
        for _ in range(10):
            outs.append(t._run(NAME, body))
    except WriteLoopAborted as loop:
        assert loop.filename == NAME, f"wrong file named: {loop.filename!r}"
        assert loop.count == ABORT_AFTER, (
            f"aborted at {loop.count}, expected {ABORT_AFTER}")
        assert len(outs) == ABORT_AFTER - 1, (
            f"{len(outs)} calls returned before the abort, expected "
            f"{ABORT_AFTER - 1}")
        assert outs[-1].startswith("STOP"), (
            f"the message should be tried before the mechanism: {outs[-1]!r}")
        PRD.unlink(missing_ok=True)
        return
    raise AssertionError(
        f"{len(outs)} identical writes and no abort — the loop is unbounded "
        f"again")


@test("the abort is a BaseException, so CrewAI cannot swallow it")
def _():
    # CrewAI catches Exception around a tool call and hands the error back to
    # the agent as observation text — which for a looping model is just another
    # turn in the loop. This has to pass through.
    assert issubclass(WriteLoopAborted, BaseException), "not a BaseException"
    assert not issubclass(WriteLoopAborted, Exception), (
        "WriteLoopAborted subclasses Exception, so CrewAI will catch it and "
        "feed it back to the agent — the loop continues")


print("\n── revision is still allowed ───────────────────────────────────────")


@test("a genuine rewrite goes through, and says it is a rewrite")
def _():
    t = _tool()
    t._run(NAME, "# canary\n\nfirst draft\n")
    out = t._run(NAME, "# canary\n\nsecond draft, materially different\n")
    assert not out.startswith("STOP"), f"a real revision was refused: {out!r}"
    assert "second draft" in PRD.read_text(), "the revision did not reach disk"
    assert "2 versions" in out, f"the message does not count versions: {out!r}"
    PRD.unlink(missing_ok=True)


@test("the ledger separates files, so one file cannot block another")
def _():
    t = _tool()
    other = f"docs/{SLUG}-QA.md"
    body = "# canary\n\nsame text, two different files\n"
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
    body = "# canary\n\noriginal\n"
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
