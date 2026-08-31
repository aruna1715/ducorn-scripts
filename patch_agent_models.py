#!/usr/bin/env python3
"""
Fix _get_agent_models(): the fifth hardcoded model list, and a live spend leak.

TWO BUGS, BOTH SILENT
---------------------

1. A model the founder picks in the switcher can be downgraded to llama3.1
   without a word. _get_agent_models has:

       model_map = {"claude-sonnet": ..., "deepseek-chat": ...,
                    "deepseek-reasoner": ..., "local-fast": ..., "local-heavy": ...}
       ...
       model_map.get(agents.get("SAGE", "local-fast"), "local-fast")

   claude-opus, claude-sonnet-5 and gemini-flash are not in that dict, because
   they were added to LiteLLM after it was written. Pick Claude Opus for SAGE
   in the dashboard and .get() misses, so SAGE runs on local-fast. The run
   completes, the logs say nothing, and the output is quietly an 8B model's.

   This is the same failure that hid behind the LiteLLM fallbacks for weeks: a
   lookup that cannot find the right answer returning a plausible wrong one.
   The map is deleted rather than extended. The dashboard's model ids ARE
   LiteLLM's ids now — available_models() derives them from /v1/models — so
   there is nothing left to translate.

2. Test runs are NOT pinned to local models, despite appearances.
   _pin_local_for_test_runs sets DUCORN_LOCAL_ONLY=1, which skill_runner.py and
   DuCornCursorTool.py honour — but _get_agent_models never reads it. So on a
   test run the CrewAI nodes (SAGE in research, NOVA in launch) use whatever
   the switcher says, on a paid model, against a run marked test.

   Until 28 August this cost nothing, because LiteLLM had no vendor keys and
   served llama3.1 for everything. Now that the keys work, it bills.

Also returns every agent in the config rather than four hardcoded keys, so
DESIGN_MODEL is available without another edit here.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

FLOW = Path("/Users/ducorn/DC/ducorn/flows/langgraph_flow.py")
s = FLOW.read_text(encoding="utf-8")

if "_LOCAL_MODEL" in s:
    sys.exit("Already patched — _LOCAL_MODEL is present.")

OLD = '''def _get_agent_models() -> dict:
    """Read agent model config from API — respects dashboard model switcher."""
    try:
        import urllib.request, json as _json
        req = urllib.request.Request(
            "http://localhost:8000/agents/config",
            headers={"x-api-key": os.environ.get("DUCORN_API_TOKEN", "ducorn-api-2026-secure")}
        )
        resp = urllib.request.urlopen(req, timeout=3)
        data = _json.loads(resp.read())
        agents = data.get("agents", {})
        # Map dashboard model IDs to LiteLLM model strings
        model_map = {
            "claude-sonnet":     "claude-sonnet",
            "deepseek-chat":     "deepseek-chat",
            "deepseek-reasoner": "deepseek-reasoner",
            "local-fast":        "local-fast",
            "local-heavy":       "local-heavy",
        }
        return {
            "SAGE_MODEL": model_map.get(agents.get("SAGE", "local-fast"), "local-fast"),
            "REX_MODEL":  model_map.get(agents.get("REX",  "local-fast"), "local-fast"),
            "IRIS_MODEL": model_map.get(agents.get("IRIS", "local-fast"), "local-fast"),
            "NOVA_MODEL": model_map.get(agents.get("NOVA", "local-fast"), "local-fast"),
        }
    except Exception as e:
        print(f"⚠️  Could not read agent config: {e} — defaulting all to local-fast")
        return {
            "SAGE_MODEL": "local-fast",
            "REX_MODEL":  "local-fast",
            "IRIS_MODEL": "local-fast",
            "NOVA_MODEL": "local-fast",
        }'''

NEW = '''# The model a run falls back to when nothing better is known, and the one every
# test run is pinned to. One name, one place.
_LOCAL_MODEL = "local-fast"

# Agents that must always have an entry, so a caller's .get() cannot come back
# empty even if the API is unreachable mid-run.
_AGENTS = ("SAGE", "REX", "IRIS", "NOVA", "DESIGN")


def _local_only() -> bool:
    return os.environ.get("DUCORN_LOCAL_ONLY", "").lower() in ("1", "true", "yes")


def _get_agent_models() -> dict:
    """
    {"<AGENT>_MODEL": model_id} from the dashboard switcher.

    No translation table. The switcher's ids come from available_models(),
    which reads LiteLLM's /v1/models, so they are already the ids LiteLLM
    serves. The map that used to sit here silently downgraded any model added
    after it was written — claude-opus among them — to local-fast.

    On a test run every agent is pinned to local regardless of the switcher.
    DUCORN_LOCAL_ONLY was already set by _pin_local_for_test_runs and honoured
    by skill_runner and DuCornCursorTool; this function ignored it, which meant
    the CrewAI nodes billed a paid model on runs marked test.
    """
    if _local_only():
        print(f"🔒 local-only run — every agent pinned to {_LOCAL_MODEL}")
        return {f"{a}_MODEL": _LOCAL_MODEL for a in _AGENTS}

    try:
        import urllib.request, json as _json
        req = urllib.request.Request(
            "http://localhost:8000/agents/config",
            headers={"x-api-key": os.environ.get("DUCORN_API_TOKEN", "ducorn-api-2026-secure")}
        )
        resp = urllib.request.urlopen(req, timeout=3)
        data = _json.loads(resp.read())
        agents = data.get("agents", {}) or {}
    except Exception as e:
        print(f"⚠️  Could not read agent config: {e} — defaulting all to {_LOCAL_MODEL}")
        return {f"{a}_MODEL": _LOCAL_MODEL for a in _AGENTS}

    # Every agent the API knows about, plus the required ones, so a new agent
    # added to the switcher reaches the pipeline without another edit here.
    models = {f"{name}_MODEL": (model or _LOCAL_MODEL)
              for name, model in agents.items()}
    for a in _AGENTS:
        models.setdefault(f"{a}_MODEL", _LOCAL_MODEL)

    chosen = ", ".join(f"{k.replace('_MODEL','')}={v}" for k, v in sorted(models.items()))
    print(f"🎛️  models from switcher: {chosen}")
    return models'''

if s.count(OLD) != 1:
    sys.exit(f"ANCHOR MISS: found {s.count(OLD)} matches for _get_agent_models, "
             f"expected 1. Nothing written.")

backup = FLOW.with_name(f"langgraph_flow.backup-models-{datetime.now():%Y%m%d-%H%M%S}.py")
shutil.copy2(FLOW, backup)
FLOW.write_text(s.replace(OLD, NEW, 1), encoding="utf-8")

import ast
try:
    ast.parse(FLOW.read_text(encoding="utf-8"))
except SyntaxError as e:
    shutil.copy2(backup, FLOW)
    sys.exit(f"SYNTAX ERROR ({e}) — reverted from {backup}")

print("applied: _get_agent_models rewritten (no model_map, honours DUCORN_LOCAL_ONLY,"
      " returns every configured agent)")
print(f"backup:  {backup}")
