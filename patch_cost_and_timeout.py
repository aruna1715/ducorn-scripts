#!/usr/bin/env python3
"""
Stop paying four times for a failure, and stop timing out a design that works.

── ONE: num_retries: 3 ──────────────────────────────────────────────────────

    scripts/litellm_config.yaml
      num_retries: 3

A call that fails is made four times. For a local model that is free and
usually pointless — llama3.1 failing once fails the same way three more times,
and each attempt holds Ollama's single slot for the full timeout. For a remote
model it is billed every time: a failing Sonnet call costs four Sonnet calls.

Tonight's spend is $27.22 across 92 calls, and a retried failure is invisible in
that number — it looks like traffic.

Three is a reasonable default for a flaky network. It is the wrong default for
a machine where most failures are a prompt too long, a model that is not
served, or a slot already busy. None of those get better on the fourth try.

Two, so a genuine blip is still absorbed.

── TWO: a 300-second remote timeout ─────────────────────────────────────────

    REMOTE_TIMEOUT = float(os.environ.get("DUCORN_REMOTE_TIMEOUT", "300"))

Design renders took 211 seconds of that 300 — 70% of the budget, on a call that
worked. A slightly larger design, or a slower afternoon at the provider, and a
successful render is killed at the wire and retried, which with num_retries: 3
is four expensive minutes to produce nothing.

420, which is 2× the longest render actually observed rather than a round
number chosen for feeling roomy.

Both are ceilings, not targets. Nothing gets slower because the ceiling moved;
things that were being cut off stop being cut off.
"""
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

CONFIG = Path("/Users/ducorn/DC/scripts/litellm_config.yaml")
ROUTER = Path("/Users/ducorn/DC/scripts/ducorn_proxy.py")

NEW_RETRIES = 2
NEW_REMOTE_TIMEOUT = 420

changed = []

# ── the retries ──────────────────────────────────────────────────────────────
cfg = CONFIG.read_text(encoding="utf-8")
m = re.search(r"^(\s*)num_retries:\s*(\d+)\s*$", cfg, re.M)
if not m:
    print(f"num_retries is not in {CONFIG.name} — skipping that half")
elif int(m.group(2)) == NEW_RETRIES:
    print(f"num_retries is already {NEW_RETRIES}")
else:
    was = int(m.group(2))
    backup = CONFIG.with_name(
        f"litellm_config.backup-retries-{datetime.now():%Y%m%d-%H%M%S}.yaml")
    backup.write_text(cfg, encoding="utf-8")
    new = cfg[:m.start()] + (
        f"{m.group(1)}# 2, not 3. A failed call is made num_retries+1 times and\n"
        f"{m.group(1)}# billed every time; most failures here are a prompt too\n"
        f"{m.group(1)}# long, a model not served, or Ollama's single slot busy,\n"
        f"{m.group(1)}# and none of those improve on the fourth attempt.\n"
        f"{m.group(1)}num_retries: {NEW_RETRIES}") + cfg[m.end():]
    CONFIG.write_text(new, encoding="utf-8")
    changed.append(f"num_retries {was} → {NEW_RETRIES}  "
                   f"({was + 1} attempts → {NEW_RETRIES + 1})")
    print(f"litellm_config.yaml: num_retries {was} → {NEW_RETRIES}   "
          f"(backup {backup.name})")

    # A YAML file that does not parse takes LiteLLM down on restart.
    try:
        import yaml  # noqa
        yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
        print("  ok   the config still parses as YAML")
    except ImportError:
        print("  ??   pyyaml not importable here — config not parse-checked")
    except Exception as e:
        CONFIG.write_text(cfg, encoding="utf-8")
        sys.exit(f"the edited config does not parse ({e}) — reverted")

# ── the timeout ──────────────────────────────────────────────────────────────
rtr = ROUTER.read_text(encoding="utf-8")
anchor = 'REMOTE_TIMEOUT = float(os.environ.get("DUCORN_REMOTE_TIMEOUT", "300"))'
if anchor not in rtr:
    if f'"DUCORN_REMOTE_TIMEOUT", "{NEW_REMOTE_TIMEOUT}"' in rtr:
        print(f"REMOTE_TIMEOUT is already {NEW_REMOTE_TIMEOUT}")
    else:
        print("REMOTE_TIMEOUT is not at its expected default — skipping")
else:
    backup = ROUTER.with_name(
        f"ducorn_proxy.backup-timeout-{datetime.now():%Y%m%d-%H%M%S}.py")
    backup.write_text(rtr, encoding="utf-8")
    ROUTER.write_text(rtr.replace(
        anchor,
        "# 420, not 300. A design render was measured at 211s — 70% of the old\n"
        "# budget, on a call that succeeded. A slightly larger page or a slower\n"
        "# afternoon and the wire is cut on work that was going to finish, then\n"
        "# retried at full price. This is a ceiling, not a target: nothing gets\n"
        "# slower because it moved.\n"
        f'REMOTE_TIMEOUT = float(os.environ.get("DUCORN_REMOTE_TIMEOUT", '
        f'"{NEW_REMOTE_TIMEOUT}"))', 1), encoding="utf-8")
    import ast
    try:
        ast.parse(ROUTER.read_text(encoding="utf-8"))
    except SyntaxError as e:
        ROUTER.write_text(rtr, encoding="utf-8")
        sys.exit(f"SYNTAX ERROR in the router ({e}) — reverted")
    r = subprocess.run([sys.executable, "-m", "pyflakes", str(ROUTER)],
                       capture_output=True, text=True)
    if [l for l in (r.stdout + r.stderr).splitlines() if "undefined name" in l]:
        ROUTER.write_text(rtr, encoding="utf-8")
        sys.exit("undefined name in the router — reverted")
    changed.append(f"REMOTE_TIMEOUT 300 → {NEW_REMOTE_TIMEOUT}s")
    print(f"ducorn_proxy.py: REMOTE_TIMEOUT 300 → {NEW_REMOTE_TIMEOUT}   "
          f"(backup {backup.name})")

    # The local timeout must stay below the remote one, or a local model gets
    # a budget it can never use and Ollama's slot is held past any use.
    lm = re.search(r'DUCORN_LOCAL_TIMEOUT", "(\d+)"', ROUTER.read_text())
    if lm and int(lm.group(1)) >= NEW_REMOTE_TIMEOUT:
        print(f"  ??   LOCAL_TIMEOUT is {lm.group(1)}s, not below the new "
              f"remote ceiling — worth a look")
    elif lm:
        print(f"  ok   LOCAL_TIMEOUT stays at {lm.group(1)}s, below the ceiling")

if not changed:
    print("\nNothing to change.")
    sys.exit(0)

print("\nchanged:")
for c in changed:
    print(f"  · {c}")
print("""
Both take effect on restart:

  launchctl kickstart -k gui/$(id -u)/com.ducorn.litellm
  launchctl kickstart -k gui/$(id -u)/com.ducorn.router

Then confirm the router is answering and nothing else moved:

  python3 scripts/doctor.py --quiet""")
