#!/usr/bin/env python3
"""
Break the write loop with a mechanism, because the message did not work.

── WHAT JUST HAPPENED ───────────────────────────────────────────────────────

    STOP — docs/...-PRD.md already contains exactly this content. You have now
    sent it 4 times. The file is saved and the task is complete. Do not call
    this tool again; reply with your final answer.

    Tool Execution Started (#5)
    Tool: du_corn_writer_tool
    Args: {'filename': 'docs/...-PRD.md', 'content': "# pipeline-test-product-e2e..."}

    STOP — ... You have now sent it 5 times ...

llama3.1 read the refusal and called the tool again. Then again.

That is my fault twice over. I wrote in the last patch: "Deliberately not a
hard cap. A cap would turn a loop into a crash; the point is to end the turn."
Which sounds reasonable and is wrong — a refusal message is an INSTRUCTION, and
the whole lesson of this week is that an instruction with no mechanism behind
it does not hold. I diagnosed that failure mode correctly in the writer's own
docstring and then shipped another instance of it.

The message is still worth keeping: a stronger model does stop on the first
refusal, and that is the cheap path. But there has to be something underneath
it for the model that does not.

── THE MECHANISM ────────────────────────────────────────────────────────────

After three identical sends, the tool raises WriteLoopAborted, which is a
BaseException rather than an Exception — deliberately. CrewAI catches Exception
around tool calls and hands the error back to the agent as observation text,
which for a looping model is simply another turn in the loop. BaseException
passes through the framework and out of crew.kickoff(), where our own code can
catch it.

And catching it is safe, which is the part that makes this the right shape
rather than a crash: the abort can only fire AFTER a successful write, so the
deliverable is already on disk. Breaking the loop loses nothing but the
repetition.

    write 1   file saved, "reply with your final answer"
    write 2   identical → refused with the STOP message
    write 3   identical → WriteLoopAborted, caught, stage continues

All three kickoff sites that hand out this tool learn to catch it:

    node_research      the PRD is written; carry on to the type check and gate
    node_launch        the announcement is written; carry on to gate 4
    skill_runner       returns a plain marker instead of the crew's output

skill_runner is the one place where an abort is not free: skill 06 parses a
VERDICT line out of the crew's answer, and an aborted run has no answer to
parse. That skill will therefore fail — visibly, with a message naming the
loop, which is the honest outcome. A QA verdict invented after the agent lost
the thread is worse than a failure.

Threshold is DUCORN_WRITE_ABORT_AFTER, default 3.

── COST, IF YOU WANT TO WEIGH IT ────────────────────────────────────────────

The loop is survivable on Ollama: max_iter=15 ends it, at roughly ten seconds
an iteration, so a looping research stage wastes about a hundred seconds and
still produces a correct PRD. On Sonnet the same fifteen iterations are about
$2.20 for a stage that should cost sixty cents, and a longer PRD costs more per
iteration. That is the reason to fix it before the paid E2E rather than after.
"""
import ast
import shutil
import sys
from datetime import datetime
from pathlib import Path

TOOL = Path("/Users/ducorn/DC/ducorn/tools/DuCornWriterTool.py")
FLOW = Path("/Users/ducorn/DC/ducorn/flows/langgraph_flow.py")
SKILL = Path("/Users/ducorn/DC/ducorn/skill_runner.py")

edits, applied = [], []


def swap(path, label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{path.name}:{label}]: found {text.count(old)}, "
                 f"expected 1. NOTHING WRITTEN.")
    applied.append(f"{path.name}:{label}")
    return text.replace(old, new, 1)


# ═══════════════════════════════════════════════════════════════════════════
t = TOOL.read_text(encoding="utf-8")
if "WriteLoopAborted" in t:
    sys.exit("Already patched — the writer can abort a loop.")
if "_WRITES" not in t:
    sys.exit("Apply patch_writer_done.py first — this builds on its ledger. "
             "NOTHING WRITTEN.")

t = swap(TOOL, "exception", t, '''# ── write ledger ──''',
         '''class WriteLoopAborted(BaseException):
    """
    Raised to break an agent out of a write loop.

    A BaseException, not an Exception, and that is the whole point: CrewAI
    catches Exception around a tool call and feeds the error back to the agent
    as observation text, which for a looping model is just another turn in the
    loop. This has to pass through the framework so our own code can catch it.

    Safe to catch and continue from: the abort can only fire after a
    successful write, so the deliverable is already on disk. Only the
    repetition is lost.
    """

    def __init__(self, filename, count):
        self.filename = filename
        self.count = count
        super().__init__(f"{filename} was written identically {count} times; "
                         f"the agent ignored the refusal, so the tool stopped "
                         f"it. The file on disk is complete.")


# How many identical sends before the mechanism takes over from the message.
# A capable model stops at the first refusal; llama3.1 sent it five times.
ABORT_AFTER = int(os.environ.get("DUCORN_WRITE_ABORT_AFTER", "3"))


# ── write ledger ──''')

t = swap(TOOL, "abort", t, '''        if identical:''',
         '''        if identical and before + 1 >= ABORT_AFTER:
            # The message was tried and ignored. Stop asking.
            print(f"[DuCornWriterTool] 🛑 {filename} sent identically "
                  f"{before + 1} times — aborting the agent loop", flush=True)
            raise WriteLoopAborted(filename, before + 1)

        if identical:''')
edits.append((TOOL, t))

# ═══════════════════════════════════════════════════════════════════════════
f = FLOW.read_text(encoding="utf-8")
if "WriteLoopAborted" in f:
    sys.exit("langgraph_flow already catches WriteLoopAborted.")

