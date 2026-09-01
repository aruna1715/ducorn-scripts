#!/usr/bin/env python3
"""
Stop API restarts from killing running pipelines.

WHAT HAPPENED
-------------
1 Sept, ducorn-spend-view. The API was restarted to pick up a patch while a
pipeline was mid-research. Thirty-six seconds later the run died with no
traceback and no Gate 1 approval — SIGKILL leaves neither.

    API restarted    11:19:25
    last model call  11:20:01
    gap              ~36s = launchd's SIGTERM-then-SIGKILL grace period

THE DEFECT
----------
The API starts pipelines with:

    subprocess.Popen([python, "-u", "langgraph_flow.py", slug, ...])

No start_new_session, no setsid. The child stays in the API's process group,
so it is part of the launchd job. `launchctl kickstart -k com.ducorn.api`
terminates the job — and everything in it.

Four Popen call sites, none detached. So every API restart has always killed
every in-flight pipeline: every deploy, every config change, every kickstart.
It went unnoticed because nobody had restarted the API during a run before.

A pipeline is a long-running job that outlives the request that started it.
Coupling its lifetime to the web server's is wrong independently of who
triggered the restart.

THE FIX
-------
start_new_session=True on every pipeline Popen. The child gets its own session
and process group, so signals sent to the API's job do not reach it.

This does NOT make pipelines unkillable: scripts/delete_run.py and
POST /pipeline/kill/{slug} both find the process by name and signal it
directly. Stopping a run stays deliberate rather than a side effect of
restarting a web server.
"""
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

API = Path("/Users/ducorn/DC/ducorn-products/products/ducorn-activity-api/main.py")
s = API.read_text(encoding="utf-8")

if "start_new_session" in s:
    sys.exit("Already patched — start_new_session is present.")

lines = s.splitlines(keepends=True)
sites = [i for i, l in enumerate(lines) if l.strip() == "subprocess.Popen("]
if len(sites) != 4:
    sys.exit(f"ANCHOR MISS: expected 4 `subprocess.Popen(` call sites, "
             f"found {len(sites)}. NOTHING WRITTEN.")

# Insert the argument just before each call's closing paren. Walk forward from
# the call site tracking depth, so a nested call or a dict argument cannot be
# mistaken for the end of the call.
inserted = 0
for start in reversed(sites):           # reversed: later edits do not shift earlier indices
    depth = 0
    for i in range(start, min(start + 40, len(lines))):
        depth += lines[i].count("(") - lines[i].count(")")
        if depth == 0 and i > start:
            indent = " " * (len(lines[start]) - len(lines[start].lstrip()) + 4)
            # The last argument may have no trailing comma — two of these four
            # calls end `stderr=subprocess.STDOUT` with none. Appending a kwarg
            # after that is a syntax error, so add the comma first.
            j = i - 1
            while j > start and not lines[j].strip():
                j -= 1
            stripped = lines[j].rstrip()
            if stripped and not stripped.endswith((",", "(")):
                lines[j] = stripped + ",\n"
            lines.insert(i, indent +
                         "# Detached: a pipeline outlives the request that "
                         "started it, and must\n" + indent +
                         "# survive an API restart. Without this the child "
                         "shares the API's\n" + indent +
                         "# process group and launchctl kickstart -k kills it "
                         "mid-run.\n" + indent +
                         "start_new_session=True,\n")
            inserted += 1
            break
    else:
        sys.exit(f"ANCHOR MISS: could not find the end of the Popen call "
                 f"starting at line {start + 1}. NOTHING WRITTEN.")

if inserted != 4:
    sys.exit(f"Only {inserted}/4 call sites patched. NOTHING WRITTEN.")

s = "".join(lines)

backup = API.with_name(f"main.backup-detach-{datetime.now():%Y%m%d-%H%M%S}.py")
shutil.copy2(API, backup)
API.write_text(s, encoding="utf-8")

import ast
try:
    ast.parse(s)
except SyntaxError as e:
    shutil.copy2(backup, API)
    sys.exit(f"SYNTAX ERROR ({e}) — reverted from {backup}")

print(f"applied: start_new_session=True at {inserted} Popen call sites")
print(f"backup:  {backup}")
print()
print("Restart the API once more to load this — after that, restarts are safe.")
