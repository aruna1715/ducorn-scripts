#!/usr/bin/env python3
"""
Make gate_2 actually pause, and stop max_iter from crashing on Anthropic.

── 1. GATE 2 DID NOT PAUSE ──────────────────────────────────────────────────

    [gate_2] phase=gate_2 status=awaiting_approval
    🔨 REX: Building 'ducorn-spend-view'          ← without waiting

_stream_until_pause decides whether to stop:

    gate_nodes = {"gate_1", "gate_3", "gate_4"}
    if status == "awaiting_approval" and node in gate_nodes:
        return state

gate_2 is not in that set. I added the node yesterday and never added it here,
so the gate raised three approvals, set awaiting_approval, and the loop carried
on into build. The design gate was decorative in the most expensive way: it did
all the work of pausing and then did not pause.

The fix is not to add "gate_2" to the set. A gate is any node whose name starts
with gate_, and that is derivable — so the next gate someone adds works without
anyone remembering this line exists. This was the fifth hardcoded phase list in
this codebase and the fourth to be wrong.

── 2. max_iter IS A CRASH, NOT A LIMIT, ON ANTHROPIC ────────────────────────

    handle_max_iterations_exceeded → llm.call(...)
    → AnthropicException: This model does not support assistant message
      prefill. The conversation must end with a user message.

When an agent exceeds max_iter, CrewAI forces a final answer by prefilling an
assistant message. Anthropic rejects that with a 400. So exceeding max_iter on
Claude is not a graceful truncation — it kills the stage.

skill_runner had max_iter=3, which is barely enough for a skill that reads a
PRD, thinks, and writes a file. It was survivable while everything ran on
llama3.1 through Ollama, which accepts prefill. The first real Claude run hit
it immediately.

This also reframes the limits I set this morning. I set max_iter=8 on research
and 6 on launch and called it runaway protection. It is not: on Anthropic it is
a landmine. The runaway guard is the LiteLLM per-key budget, which refuses the
call and is already in place. max_iter should be set high enough that normal
work never reaches it.

    skill_runner   3 → 15
    node_research  8 → 15
    node_launch    6 → 10
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

FLOW = Path("/Users/ducorn/DC/ducorn/flows/langgraph_flow.py")
SKILL = Path("/Users/ducorn/DC/ducorn/skill_runner.py")

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
edits, applied = [], []


def swap(path, label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{path.name}:{label}]: found {text.count(old)}, "
                 f"expected 1. NOTHING WRITTEN.")
    applied.append(f"{path.name}:{label}")
    return text.replace(old, new, 1)


f = FLOW.read_text(encoding="utf-8")
if 'node.startswith("gate_")' in f:
    sys.exit("Already patched — the gate check is derived.")

# ── gate detection derives from the name ─────────────────────────────────────
f = swap(FLOW, "gate pause", f,
'''            gate_nodes = {"gate_1", "gate_3", "gate_4"}
            if status == "awaiting_approval" and node in gate_nodes:''',
'''            # A gate is any node named gate_*. Derived, not listed: the set
            # here used to be {"gate_1", "gate_3", "gate_4"} and gate_2 was
            # added to the graph without anyone updating it, so the design gate
            # raised its approvals and then let build run anyway.
            if status == "awaiting_approval" and node.startswith("gate_"):''')

# ── max_iter values that do not crash ────────────────────────────────────────
f = swap(FLOW, "research max_iter", f,
'''            # Default is 25. A PRD that takes more than eight tool calls is
            # looping, not working — which is what nine identical writes of the
            # same file looked like on 1 September.
            max_iter=8,
            max_retry_limit=1,''',
'''            # NOT a runaway guard. Exceeding max_iter makes CrewAI force a
            # final answer via assistant-message prefill, which Anthropic
            # rejects with a 400 — so hitting this limit kills the stage rather
            # than truncating it. The runaway guard is the LiteLLM per-key
            # budget, which refuses the call cleanly. Set high enough that
            # normal work never reaches it.
            max_iter=15,
            max_retry_limit=1,''')

f = swap(FLOW, "launch max_iter", f,
'''            max_iter=6,          # one launch announcement; 25 is a runaway''',
'''            max_iter=10,         # see node_research: this is a crash, not a cap''')
edits.append((FLOW, f))

sk = SKILL.read_text(encoding="utf-8")
if "max_iter=15" in sk:
    sys.exit("Already patched — skill_runner max_iter is 15.")

sk = swap(SKILL, "skill max_iter", sk, "        max_iter=3", '''        # 3 was barely enough to read a PRD, think and write a file, and
        # exceeding it is fatal rather than graceful: CrewAI forces a final
        # answer with assistant-message prefill, which Anthropic 400s. Survived
        # only because every previous run was llama3.1 via Ollama, which
        # accepts prefill. Spend is capped by the LiteLLM per-key budget.
        max_iter=15''')
edits.append((SKILL, sk))

for path, text in edits:
    backup = path.with_name(f"{path.stem}.backup-gate2-{stamp}{path.suffix}")
    shutil.copy2(path, backup)
    path.write_text(text, encoding="utf-8")

import ast
for path, _ in edits:
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        sys.exit(f"SYNTAX ERROR in {path.name} ({e}) — restore from "
                 f"*.backup-gate2-{stamp}.*")

print("applied: " + ", ".join(applied))
print(f"backups: *.backup-gate2-{stamp}.*")
