#!/usr/bin/env python3
"""
Make the free tier capable: qwen2.5:32b for test runs.

    cd ~/DC && python3 scripts/patch_local_heavy.py            show
    cd ~/DC && python3 scripts/patch_local_heavy.py --apply    do it

Needs scripts/patchlib.py.

── WHY ──────────────────────────────────────────────────────────────────────

A test run pins every agent to local-fast, which is ollama/llama3.1 — 8B. It
cannot complete a G-Stack skill: on zz-plumbing-check it made 99,808
characters of tool calls, exhausted max_iter=15, produced no final answer,
and the runner recorded "produced only 0 chars of substance".

So the free tier could not prove the pipeline, which is the one job it has.

qwen2.5:32b is already on this machine — 19GB, pulled five weeks ago — and
litellm_config.yaml already has an entry for it, commented out. The dashboard
already has a display name for it: "Qwen 2.5 32B (Free)". Everything was
present except the three lines that make it reachable.

── THE THREE CHANGES ────────────────────────────────────────────────────────

1. litellm_config.yaml serves local-heavy.

2. _LOCAL_MODEL becomes a setting rather than a literal:

       _LOCAL_MODEL = os.environ.get("DUCORN_LOCAL_MODEL", "local-fast")

   One env var, read where the local default is needed. The default stays
   local-fast so a machine without qwen keeps working.

3. The router stops being the shortest timeout in the chain.

       generate_design.RENDER_TIMEOUT = 900     what a render is allowed
       ducorn_proxy httpx timeout    = 300      what the router permits

   The outer limit was shorter than the inner one, so the 900s budget could
   never be reached. Harmless with an 8B model that answers in seconds;
   fatal with a 32B model rendering a full HTML page. It now defaults to 900
   and reads DUCORN_ROUTER_TIMEOUT.

── WHAT IS DELIBERATELY NOT CHANGED ─────────────────────────────────────────

skill_runner's SKILL_MODELS fallbacks still read "local-fast". They only
apply when SAGE_MODEL and friends are absent from the environment, and
_get_agent_models sets all of them before any skill runs. Changing an
unexercised path adds risk and proves nothing.

── WHAT TO EXPECT ───────────────────────────────────────────────────────────

Slow. A 32B model on an M4 Pro is minutes per skill, and a full phase may
take the better part of an hour. Slow and free beats fast and useless, and
nothing here is billed.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
CFG = DC / "scripts" / "litellm_config.yaml"
FLOW = DC / "ducorn" / "flows" / "langgraph_flow.py"
PROXY = DC / "scripts" / "ducorn_proxy.py"
ENVF = DC / "shared" / ".env"
LIB = DC / "scripts" / "patchlib.py"
TAG = "localheavy"

CFG_OLD = '''#  - model_name: local-heavy
#    litellm_params:
#      model: ollama/qwen2.5:32b
#      api_base: http://localhost:11434'''

CFG_NEW = '''  - model_name: local-heavy
    litellm_params:
      model: ollama/qwen2.5:32b
      api_base: http://localhost:11434'''

FLOW_OLD = '''_LOCAL_MODEL = "local-fast"'''

FLOW_NEW = '''# The model a TEST run uses. A setting, not a literal.
#
# local-fast is ollama/llama3.1 — 8B — and it cannot complete a G-Stack
# skill: it exhausts max_iter making tool calls and returns no final answer,
# which the runner records as "produced only 0 chars of substance". A free
# tier that cannot finish a run cannot prove the pipeline, which is its only
# purpose.
#
# The default stays local-fast so a machine without qwen2.5:32b is unaffected.
# shared/.env sets DUCORN_LOCAL_MODEL=local-heavy where it is available.
_LOCAL_MODEL = os.environ.get("DUCORN_LOCAL_MODEL", "local-fast")'''

PROXY_OLD = '''    async with httpx.AsyncClient(timeout=300) as client:'''

PROXY_NEW = '''    # Long enough for the slowest thing that goes through it.
    #
    # This was 300s while generate_design allows a render 900s, so the router
    # — the OUTER limit — was shorter than the budget it was carrying and the
    # inner one could never be reached. Invisible with an 8B model answering
    # in seconds; a guaranteed cut-off with a 32B model rendering a page.
    async with httpx.AsyncClient(timeout=_ROUTER_TIMEOUT) as client:'''

PROXY_CONST = '''

# Seconds a single upstream call may take. Must be >= the longest budget any
# caller sets, or the router truncates a call the caller still considers live:
# generate_design.RENDER_TIMEOUT is 900.
_ROUTER_TIMEOUT = float(os.environ.get("DUCORN_ROUTER_TIMEOUT", "900"))
'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in (CFG, FLOW, PROXY, LIB):
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

sys.path.insert(0, str(DC / "scripts"))
from patchlib import code_only, py_ok, PatchCheckFailed   # noqa: E402

print("patch_local_heavy\n")

# The model must actually be on this machine. Serving a config entry for a
# model Ollama does not have turns every test run into a 404.
r = subprocess.run(["ollama", "list"], capture_output=True, text=True)
if "qwen2.5:32b" not in r.stdout:
    sys.exit("NOTHING DONE — ollama does not list qwen2.5:32b. "
             "`ollama pull qwen2.5:32b` first (19GB, free).")
print("  ok  ollama has qwen2.5:32b")

cfg_src = CFG.read_text(encoding="utf-8")
flow_src = FLOW.read_text(encoding="utf-8")
proxy_src = PROXY.read_text(encoding="utf-8")

if "DUCORN_LOCAL_MODEL" in flow_src:
    sys.exit("NOTHING DONE — the local model is already a setting.")

bad = False
for label, hay, a in [("the commented local-heavy entry", cfg_src, CFG_OLD),
                      ("_LOCAL_MODEL", flow_src, FLOW_OLD),
                      ("the router's client", proxy_src, PROXY_OLD)]:
    n = hay.count(a)
    print(f"  {'ok ' if n == 1 else '!! '}{label}  ({n} match)")
    bad |= n != 1
if bad:
    sys.exit("\nNOTHING DONE — an anchor did not match exactly once.")

if "import os" not in proxy_src:
    sys.exit("NOTHING DONE — ducorn_proxy has no `import os`; the timeout "
             "setting would raise NameError at import.")
print("  ok  ducorn_proxy imports os")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
for f in (CFG, FLOW, PROXY):
    shutil.copy2(f, f.with_suffix(f".backup-{TAG}-{stamp}{f.suffix}"))

CFG.write_text(cfg_src.replace(CFG_OLD, CFG_NEW, 1), encoding="utf-8")
FLOW.write_text(flow_src.replace(FLOW_OLD, FLOW_NEW, 1), encoding="utf-8")

# The constant goes after the imports, before first use.
_m = re.search(r"^(import os.*?)$", proxy_src, re.M)
proxy_out = (proxy_src[:_m.end()] + PROXY_CONST + proxy_src[_m.end():]
             ).replace(PROXY_OLD, PROXY_NEW, 1)
PROXY.write_text(proxy_out, encoding="utf-8")
print(f"\nwrote litellm_config.yaml, langgraph_flow.py and ducorn_proxy.py, "
      f"backups tagged {TAG}-{stamp}")

for f in (FLOW, PROXY):
    try:
        py_ok(f.read_text(encoding="utf-8"), f.name)
    except PatchCheckFailed as e:
        sys.exit(f"⚠️  {e} — restore the backups.")

# YAML must still parse, or LiteLLM will not start at all.
try:
    import yaml
    served = [m["model_name"] for m in
              yaml.safe_load(CFG.read_text())["model_list"]]
except Exception as e:
    sys.exit(f"⚠️  litellm_config.yaml does not parse: {e} — restore the "
             f"backup, or LiteLLM will not start.")
if "local-heavy" not in served:
    sys.exit("⚠️  local-heavy is not in the served model list — restore the "
             "backups.")
print(f"verified: the config parses and serves {len(served)} models "
      f"including local-heavy.")

code = code_only(PROXY.read_text(encoding="utf-8"))
if "timeout=300" in code:
    sys.exit("⚠️  the router still hardcodes 300s — restore the backups.")
print("          the router timeout is a setting, defaulting to 900s.")

# shared/.env — appended, and read back.
env_txt = ENVF.read_text(encoding="utf-8") if ENVF.is_file() else ""
if "DUCORN_LOCAL_MODEL=" not in env_txt:
    shutil.copy2(ENVF, ENVF.with_name(f".env.backup-{TAG}-{stamp}"))
    with ENVF.open("a", encoding="utf-8") as fh:
        fh.write(f"\n# Test runs use this model. qwen2.5:32b — free, local, "
                 f"and able to finish a skill.\nDUCORN_LOCAL_MODEL=local-heavy\n")
    back = ENVF.read_text(encoding="utf-8")
    if "DUCORN_LOCAL_MODEL=local-heavy" not in back:
        sys.exit("⚠️  the setting did not land in shared/.env — restore "
                 f".env.backup-{TAG}-{stamp}.")
    print("          shared/.env now sets DUCORN_LOCAL_MODEL=local-heavy.")
else:
    print("          shared/.env already sets DUCORN_LOCAL_MODEL — left alone.")

print("""
  launchctl kickstart -k gui/$(id -u)/com.ducorn.litellm
  launchctl kickstart -k gui/$(id -u)/com.ducorn.router
  sleep 20
  curl -s localhost:4000/v1/models | grep -o local-heavy
  python3 scripts/doctor.py

doctor's "every agent's model is served by LiteLLM" is the check that matters
— it fails if the config and the router disagree.

Then re-run zz-plumbing-check phase 1 as TEST. It will be SLOW: minutes per
skill, possibly an hour for the phase. Every 💸 line should still read $0.00.
""")
