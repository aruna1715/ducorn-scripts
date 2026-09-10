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

GRANT what you name. Never "everything to everyone".

The first version of this set every key to the full served list, which would
have been a real regression: CLEO and ECHO are deliberately scoped WITHOUT
claude-sonnet — they are the cheap agents, pinned to local-fast, and their
keys are the boundary that stops anything reaching a paid model on their
behalf. Flattening that is the same error litellm_budget.py refuses by
design: "Refusing to change all nine keys at once — their budgets differ on
purpose."

So a grant is explicit and additive. Existing entries are kept.

Budgets are untouched: they are the other control, they differ on purpose,
and nothing here reads or writes them.

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
    ap.add_argument("--grant", action="append", default=[], metavar="MODEL",
                    help="add this model to every restricted key, keeping "
                         "what each already has. Repeatable.")
    ap.add_argument("--key", action="append", default=[], metavar="AGENT",
                    help="limit the grant to these agents, e.g. --key SAGE")
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

    drift, restricted = {}, {}
    for name in sorted(keys):
        value = keys[name]
        info = api(f"/key/info?key={value}", master).get("info", {}) or {}
        have = info.get("models") or []
        missing = [m for m in want if m not in have] if have else []
        restricted[name] = (value, have)
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

    print(f"\n{len(drift)} key(s) cannot reach every served model. Some of "
          f"that is deliberate:\n"
          f"  a key WITHOUT claude-sonnet is a cost boundary, not drift.\n"
          f"Grant only what you mean.")

    if not a.grant:
        print("""
Nothing written. Name the models to grant:

  python3 scripts/litellm_models.py --grant local-heavy --apply

local-heavy is free, so granting it to every agent costs nothing and is what
a TEST run needs. Granting a paid model is a spending decision — make it one
key at a time:

  python3 scripts/litellm_models.py --grant claude-opus --key DESIGN --apply
""")
        return 0

    unknown = [m for m in a.grant if m not in want]
    if unknown:
        raise SystemExit(f"\n{unknown} is not served by litellm_config.yaml. "
                         f"Serving it comes first, or the grant points at "
                         f"nothing.")

    only = {f"LITELLM_KEY_{k.strip().upper()}" for k in a.key}
    targets = {n: v for n, v in restricted.items()
               if v[1] and (not only or n in only)}
    if only:
        missing_names = only - set(restricted)
        if missing_names:
            raise SystemExit(f"\nno such key(s) in the environment: "
                             f"{sorted(missing_names)}")
    if not targets:
        print("\nNo restricted key matches — unrestricted keys already allow "
              "everything.")
        return 0

    print(f"\ngranting {a.grant} to {len(targets)} key(s), keeping what each "
          f"already has")
    if not a.apply:
        for n, (_v, have) in sorted(targets.items()):
            add = [m for m in a.grant if m not in have]
            print(f"  {n:<24} {len(have)} → {len(have) + len(add)}"
                  + (f"  (+{add})" if add else "  (already has them)"))
        print("\nNothing written. Re-run with --apply.")
        return 0

    failed = []
    for name, (value, have) in sorted(targets.items()):
        add = [m for m in a.grant if m not in have]
        if not add:
            print(f"  {name:<24} already has them")
            continue
        merged = have + add
        api("/key/update", master, {"key": value, "models": merged})
        # Read it back. A 200 from an update is not evidence the value stuck.
        back = api(f"/key/info?key={value}", master).get("info", {}) or {}
        now = back.get("models") or []
        still = [m for m in add if m not in now]
        # And the boundary must survive: nothing this grants may ADD a model
        # the operator did not name.
        crept = [m for m in now if m not in merged]
        if still or crept:
            failed.append(f"{name}: missing {still} unexpected {crept}")
            print(f"  {name:<24} FAILED — missing {still} unexpected {crept}")
        else:
            print(f"  {name:<24} +{add}  ({len(now)} allowed)")

    if failed:
        raise SystemExit("\n" + "\n".join(failed))

    print("""
Granted. Each key keeps the models it had; only what you named was added.

Re-run the read-only view after any change to litellm_config.yaml — a model
added there is invisible to every restricted key until it is granted.""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
