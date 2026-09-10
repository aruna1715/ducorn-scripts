#!/usr/bin/env python3
"""
Can every agent key actually reach every model the config serves?

    cd ~/DC && python3 scripts/check_agent_models.py

Install as scripts/check_agent_models.py. Read-only — it writes nothing,
needs no master key, and is safe to run while a pipeline is in flight.

Exit 0 = every key can reach the model a TEST run uses.
Exit 1 = at least one cannot, and a test run would die at that agent.

── WHY THIS IS NOT THE SAME AS LOOKING AT THE UI ─────────────────────────────

Three separate things have to agree, and the run only works if all three do:

    litellm_config.yaml   the model_name entries LiteLLM serves
    the key record        each key's `models` allowlist, in LiteLLM's DB
    GET /v1/models        what a CALLING KEY is actually told it may use

The UI and /key/info show you the middle one. The pipeline only ever sees the
third. A run died with

    Model 'local-heavy' is not served by LiteLLM
    available_models: ['claude-sonnet','deepseek-chat','deepseek-reasoner',
                       'local-fast']

while the config served eight models and the proxy had logged all eight on
startup. The config was right and the record was the problem — but nothing in
the stack was asking the question from where the agents stand.

So this asks from there. It authenticates AS each agent key, exactly as
skill_runner does, and reports what that key is told. No master key, because
a check that needs an admin credential is a check nobody runs.

── WHAT IT WILL AND WILL NOT FAIL ON ────────────────────────────────────────

A key missing the LOCAL model is a failure. A test run pins every agent to it,
so one key without it means the pipeline cannot be proven for free — which is
the whole point of a test run.

A key missing a PAID model is reported, not failed. CLEO and ECHO are scoped
without claude-sonnet deliberately: they are the cheap agents, and the gap in
their allowlist is the boundary that stops anything reaching a paid model on
their behalf. A checker that called that "drift" would push someone toward
flattening it.

Which model is the local one is read from DUCORN_LOCAL_MODEL, not written
here. There is no list of agent names in this file either. Both would be a
second copy of a fact that lives somewhere else, and the copy is always the
one that goes stale.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

DC = Path(os.environ.get("DUCORN_ROOT", "/Users/ducorn/DC"))
CFG = DC / "scripts" / "litellm_config.yaml"
LITELLM = os.environ.get("LITELLM_URL", "http://localhost:4000")
TIMEOUT = 20


def served_models(path: Path) -> list:
    """
    The model names litellm_config.yaml serves.

    Parsed without PyYAML on purpose. This must run under whichever python
    the operator happens to type, and a check that cannot run is a check that
    does not exist — a patch earlier in this project imported yaml under a
    python that did not have it, and reported a working config as broken.
    """
    names = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("#") or "model_name:" not in s:
            continue
        name = s.split("model_name:", 1)[1].strip().strip('"\'')
        if name:
            names.append(name)
    return names


def models_for(key: str) -> tuple:
    """
    (models, error) for one calling key. This is the pipeline's own view.
    """
    req = urllib.request.Request(
        f"{LITELLM}/v1/models",
        headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:160].replace("\n", " ")
        return [], f"HTTP {e.code}: {detail}"
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"
    data = body.get("data")
    if not isinstance(data, list):
        return [], f"unexpected response shape: {str(body)[:120]}"
    return [m.get("id") for m in data if isinstance(m, dict) and m.get("id")], ""


def load_env() -> None:
    """Load shared/.env the way the services do, so the keys are present."""
    sys.path.insert(0, str(DC / "scripts"))
    try:
        from ducorn_env import load_ducorn_env
        load_ducorn_env()
    except Exception as e:
        print(f"note: could not load shared/.env via ducorn_env ({e}) — "
              f"relying on the environment as it stands\n")


def main() -> int:
    if not CFG.is_file():
        print(f"{CFG} is not there — nothing to check against.")
        return 1

    load_env()

    served = served_models(CFG)
    if not served:
        print(f"no model_name entries in {CFG}.")
        return 1

    local = os.environ.get("DUCORN_LOCAL_MODEL", "local-fast")

    keys = {k: v for k, v in os.environ.items()
            if k.startswith("LITELLM_KEY_") and v.strip()}
    if not keys:
        print("no LITELLM_KEY_* variables — shared/.env did not load, so this "
              "would test nothing.")
        return 1

    print(f"litellm_config.yaml serves {len(served)}: {', '.join(served)}")
    print(f"a TEST run pins every agent to: {local}"
          + ("" if local in served else "   ⚠️  NOT IN THE SERVED LIST"))
    print(f"asking {LITELLM}/v1/models as each of {len(keys)} agent keys\n")

    if local not in served:
        print(f"Stop here. DUCORN_LOCAL_MODEL is {local!r} and the config does "
              f"not serve it, so no key can be granted it. Fix "
              f"litellm_config.yaml first — granting keys a model that is not "
              f"served changes nothing.\n")

    blocked, unreachable, notes = [], [], []
    for name in sorted(keys):
        agent = name[len("LITELLM_KEY_"):]
        got, err = models_for(keys[name])
        if err:
            print(f"  {agent:<8} ⚠️  {err}")
            unreachable.append(agent)
            continue

        has_local = local in got
        missing = [m for m in served if m not in got]
        mark = "✅" if has_local else "❌"
        print(f"  {agent:<8} {mark} {len(got)} reachable"
              + (f"   no {local}" if not has_local else "")
              + (f"   also missing: {', '.join(m for m in missing if m != local)}"
                 if [m for m in missing if m != local] else ""))
        if not has_local:
            blocked.append(agent)
        paid_gaps = [m for m in missing if m != local]
        if paid_gaps:
            notes.append((agent, paid_gaps))

    print()
    if unreachable:
        print(f"{len(unreachable)} key(s) could not be asked: "
              f"{', '.join(unreachable)}.")
        print("That is not the same as a key being wrong — the proxy may be "
              "down, or the key value in shared/.env may not match what "
              "LiteLLM holds. Check the proxy is up before reading anything "
              "else here.\n")

    if notes:
        print("Gaps in PAID models, reported and not failed:")
        for agent, gaps in notes:
            print(f"  {agent:<8} cannot reach {', '.join(gaps)}")
        print("Some of these are the point. A key scoped without a paid model "
              "is a spending boundary — CLEO and ECHO are deliberately\n"
              "without claude-sonnet. Only widen one if you mean to.\n")

    if blocked:
        print(f"❌ {len(blocked)} key(s) cannot reach {local}: "
              f"{', '.join(blocked)}")
        print(f"A TEST run pins every agent to {local}, so it will fail at the "
              f"first skill those agents own — with 'Model {local!r} is not "
              f"served by LiteLLM', which names the wrong cause.")
        return 1

    if unreachable:
        return 1

    print(f"✅ every agent key can reach {local}. A test run has a model to "
          f"use at every step.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
