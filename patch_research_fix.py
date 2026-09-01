#!/usr/bin/env python3
"""
Fix node_research: the model it uses, the brief it ignores, and the loop.

THREE DEFECTS, ONE CAUSE EACH
-----------------------------

1. IT ALWAYS RUNS local-fast.

       llm=os.environ.get("SAGE_MODEL", "local-fast")

   Nothing sets SAGE_MODEL before this node. node_launch was fixed for exactly
   this — it calls _get_agent_models() and writes NOVA_MODEL into the
   environment first, and test_integration T29 asserts it does. node_research
   never was, so it has silently used llama3.1 on every run since the switcher
   existed. The 1 Sept run printed "💳 environment=production" and then made
   17 calls to ollama/llama3.1 for $0.00.

   Every PRD DuCorn has ever produced was written by an 8B model.

2. THE FOUNDER'S BRIEF NEVER REACHES SAGE.

   The task description is built from the topic string, ducorn-stack-context.md
   and generic instructions. The brief is read into `founder_brief` AFTER the
   task is constructed, and is only used to re-append it to the PRD once
   research has overwritten the file. So an uploaded brief influences nothing.

   That is why a rebuild of the DuCorn dashboard came back as a generic
   analytics product competing with Mixpanel, in React and Kubernetes.

3. NOTHING BOUNDS THE LOOP.

   CrewAI's Agent.max_iter defaults to 25. With no brief, SAGE could not
   produce output that satisfied the task, so it rewrote the same PRD nine
   times and would have kept going. On llama3.1 that was free. On claude-sonnet
   at 25 iterations per task across six skills it is not.

WHAT CHANGES
------------
  * the model comes from _get_agent_models(), the way node_launch does it
  * the brief goes in FIRST, marked binding, with the generic research
    instruction subordinated to it — "research what the brief leaves open"
    rather than "research the market", which is what invited Mixpanel
  * max_iter is set explicitly; a PRD that needs more than eight tool calls
    is looping, not working
  * a missing brief now FAILS the node instead of researching from a name.
    The API already requires a brief, so its absence here means something
    upstream is broken, and inventing a product is the worst response to that.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

FLOW = Path("/Users/ducorn/DC/ducorn/flows/langgraph_flow.py")
s = FLOW.read_text(encoding="utf-8")

if "BRIEF IS BINDING" in s:
    sys.exit("Already patched — node_research carries the brief.")

lines = s.splitlines(keepends=True)

start = [i for i, l in enumerate(lines) if l.strip() == "sage = Agent("]
end = [i for i, l in enumerate(lines)
       if l.strip() == "crew = Crew(agents=[sage], tasks=[task], verbose=True)"]
if len(start) != 1 or len(end) != 1 or end[0] <= start[0]:
    sys.exit(f"ANCHOR MISS: start={len(start)} end={len(end)}. NOTHING WRITTEN.")

NEW = '''        # The model comes from the dashboard switcher, exactly as node_launch
        # does it. Reading os.environ["SAGE_MODEL"] directly meant falling
        # through to local-fast on every run, because nothing sets it here.
        _models = _get_agent_models()
        _sage_model = _models.get("SAGE_MODEL", _LOCAL_MODEL)
        os.environ["SAGE_MODEL"] = _sage_model
        print(f"🧠 SAGE model: {_sage_model}")

        # The brief, read BEFORE the task is built. It used to be read after,
        # purely so it could be re-appended once research had overwritten the
        # file — which preserved it on disk without it ever reaching the model.
        prd_path = PRODUCTS_DIR / "docs" / f"{topic}-PRD.md"
        prd_path.parent.mkdir(parents=True, exist_ok=True)

        founder_brief = ""
        if prd_path.exists():
            raw = prd_path.read_text()
            founder_brief = (raw.split(BRIEF_MARKER, 1)[1].lstrip("\\n")
                             if BRIEF_MARKER in raw else raw)
        founder_brief = founder_brief.strip()

        if not founder_brief:
            # The API rejects a start with no brief, so an empty one here means
            # something upstream broke. Researching from the product NAME is
            # how a dashboard rebuild came back as a Mixpanel competitor —
            # failing is the honest response.
            msg = (f"No founder brief found at {prd_path}. Refusing to research "
                   f"from the product name alone.")
            print(f"❌ {msg}")
            _post_slack(f"❌ *ATLAS: Research blocked* — `{topic}`\\n{msg}")
            return {**state, "phase": "research", "status": "failed",
                    "error": msg}

        print(f"📋 Founder brief: {len(founder_brief)} chars — "
              f"passing to SAGE as binding")

        sage = Agent(
            role="Research Director",
            goal=f"Turn the founder's brief for {topic} into a complete PRD",
            backstory="You are SAGE, DuCorn's research intelligence.",
            llm=_sage_model,
            tools=[SerperDevTool(),
                   JailedFileReadTool(topic=topic),
                   DuCornWriterTool(topic=topic)],
            # Default is 25. A PRD that takes more than eight tool calls is
            # looping, not working — which is what nine identical writes of the
            # same file looked like on 1 September.
            max_iter=8,
            max_retry_limit=1,
            verbose=True
        )

        # Read stack context
        context_path = PRODUCTS_DIR / "docs" / "ducorn-stack-context.md"
        context = context_path.read_text() if context_path.exists() else ""

        task = Task(
            description=f"""Expand the founder's brief below into a complete PRD