f = swap(FLOW, "research", f, '''        crew = Crew(agents=[sage], tasks=[task], verbose=True)
        result = crew.kickoff()''',
         '''        from tools.DuCornWriterTool import WriteLoopAborted

        crew = Crew(agents=[sage], tasks=[task], verbose=True)
        try:
            result = crew.kickoff()
        except WriteLoopAborted as loop:
            # The PRD is on disk — the abort only fires after a write lands.
            # Everything below reads the file, not the crew's answer, so this
            # loses nothing except the repetition.
            print(f"🛑 {loop}")
            result = None''')

f = swap(FLOW, "launch", f, '''        crew = Crew(agents=[nova], tasks=[task], verbose=True)
        crew.kickoff()''',
         '''        from tools.DuCornWriterTool import WriteLoopAborted

        crew = Crew(agents=[nova], tasks=[task], verbose=True)
        try:
            crew.kickoff()
        except WriteLoopAborted as loop:
            print(f"🛑 {loop}")''')
edits.append((FLOW, f))

# ═══════════════════════════════════════════════════════════════════════════
sk = SKILL.read_text(encoding="utf-8")
if "WriteLoopAborted" in sk:
    sys.exit("skill_runner already catches WriteLoopAborted.")

sk = swap(SKILL, "kickoff", sk, '''    crew = Crew(agents=[agent], tasks=[task], verbose=True)
    result = crew.kickoff()
    return str(result)''',
         '''    from tools.DuCornWriterTool import WriteLoopAborted

    crew = Crew(agents=[agent], tasks=[task], verbose=True)
    try:
        result = crew.kickoff()
    except WriteLoopAborted as loop:
        # Unlike the flow nodes, this one costs something: skill 06 parses a
        # VERDICT line out of what the crew returns, and an aborted run has
        # nothing to parse, so that skill will fail. It should. A QA verdict
        # invented after the agent lost the thread is worse than a failure.
        print(f"🛑 {loop}", flush=True)
        return (f"WRITE LOOP ABORTED — the agent sent {loop.filename} "
                f"identically {loop.count} times and ignored the refusal. Its "
                f"file output is on disk and complete; it produced no final "
                f"answer, so any verdict this skill was meant to return is "
                f"missing.")
    return str(result)''')
edits.append((SKILL, sk))

# ═══════════════════════════════════════════════════════════════════════════
# The tests written by patch_writer_done.py assert nine refusals out of ten
# identical writes. With the abort at three, the tenth never happens — and the
# BaseException would escape the harness's `except Exception` and kill the whole
# script rather than failing one test. Update them in the same patch.
TEST = Path("/Users/ducorn/DC/scripts/test_writer_done.py")
if not TEST.exists():
    sys.exit(f"{TEST} is missing — apply patch_writer_done.py first. "
             f"NOTHING WRITTEN.")
te = TEST.read_text(encoding="utf-8")

te = swap(TEST, "import", te,
          "from tools.DuCornWriterTool import DuCornWriterTool, reset_writes, writes_for  # noqa",
          "from tools.DuCornWriterTool import (  # noqa\n"
          "    DuCornWriterTool, WriteLoopAborted, reset_writes, writes_for, ABORT_AFTER)")

te = swap(TEST, "abort test", te,
          '''@test("ten identical writes are refused nine times, and the count is right")
def _():
    t = _tool()
    body = "# canary\\n\\nSent ten times, as it was on 1 September.\\n"
    outs = [t._run(NAME, body) for _ in range(10)]
    stops = [o for o in outs if o.startswith("STOP")]
    assert len(stops) == 9, f"expected 9 refusals, got {len(stops)}"
    assert "10 times" in stops[-1], f"last refusal: {stops[-1]!r}"
    PRD.unlink(missing_ok=True)''',
          '''@test("an agent that ignores the refusal is stopped by the tool")
def _():
    # llama3.1 read "STOP ... do not call this tool again" and called it again,
    # twice. The message is kept because a capable model does stop there, but
    # there has to be something underneath it for the model that does not.
    t = _tool()
    body = "# canary\\n\\nSent until the tool stops us.\\n"
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
        "feed it back to the agent — the loop continues")''')

edits.append((TEST, te))

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backups = []
for path, text in edits:
    backup = path.with_name(f"{path.stem}.backup-abort-{stamp}{path.suffix}")
    shutil.copy2(path, backup)
    backups.append((path, backup))
    path.write_text(text, encoding="utf-8")

for path, backup in backups:
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        for p, b in backups:
            shutil.copy2(b, p)
        sys.exit(f"SYNTAX ERROR in {path.name} ({e}) — all files reverted")

# Every site that hands out the writer must catch the abort, or a loop there
# becomes an uncaught BaseException that kills the process.
handed_out = FLOW.read_text().count("DuCornWriterTool(") \
           + SKILL.read_text().count("DuCornWriterTool(")
caught = FLOW.read_text().count("except WriteLoopAborted") \
       + SKILL.read_text().count("except WriteLoopAborted")
if caught < handed_out:
    for p, b in backups:
        shutil.copy2(b, p)
    sys.exit(f"{handed_out} places hand out the writer but only {caught} catch "
             f"the abort — an uncaught BaseException would kill the run. "
             f"All files reverted.")

print("applied: " + ", ".join(applied))
print(f"         {handed_out} writer sites, {caught} catching the abort")
print(f"backups: *.backup-abort-{stamp}.*")
print()
print("The sequence is now:")
print("  write 1   saved, 'reply with your final answer'")
print("  write 2   identical → refused with the STOP message")
print("  write 3   identical → loop aborted, stage carries on")
print()
print("Re-run the writer tests, which cover the refusal path:")
print("  cd ~/DC/ducorn && .venv/bin/python ../scripts/test_writer_done.py")
