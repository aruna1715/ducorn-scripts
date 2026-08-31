#!/usr/bin/env python3
"""
Put a real spend cap on the LiteLLM virtual keys.

    python3 scripts/litellm_budget.py                      # show keys and spend
    python3 scripts/litellm_budget.py --budget 40 --apply  # cap at $40/day

WHY THIS AND NOT THE DASHBOARD'S BUDGET CHECK
---------------------------------------------
/pipeline/start already checks a daily budget. It ends:

    except:
        pass  # Don't block on budget check failure

so it is advisory. It runs once, before the run starts, does not block, and
nothing watches spend while a pipeline is going. $93.14 of claude-sonnet-4-6
went out on 28 August with that check in place.

A LiteLLM virtual-key budget is a different kind of thing: the proxy refuses
the call. An over-budget request comes back as an error the pipeline can see
and report, instead of succeeding and being noticed on a bill. That is the
difference between reporting spend and limiting it.

WHAT IT DOES NOT COVER
----------------------
The master key bypasses budgets — that is how LiteLLM works, and it is why the
master key must never be used for completions. This script says so loudly if it
finds a key that looks like it is being used that way.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

LITELLM = os.environ.get("LITELLM_URL", "http://localhost:4000")
ENV_FILES = [Path("/Users/ducorn/DC/shared/.env"),
             Path("/Users/ducorn/DC/ducorn/.env")]


def load_env():
    """Read KEY=value from the DuCorn env files without importing anything."""
    out = {}
    for p in ENV_FILES:
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return out


def call(path, master, payload=None, method=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{LITELLM}{path}", data=data,
        headers={"Authorization": f"Bearer {master}",
                 "Content-Type": "application/json"},
        method=method or ("POST" if data else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:400]
        raise SystemExit(f"LiteLLM {path} -> HTTP {e.code}\n{body}")
    except urllib.error.URLError as e:
        raise SystemExit(f"Cannot reach LiteLLM at {LITELLM} ({e.reason}).\n"
                         f"Is it running?  launchctl list | grep ducorn.litellm")


def money(v):
    return "unlimited" if v in (None, "") else f"${float(v):.2f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=float,
                    help="max spend per period, in dollars")
    ap.add_argument("--key", action="append", default=[],
                    help="agent name to act on, e.g. --key SAGE --key REX. "
                         "Repeatable. Omit and --apply refuses rather than "
                         "changing all nine at once.")
    ap.add_argument("--create", metavar="AGENT",
                    help="generate a NEW virtual key for this agent (e.g. "
                         "DESIGN) and print the line to add to shared/.env")
    ap.add_argument("--duration", default="1d",
                    help="budget period LiteLLM understands: 1d, 7d, 30d "
                         "(default 1d)")
    ap.add_argument("--apply", action="store_true",
                    help="actually set it (default is to show what is there)")
    args = ap.parse_args()

    env = load_env()
    master = (os.environ.get("LITELLM_MASTER_KEY")
              or env.get("LITELLM_MASTER_KEY") or "ducorn-admin-2026")

    # Which virtual keys DuCorn actually uses, and where each is set.
    named = {k: v for k, v in env.items()
             if k.startswith("LITELLM_KEY_") and v}
    if not named:
        print("No LITELLM_KEY_* entries found in shared/.env or ducorn/.env.")
        print("Nothing to cap — the pipeline may be using the master key, "
              "which cannot be capped. Check OPENAI_API_KEY in ducorn/.env.")

    info = call("/key/list?return_full_object=true", master)
    keys = info.get("keys", info.get("data", []))
    if isinstance(keys, dict):
        keys = list(keys.values())

    print(f"\nLiteLLM virtual keys at {LITELLM}\n" + "=" * 68)
    by_token = {}
    for k in keys:
        if not isinstance(k, dict):
            continue
        alias = k.get("key_alias") or "(no alias)"
        token = k.get("token") or k.get("key_name") or ""
        by_token[token] = k
        print(f"  {alias:<28} spend {money(k.get('spend', 0)):>10}   "
              f"budget {money(k.get('max_budget')):>10}   "
              f"period {k.get('budget_duration') or '-'}")
    if not keys:
        print("  (none returned — every caller may be using the master key)")

    print(f"\nDuCorn env keys: {', '.join(named) or '(none)'}")
    for name, value in named.items():
        tail = value[-8:] if len(value) > 8 else value
        print(f"  {name:<22} ...{tail}")

    # ── create a key that does not exist yet ─────────────────────────────────
    if args.create:
        agent = args.create.strip().upper()
        env_var = f"LITELLM_KEY_{agent}"
        if env_var in named:
            raise SystemExit(f"\n{env_var} already exists in your env files. "
                             f"Use --key {agent} --budget N to change its cap.")
        if args.budget is None:
            raise SystemExit("\n--create needs --budget, e.g. "
                             f"--create {agent} --budget 10")
        if not args.apply:
            print(f"\nDRY RUN — would create key alias 'ducorn-{agent.lower()}' "
                  f"with max_budget={money(args.budget)} per {args.duration}.")
            print("Re-run with --apply.")
            return
        res = call("/key/generate", master,
                   {"key_alias": f"ducorn-{agent.lower()}",
                    "max_budget": args.budget,
                    "budget_duration": args.duration,
                    "metadata": {"agent": agent}})
        new_key = res.get("key")
        if not new_key:
            raise SystemExit(f"LiteLLM did not return a key: {res}")
        print(f"\nCreated ducorn-{agent.lower()} — "
              f"{money(args.budget)} per {args.duration}")
        print("\nAdd this line to /Users/ducorn/DC/shared/.env, then restart "
              "the API:\n")
        print(f"  {env_var}={new_key}")
        print("\nThe key is shown once here. LiteLLM stores a hash, not the "
              "value —\nif you lose it you generate a new one rather than "
              "recovering this.")
        return

    if args.budget is None:
        print("\nPass --budget N --apply to set a cap, e.g.")
        print("  python3 scripts/litellm_budget.py --key ATLAS --budget 40 --apply")
        print("  python3 scripts/litellm_budget.py --create DESIGN --budget 10 --apply")
        return

    # Which keys to touch. Requiring --key is deliberate: these nine budgets
    # were set deliberately and at different levels, and a single --budget
    # applied to all of them would flatten that in one keystroke.
    if not args.key:
        raise SystemExit(
            "\nRefusing to change all nine keys at once — their budgets differ "
            "on purpose.\nName the ones you mean:\n"
            "  --key ATLAS --budget 40 --apply\n"
            "  --key SAGE --key REX --budget 10 --apply")

    targets = {}
    for agent in args.key:
        var = f"LITELLM_KEY_{agent.strip().upper()}"
        if var not in named:
            raise SystemExit(f"\n{var} is not in your env files. "
                             f"Create it first:\n"
                             f"  --create {agent.strip().upper()} --budget N --apply")
        targets[var] = named[var]

    if not args.apply:
        print(f"\nDRY RUN — would set max_budget={money(args.budget)} "
              f"per {args.duration} on: {', '.join(targets)}")
        print("Re-run with --apply.")
        return

    for name, value in targets.items():
        call("/key/update", master,
             {"key": value, "max_budget": args.budget,
              "budget_duration": args.duration})
        # Read it back. A PUT that returns 200 is not evidence the value stuck.
        back = call("/key/info?key=" + value, master).get("info", {})
        got = back.get("max_budget")
        ok = got is not None and abs(float(got) - args.budget) < 0.001
        print(f"\n{name}: asked for {money(args.budget)} per {args.duration}")
        print(f"  LiteLLM reports: {money(got)} "
              f"per {back.get('budget_duration') or '-'}   "
              f"{'OK' if ok else 'MISMATCH — check by hand'}")

    print("\nA call that would exceed this now FAILS at the proxy — the "
          "pipeline\nsees an error instead of quietly spending. Check spend "
          "any time with:")
    print("  python3 scripts/litellm_budget.py")
    print("\nNOTE: the master key bypasses budgets. Nothing that makes "
          "completions\nshould ever use it — only /v1/models and admin calls.")


if __name__ == "__main__":
    main()