for '{topic}'.

=============================== THE BRIEF IS BINDING ===========================
Everything between these markers was written by the founders. It is the
specification, not background reading. Do not substitute your own idea of what
this product should be, do not propose a different tech stack than it names,
and do not drop requirements you think are unnecessary.

{founder_brief}

================================ END OF BRIEF =================================

YOUR JOB
1. Expand the brief into a PRD: structure it, make implicit requirements
   explicit, and fill in what the brief leaves genuinely open.
2. Research ONLY what the brief does not settle. If it names a stack, a file
   format or a constraint, that decision is already made.
3. Save the result to docs/{topic}-PRD.md using DuCornWriterTool — one write,
   complete, first time.

The PRD MUST include one of these type markers:
**Type:** software | document | dashboard | api

Reference — the DuCorn stack this runs on:
{context[:2000]}""",
            expected_output=f"A PRD at docs/{topic}-PRD.md that implements the "
                            f"founder's brief, not a generic product of the "
                            f"same name",
            agent=sage
        )

'''

lines[start[0]:end[0]] = [NEW]
s = "".join(lines)

# node_launch's agent is unbounded too — same 25-iteration default, and it
# writes one short document.
old_nova = '''            llm=_models.get("NOVA_MODEL", "local-fast"),
            tools=[FileReadTool(base_dir=str(PRODUCTS_DIR)), DuCornWriterTool()],
            verbose=True'''
if s.count(old_nova) == 1:
    s = s.replace(old_nova, '''            llm=_models.get("NOVA_MODEL", _LOCAL_MODEL),
            tools=[FileReadTool(base_dir=str(PRODUCTS_DIR)), DuCornWriterTool()],
            max_iter=6,          # one launch announcement; 25 is a runaway
            max_retry_limit=1,
            verbose=True''', 1)
    print("also bounded: node_launch max_iter=6")

backup = FLOW.with_name(f"langgraph_flow.backup-research-"
                        f"{datetime.now():%Y%m%d-%H%M%S}.py")
shutil.copy2(FLOW, backup)
FLOW.write_text(s, encoding="utf-8")

import ast
try:
    ast.parse(s)
except SyntaxError as e:
    shutil.copy2(backup, FLOW)
    sys.exit(f"SYNTAX ERROR ({e}) — reverted from {backup}")

print("applied: node_research model + brief + max_iter")
print(f"backup:  {backup}")
