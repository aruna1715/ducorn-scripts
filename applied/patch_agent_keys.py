#!/usr/bin/env python3
"""
Make each agent spend against its own LiteLLM key.

PREREQUISITE — create the DESIGN key first, and add it to shared/.env:
    python3 scripts/litellm_budget.py --create DESIGN --budget 10 --apply

THE PROBLEM
-----------
Nine per-agent virtual keys exist, with budgets set at different levels on
purpose: ATLAS $20, SAGE/REX/IRIS $5 each, the rest $2. Eight of them are never
used. Only LITELLM_KEY_ATLAS appears in live code — the API passes it as
OPENAI_API_KEY to every pipeline subprocess, so SAGE's research, REX's build,
IRIS's QA and DESIGN's renders all spend against ATLAS's $20.

So the effective cap is $20/day for everything, the other eight budgets cap
keys that nothing holds, and LiteLLM_SpendLogs cannot tell you which stage cost
what. A control that exists, reads correctly on its own, and never reaches the
thing it is supposed to control — the same shape as the router table, the Drive
catch-all, display_header_footer and --force.

WHAT THIS CHANGES
-----------------
Each node and each G-Stack skill sets OPENAI_API_KEY to its own agent's key
before it runs. Nodes execute sequentially in one process and skills run as
subprocesses, so setting the environment variable at the top of each is enough
and matches how NOVA_MODEL and DUCORN_LOCAL_ONLY already work.

    node_research   SAGE      node_design   DESIGN     node_launch   NOVA
    skill 01        SAGE      skills 02/03/06  IRIS     skills 04/05  REX

Two things follow, and the second is the reason to do this before the run
rather than after:

  * a runaway stage is capped at ITS budget, not at everything's
  * LiteLLM_SpendLogs attributes spend per key, so the first production run
    finally answers what design costs and what build costs — which is the data
    COST_ESTIMATES should derive from instead of being three hardcoded strings

MISSING KEYS
------------
A missing LITELLM_KEY_<AGENT> falls back to ATLAS with a warning rather than
failing, because dying mid-pipeline over a config gap is worse than spending
from the wrong bucket. The gap should be caught BEFORE a run instead —
verify_design_wiring.py checks every agent has a key.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

FLOW  = Path("/Users/ducorn/DC/ducorn/flows/langgraph_flow.py")
SKILL = Path("/Users/ducorn/DC/ducorn/skill_runner.py")

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
edits, applied = [], []


def swap(path, label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{path.name}:{label}]: found {text.count(old)}, "
                 f"expected 1. NOTHING WRITTEN.")
    applied.append(f"{path.name}:{label}")
    return text.replace(old, new, 1)


HELPER = '''def _key_for(agent: str) -> str:
    """
    The LiteLLM virtual key this agent spends against.

    Falls back to ATLAS, loudly. Nine keys exist with deliberately different
    budgets; until this function was used, every one of them except ATLAS
    capped a key nothing held.
    """
    key = os.environ.get(f"LITELLM_KEY_{agent.upper()}", "").strip()
    if key:
        return key
    fallback = os.environ.get("LITELLM_KEY_ATLAS", "").strip()
    print(f"⚠️  LITELLM_KEY_{agent.upper()} is not set — {agent} will spend "
          f"against ATLAS's budget and its costs will be attributed to ATLAS. "
          f"Create one: scripts/litellm_budget.py --create {agent.upper()} "
          f"--budget N --apply")
    return fallback


def _use_key(agent: str) -> None:
    """Point this process's model calls at `agent`'s key."""
    key = _key_for(agent)
    if key:
        os.environ["OPENAI_API_KEY"] = key
        print(f"🔑 {agent} calls billed to LITELLM_KEY_{agent.upper()}")


'''

# ── langgraph_flow ───────────────────────────────────────────────────────────
f = FLOW.read_text(encoding="utf-8")
if "_key_for" in f:
    sys.exit("Already patched — _key_for is in langgraph_flow.py.")

f = swap(FLOW, "helper", f, "def _get_agent_models() -> dict:", HELPER + "def _get_agent_models() -> dict:")

def key_in_node(text, node, agent):
    """
    Insert _use_key(agent) as the first thing a node does with its topic.

    Anchored on the function definition, not on a log line. An earlier draft
    matched `print(f"...SAGE: Researching...")` — the real string is
    "Starting research for", which I had invented rather than read. Function
    names are the part that cannot drift.
    """
    lines = text.splitlines(keepends=True)
    defs = [i for i, l in enumerate(lines) if l.startswith(f"def {node}(")]
    if len(defs) != 1:
        sys.exit(f"ANCHOR MISS [{node}]: {len(defs)} definitions found. "
                 f"NOTHING WRITTEN.")
    for i in range(defs[0], min(defs[0] + 12, len(lines))):
        if lines[i].strip() == 'topic = state["topic"]':
            lines.insert(i + 1, f'    _use_key("{agent}")\n')
            applied.append(f"{FLOW.name}:{node} -> {agent}")
            return "".join(lines)
    sys.exit(f"ANCHOR MISS [{node}]: no `topic = state[\"topic\"]` in its "
             f"first 12 lines. NOTHING WRITTEN.")


f = key_in_node(f, "node_research", "SAGE")
f = key_in_node(f, "node_design", "DESIGN")
f = key_in_node(f, "node_launch", "NOVA")
edits.append((FLOW, f))

# ── skill_runner ─────────────────────────────────────────────────────────────
sk = SKILL.read_text(encoding="utf-8")
if "_key_for" in sk:
    sys.exit("Already patched — _key_for is in skill_runner.py.")

sk = swap(SKILL, "helper", sk,
          '''def _local_only() -> bool:''', HELPER + '''def _local_only() -> bool:''')

# Set the key once the skill's agent is known, before the Crew is built.
sk = swap(SKILL, "per-skill key", sk,
'''    agent_name = SKILL_AGENTS[skill_num]
    model = SKILL_MODELS.get(agent_name, "local-fast")''',
'''    agent_name = SKILL_AGENTS[skill_num]
    # Each skill bills its own agent: 01 SAGE, 02/03/06 IRIS, 04/05 REX. This
    # process inherited ATLAS's key from the parent; override it before any
    # call is made, or every skill spends from the same bucket.
    _use_key(agent_name)
    model = SKILL_MODELS.get(agent_name, "local-fast")''')
edits.append((SKILL, sk))


for path, text in edits:
    backup = path.with_name(f"{path.stem}.backup-agentkeys-{stamp}{path.suffix}")
    shutil.copy2(path, backup)
    path.write_text(text, encoding="utf-8")

import ast
for path, _ in edits:
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        sys.exit(f"SYNTAX ERROR in {path.name} ({e}) — restore from "
                 f"*.backup-agentkeys-{stamp}.*")

print("applied: " + ", ".join(applied))
print(f"backups: *.backup-agentkeys-{stamp}.*")
print()
print("Restart the API, then confirm every agent has a key:")
print("  ducorn/.venv/bin/python scripts/verify_design_wiring.py")
