#!/usr/bin/env python3
"""
A phase starts as a TEST run unless you say otherwise.

    cd ~/DC && python3 scripts/patch_phase_test_default.py            show
    cd ~/DC && python3 scripts/patch_phase_test_default.py --apply    do it

Needs scripts/patchlib.py.

── WHY ──────────────────────────────────────────────────────────────────────

start_phase inserts every run as production:

    VALUES (%s, %s, %s, 'created', %s, %s, %s, %s, 'production')

Hardcoded. There has never been a way to run a phase cheaply, even though the
whole mechanism for it exists: _pin_local_for_test_runs reads
pipeline_runs.environment, and a 'test' run pins every agent to the local
model. Free. Same nodes, same skills, same gates, same jail — the plumbing is
exercised end to end and nothing is billed.

Phase 1 of the admin rebuild was run straight to production because that was
the only setting available, and the plumbing faults it found — a dangling
else, a gate scraping prose, a build directory nobody wrote to — would all
have surfaced identically on local models for nothing.

── THE CHANGE ───────────────────────────────────────────────────────────────

    start_next(..., environment="test")     the default

Expensive becomes the thing you ask for, not the thing you get. The run
announces which it is before it launches, and the dashboard has to send
environment="production" deliberately.

── WHAT A TEST RUN DOES NOT PROVE ───────────────────────────────────────────

That the product is good. A local model writes worse code than claude-sonnet,
so a test run's OUTPUT is not the output you would ship. What it proves is
that every step runs, hands off, gates, and records — which is the part that
has failed all day, and the part that costs nothing to check.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
SP = DC / "scripts" / "start_phase.py"
API = DC / "ducorn-products" / "products" / "ducorn-activity-api" / "main.py"
LIB = DC / "scripts" / "patchlib.py"
TAG = "testdefault"

SIG_OLD = '''def start_next(epic_name: str, *, engine="gstack", coder="crewai",
               complexity="medium") -> dict:'''
SIG_NEW = '''def start_next(epic_name: str, *, engine="gstack", coder="crewai",
               complexity="medium", environment="test") -> dict:'''

INS_OLD = '''            cur.execute("""
                INSERT INTO pipeline_runs
                    (slug, product_name, complexity, status, product_type,
                     has_ui, build_engine, coder, environment)
                VALUES (%s, %s, %s, 'created', %s, %s, %s, %s, 'production')
            """, (slug,
                  f"{plan['epic']} — phase {plan['next']['seq']}: "
                  f"{plan['next']['title']}",
                  complexity, ptype, ptype in ("webpage", "software"),
                  engine, coder))'''

INS_NEW = '''            # TEST unless asked otherwise. _pin_local_for_test_runs reads
            # this column and pins every agent to the local model when it
            # says 'test' — same nodes, same gates, same jail, no bill.
            #
            # It used to be the literal 'production', so there was no way to
            # exercise the plumbing cheaply. Every plumbing fault phase 1
            # found would have surfaced the same way on local models.
            if environment not in ("test", "production"):
                raise NotStartable(
                    f"environment must be 'test' or 'production', not "
                    f"{environment!r}")
            cur.execute("""
                INSERT INTO pipeline_runs
                    (slug, product_name, complexity, status, product_type,
                     has_ui, build_engine, coder, environment)
                VALUES (%s, %s, %s, 'created', %s, %s, %s, %s, %s)
            """, (slug,
                  f"{plan['epic']} — phase {plan['next']['seq']}: "
                  f"{plan['next']['title']}",
                  complexity, ptype, ptype in ("webpage", "software"),
                  engine, coder, environment))'''

LAUNCH_OLD = '''    LOGS.mkdir(parents=True, exist_ok=True)
    log = LOGS / f"flow_{slug}.log"'''
LAUNCH_NEW = '''    print(f"🏷️  {slug} is a {environment.upper()} run"
          + ("  — local models, nothing billed"
             if environment == "test" else "  — PAID models"), flush=True)

    LOGS.mkdir(parents=True, exist_ok=True)
    log = LOGS / f"flow_{slug}.log"'''

RET_OLD = '''    return {"started": slug, "seq": plan["next"]["seq"],
            "title": plan["next"]["title"], "pid": proc.pid,'''
RET_NEW = '''    return {"started": slug, "seq": plan["next"]["seq"],
            "title": plan["next"]["title"], "pid": proc.pid,
            "environment": environment,'''

CLI_OLD = '''    ap.add_argument("--complexity", default="medium",
                    choices=["simple", "medium", "complex"])'''
CLI_NEW = '''    ap.add_argument("--complexity", default="medium",
                    choices=["simple", "medium", "complex"])
    ap.add_argument("--environment", default="test",
                    choices=["test", "production"],
                    help="test pins every agent to the local model and costs "
                         "nothing; production spends. Default: test.")'''

CALL_OLD = '''        r = start_next(a.epic, engine=a.engine, coder=a.coder,
                       complexity=a.complexity)'''
CALL_NEW = '''        r = start_next(a.epic, engine=a.engine, coder=a.coder,
                       complexity=a.complexity, environment=a.environment)'''

API_OLD = '''    try:
        result = sp.start_next(name)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    return result'''

API_NEW = '''    # TEST unless the caller asks for production. The expensive option is
    # the one you request, not the one you get by not saying anything.
    try:
        body = await request.json()
    except Exception:
        body = {}
    env = (body.get("environment") or "test").strip()
    try:
        result = sp.start_next(name, environment=env)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    return result'''

API_SIG_OLD = '''def epic_start_next(name: str):'''
API_SIG_NEW = '''async def epic_start_next(name: str, request: Request):'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in (SP, API, LIB):
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

sys.path.insert(0, str(DC / "scripts"))
from patchlib import code_only, py_ok, PatchCheckFailed   # noqa: E402

sp_src = SP.read_text(encoding="utf-8")
api_src = API.read_text(encoding="utf-8")
print("patch_phase_test_default\n")

if 'environment="test"' in sp_src:
    sys.exit("NOTHING DONE — phases already default to test.")

# The mechanism this relies on must actually exist.
flow = (DC / "ducorn" / "flows" / "langgraph_flow.py").read_text(encoding="utf-8")
if "_pin_local_for_test_runs" not in flow or "environment FROM pipeline_runs" not in flow:
    sys.exit("NOTHING DONE — the flow does not pin local models from "
             "pipeline_runs.environment, so a 'test' run would spend anyway.")
print("  ok  the flow pins local models when environment='test'")

bad = False
for label, hay, a in [("start_next signature", sp_src, SIG_OLD),
                      ("the INSERT", sp_src, INS_OLD),
                      ("the launch block", sp_src, LAUNCH_OLD),
                      ("the return", sp_src, RET_OLD),
                      ("the CLI options", sp_src, CLI_OLD),
                      ("the CLI call", sp_src, CALL_OLD),
                      ("the endpoint body", api_src, API_OLD),
                      ("the endpoint signature", api_src, API_SIG_OLD)]:
    n = hay.count(a)
    print(f"  {'ok ' if n == 1 else '!! '}{label}  ({n} match)")
    bad |= n != 1
if bad:
    sys.exit("\nNOTHING DONE — an anchor did not match exactly once.")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(SP, SP.with_suffix(f".backup-{TAG}-{stamp}.py"))
shutil.copy2(API, API.with_suffix(f".backup-{TAG}-{stamp}.py"))
SP.write_text(sp_src.replace(SIG_OLD, SIG_NEW, 1).replace(INS_OLD, INS_NEW, 1)
              .replace(LAUNCH_OLD, LAUNCH_NEW, 1).replace(RET_OLD, RET_NEW, 1)
              .replace(CLI_OLD, CLI_NEW, 1).replace(CALL_OLD, CALL_NEW, 1),
              encoding="utf-8")
API.write_text(api_src.replace(API_SIG_OLD, API_SIG_NEW, 1)
               .replace(API_OLD, API_NEW, 1), encoding="utf-8")
print(f"\nwrote start_phase.py and main.py, backups tagged {TAG}-{stamp}")

for f in (SP, API):
    try:
        py_ok(f.read_text(encoding="utf-8"), f.name)
    except PatchCheckFailed as e:
        sys.exit(f"⚠️  {e} — restore the backups.")

sp_after = code_only(SP.read_text(encoding="utf-8"))
if "'production')" in sp_after:
    sys.exit("⚠️  the hardcoded 'production' is still in the INSERT — restore "
             "the backups.")
if 'environment="test"' not in sp_after:
    sys.exit("⚠️  the default is not test — restore the backups.")
api_after = code_only(API.read_text(encoding="utf-8"))
if 'sp.start_next(name, environment=env)' not in api_after:
    sys.exit("⚠️  the endpoint does not pass an environment — restore the "
             "backups.")
print("verified: both parse, the hardcoded production is gone, and the "
      "default is test.")

print("""
  launchctl kickstart -k gui/$(id -u)/com.ducorn.api

A phase now starts as a TEST run — every agent on the local model, nothing
billed — and prints which it is before launching:

  🏷️  <slug> is a TEST run — local models, nothing billed

Production is an explicit choice:

  python3 scripts/start_phase.py <epic> --apply --environment production
""")
