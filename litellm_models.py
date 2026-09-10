#!/usr/bin/env python3
"""
Keep every agent key able to use every model the config serves.

    python3 scripts/litellm_models.py            show the drift
    python3 scripts/litellm_models.py --apply    fix it

Install as scripts/litellm_models.py.

── WHY ──────────────────────────────────────────────────────────────────────

Enabling local-heavy in litellm_config.yaml was not enough. LiteLLM reloaded
and logged all eight models, but a run still died with

    Model 'local-heavy' is not served by LiteLLM
    available_models: ['claude-sonnet','deepseek-chat','deepseek-reasoner',
                       'local-fast']

because /v1/models is filtered by the CALLING KEY, and each per-agent key
carries a model allowlist fixed when it was created. Those four are the
models that existed before 2026-08-29. Everything added since —
claude-opus, claude-sonnet-5, gemini-flash, local-heavy — has been invisible
to every agent, whatever the dashboard switcher offered.

So the switcher could name a model no agent could reach, and the failure
appears at the first paid call rather than at the moment the model was added.

── THE RULE ─────────────────────────────────────────────────────────────────

A key's model list is DERIVED from the config, not maintained beside it. Run
this after any change to litellm_config.yaml and the two cannot drift.

Budgets stay per-key and untouched: they are the real control, they differ on
purpose, and nothing here reads or writes them.

── WHAT IT WILL NOT DO ──────────────────────────────────────────────────────

Print a key. Keys are matched by env-var name and shown masked. LiteLLM
stores a hash, so a key value is only ever in shared/.env and in this
process's memory.

Guess the master key. If LITELLM_MASTER_KEY is not set it says so and stops,
rather than trying a default and reporting a permissions failure as a
missing model.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

DC = Path(os.environ.get("DUCORN_ROOT", "/Users/ducorn/DC"))
CFG = DC / "scripts" / "litellm_config.yaml"
LITELLM = os.environ.get("LITELLM_URL", "http://localhost:4000")


def mask(v: str) -> str:
    return f"{v[:6]}…({len(v)} chars)" if v else "(unset)"


def served_models() -> list:
    """
    The model names litellm_config.yaml serves.

    Parsed without PyYAML on purpose: this must run under whichever python
    the operator has, and a check that cannot run is a check that does not
    exist. A patch earlier today imported yaml under python3.14, could not,
    and reported a working config as broken.
    """
    names = []
    for line in CFG.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("#") or "model_name:" not in s:
            continue
        names.append(s.split("model_name:", 1)[1].strip())
    return names


def api(path: str, master: str, payload=None):
    req = urllib.request.Request(
        f"{LITELLM}{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": f"Bearer {master}",
                 "Content-Type": "application/json"},
        method="POST" if payload is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise SystemExit(f"LiteLLM {path} → {e.code}: "
                         f"{e.read().decode()[:200]}")
    except Exception as e:
        raise SystemExit(f"LiteLLM {path} unreachable: {type(e).__name__}: {e}")


def agent_keys() -> dict:
    """{env var: value} for every LITELLM_KEY_* in the environment."""
    return {k: v for k, v in os.environ.items()
            if k.startswith("LITELLM_KEY_") and v.strip()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    try:
        sys.path.insert(0, str(DC / "scripts"))
        from ducorn_env import load_ducorn_env
        load_ducorn_env()
    except Exception:
        pass

    master = os.environ.get("LITELLM_MASTER_KEY", "").strip()
    if not master:
        raise SystemExit(
            "LITELLM_MASTER_KEY is not set.\n"
            "Key administration needs it, and guessing a default would report "
            "a permissions failure as a missing model — which is exactly the "
            "confusion this script exists to end.\n"
            "Add it to shared/.env and re-run.")

    want = served_models()
    if not want:
        raise SystemExit(f"no model_name entries found in {CFG}")
    print(f"litellm_config.yaml serves {len(want)}: {', '.join(want)}\n")

    keys = agent_keys()
    if not keys:
        raise SystemExit("no LITELLM_KEY_* variables in the environment.")

    drift = {}
    for name in sorted(keys):
        value = keys[name]
        info = api(f"/key/info?key={value}", master).get("info", {}) or {}
        have = info.get("models") or []
        missing = [m for m in want if m not in have] if have else []
        # An EMPTY list in LiteLLM means "no restriction" — every model. That
        # is a valid, and arguably better, state: budgets are the control.
        state = ("no restriction — every model" if not have
                 else f"{len(have)} allowed" + (f", missing {missing}"
                                                if missing else ""))
        print(f"  {name:<24} {mask(value):<22} {state}")
        if missing:
            drift[name] = (value, missing)

    if not drift:
        print("\nNothing to do — every key can reach every served model.")
        return 0

    print(f"\n{len(drift)} key(s) cannot reach models the config serves. "
          f"That is why a run can fail on a model the switcher offers.")

    if not a.apply:
        print("\nNothing written. Re-run with --apply.")
        return 0

    failed = []
    for name, (value, missing) in drift.items():
        api("/key/update", master, {"key": value, "models": want})
        # Read it back. A 200 from an update is not evidence the value stuck —
        # litellm_budget.py learned that about budgets and it is just as true
        # here.
        back = api(f"/key/info?key={value}", master).get("info", {}) or {}
        now = back.get("models") or []
        still = [m for m in want if m not in now] if now else []
        if still:
            failed.append(f"{name}: still missing {still}")
            print(f"  {name:<24} FAILED — still missing {still}")
        else:
            print(f"  {name:<24} now allows all {len(want)}")

    if failed:
        raise SystemExit("\n" + "\n".join(failed))

    print("""
Every agent key can now reach every model the config serves.

Re-run this after any change to litellm_config.yaml — the key lists are
derived from it, so the two only drift if nobody asks.""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
