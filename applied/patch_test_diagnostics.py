#!/usr/bin/env python3
"""
Make the timing-out run leave evidence behind, and name the router.

── WHY I COULD NOT ANSWER YOUR QUESTION ─────────────────────────────────────

The last e2e timeout produced a log whose final segment is 117 lines: the
banner, the model line, the brief length, and then nothing. Everything CrewAI
printed after that was sitting in a stdout buffer when subprocess.run killed
the process, and buffers do not survive a kill.

So the one run I most needed to read is the one that recorded least, and I have
now given you three explanations for this timeout built on evidence from
earlier runs. Two changes so that stops happening.

1. PYTHONUNBUFFERED=1 on the flow subprocess. Python line-buffers to a
   terminal and block-buffers to a pipe, which is exactly backwards for a job
   whose log is only interesting when it gets killed.

2. The timeout report reads router.log as well as the flow log. The actual
   cause this time was not in the flow log at all:

       [DuCorn Router] upstream timeout:
       "POST /v1/chat/completions HTTP/1.1" 504 Gateway Timeout

   Two of those at the old 300-second budget is the entire 600-second test.
   The report now counts 504s and slow calls in the window, and counts writer
   calls so a repeat-write loop is named in the first line rather than found
   ten minutes later.

Pair this with patch_router_timing.py — that one shortens the budget and
starts writing the ⏱ lines this report reads.
"""
import ast
import shutil
import sys
from datetime import datetime
from pathlib import Path

PIPE = Path("/Users/ducorn/DC/ducorn/test_pipeline.py")
p = PIPE.read_text(encoding="utf-8")

if "_run_flow" not in p:
    sys.exit("patch_test_brief.py has not been applied — _run_flow is missing. "
             "NOTHING WRITTEN.")
if "router.log" in p:
    sys.exit("Already patched — the timeout report reads router.log.")

OLD = '''    slug = argv[2]
    try:
        return subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout, env=env,
                              cwd="/Users/ducorn/DC/ducorn")
    except subprocess.TimeoutExpired as e:
        log = Path("/Users/ducorn/DC/logs") / f"flow_{slug}.log"
        tail, blocked = "(no log)", 0
        if log.exists():
            text = log.read_text(errors="replace")
            blocked = text.count("BLOCKED:")
            tail = "\\n".join(text.splitlines()[-25:])
        raise AssertionError(
            f"{slug} did not finish in {timeout}s.\\n"
            f"  blocked tool calls in the log: {blocked}"
            f"{'  ← the agent is hunting for a file that does not exist' if blocked > 3 else ''}\\n"
            f"  log: {log}\\n"
            f"  --- last 25 lines ---\\n{tail}") from e'''

NEW = '''    import time as _time
    slug = argv[2]
    logs = Path("/Users/ducorn/DC/logs")
    log = logs / f"flow_{slug}.log"
    router = logs / "router.log"

    # Python block-buffers stdout to a pipe, so a killed run flushes nothing —
    # and the killed run is the only one whose log anyone wants to read. The
    # last timeout left a 117-line segment that ended before the first tool
    # call.
    env = {**(env or {}), "PYTHONUNBUFFERED": "1"}

    started_at = _time.time()
    try:
        return subprocess.run(argv, capture_output=True, text=True,
                              timeout=timeout, env=env,
                              cwd="/Users/ducorn/DC/ducorn")
    except subprocess.TimeoutExpired as e:
        lines = []

        blocked = writes = 0
        tail = "(no log)"
        if log.exists():
            text = log.read_text(errors="replace")
            blocked = text.count("BLOCKED:")
            writes = text.count("du_corn_writer_tool")
            tail = "\\n".join(text.splitlines()[-25:])

        if blocked > 3:
            lines.append(f"  {blocked} blocked tool calls — the agent is hunting "
                         f"for a file that does not exist")
        if writes > 6:
            lines.append(f"  {writes} writer calls — it is rewriting the same "
                         f"document instead of finishing")

        # The cause of the 1 Sept timeout was in NEITHER the flow log nor the
        # test output: the router was waiting 300s per stalled Ollama call and
        # returning 504, so two stalls consumed the whole budget.
        if router.exists():
            with open(router, "rb") as fh:
                fh.seek(0, 2)
                fh.seek(max(0, fh.tell() - 400_000))
                rtext = fh.read().decode("utf-8", "replace")
            gateways = rtext.count("504 Gateway Timeout")
            upstream = rtext.count("upstream timeout")
            slow = rtext.count("⏱ SLOW")
            if upstream or gateways:
                lines.append(f"  router: {upstream} upstream timeouts, "
                             f"{gateways} 504s — the model calls are stalling, "
                             f"not looping")
            if slow:
                lines.append(f"  router: {slow} slow calls logged")
            if not (upstream or gateways or slow):
                lines.append("  router: no timeouts or slow calls — the model "
                             "is answering, so the time is going somewhere else")

        if not lines:
            lines.append("  nothing obvious in the logs — read the tail below")

        raise AssertionError(
            f"{slug} did not finish in {timeout}s "
            f"(ran {_time.time() - started_at:.0f}s).\\n"
            + "\\n".join(lines)
            + f"\\n  log: {log}\\n  --- last 25 lines ---\\n{tail}") from e'''

if p.count(OLD) != 1:
    sys.exit(f"ANCHOR MISS: found {p.count(OLD)} copies of _run_flow's body, "
             f"expected 1. NOTHING WRITTEN.")

p = p.replace(OLD, NEW, 1)

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = PIPE.with_name(f"test_pipeline.backup-diag-{stamp}.py")
shutil.copy2(PIPE, backup)
PIPE.write_text(p, encoding="utf-8")

try:
    ast.parse(p)
except SyntaxError as e:
    shutil.copy2(backup, PIPE)
    sys.exit(f"SYNTAX ERROR ({e}) — reverted from {backup}")

print("applied: unbuffered flow output; timeout report reads router.log too")
print(f"backup:  {backup.name}")
