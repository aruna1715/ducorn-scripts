#!/usr/bin/env python3
"""
Serve Muse Glimmer as local-glimmer, and point test runs at it.

    cd ~/DC && python3 scripts/patch_local_glimmer.py            show
    cd ~/DC && python3 scripts/patch_local_glimmer.py --apply    do it

Needs scripts/patchlib.py.

── WHY A NEW NAME AND NOT A REPOINT ─────────────────────────────────────────

Repointing local-heavy at muse-glimmer would be one line and would need no
key grants. It would also make the name lie: local-heavy is Qwen everywhere
it is described, including in ducorn_classifier's comments and the
dashboard's label. A model that is not what its name says is how the switcher
stops being the single source of truth.

So: a second model, local-glimmer, with Qwen left in place. Both stay
available, which is what a campaign of test runs needs.

── local- IS NOT DECORATION ─────────────────────────────────────────────────

ducorn_proxy branches on `model.startswith("local-")` in two places — the
request timeout and the max_tokens cap. A model served as `muse-glimmer`
would be treated as REMOTE: the remote timeout, and no output cap. The prefix
is a contract, so this refuses any name without it.

── WHAT THIS DOES NOT DO ────────────────────────────────────────────────────

Grant the model to the agent keys. Adding a model to litellm_config.yaml
leaves it invisible to every per-agent key — /v1/models is filtered by the
CALLING key — which is the failure that cost an afternoon. The grant is a
separate, deliberate step and the commands are printed at the end.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
CFG = DC / "scripts" / "litellm_config.yaml"
ENVF = DC / "shared" / ".env"
LIB = DC / "scripts" / "patchlib.py"
TAG = "localglimmer"

MODEL_NAME = "local-glimmer"
OLLAMA_TAG = "muse-glimmer:30b-mlx"

CFG_OLD = '''  - model_name: local-heavy
    litellm_params:
      model: ollama/qwen2.5:32b
      api_base: http://localhost:11434'''

CFG_NEW = f'''  - model_name: local-heavy
    litellm_params:
      model: ollama/qwen2.5:32b
      api_base: http://localhost:11434

  # Meta's open agentic model, 30B, via Ollama's MLX engine on Apple Silicon.
  # The local- prefix is required: ducorn_proxy branches on it for the request
  # timeout and the max_tokens cap, so a name without it is served as remote.
  - model_name: {MODEL_NAME}
    litellm_params:
      model: ollama/{OLLAMA_TAG}
      api_base: http://localhost:11434'''

ENV_OLD = "DUCORN_LOCAL_MODEL=local-heavy"
ENV_NEW = f"DUCORN_LOCAL_MODEL={MODEL_NAME}"


def served(text: str) -> list:
    """
    model_name entries, parsed without PyYAML.

    The operator's python3 is 3.14 and has no yaml. A patch in this project
    imported it anyway, could not, and reported a working config as broken.
    """
    out = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#") or "model_name:" not in s:
            continue
        out.append(s.split("model_name:", 1)[1].strip().strip('"\''))
    return out


def ollama_models(text: str) -> list:
    """(model_name, ollama tag) for every entry backed by Ollama."""
    pairs, current = [], None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            continue
        if "model_name:" in s:
            current = s.split("model_name:", 1)[1].strip().strip('"\'')
        elif s.startswith("model:") and current:
            target = s.split("model:", 1)[1].strip()
            if target.startswith("ollama/"):
                pairs.append((current, target))
            current = None
    return pairs


ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in (CFG, ENVF, LIB):
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

print("patch_local_glimmer\n")

cfg_src = CFG.read_text(encoding="utf-8")
env_src = ENVF.read_text(encoding="utf-8")

if MODEL_NAME in cfg_src:
    sys.exit(f"NOTHING DONE — {MODEL_NAME} is already served.")

# The contract the router depends on.
if not MODEL_NAME.startswith("local-"):
    sys.exit(f"NOTHING DONE — {MODEL_NAME!r} has no local- prefix; "
             f"ducorn_proxy would treat it as a remote model.")
print(f"  ok  {MODEL_NAME} carries the local- prefix the router requires")

# The model must actually be on this machine, or every test run 404s.
r = subprocess.run(["ollama", "list"], capture_output=True, text=True)
if r.returncode != 0:
    sys.exit("NOTHING DONE — `ollama list` failed; is ollama running?")
if OLLAMA_TAG not in r.stdout:
    sys.exit(f"NOTHING DONE — ollama does not have {OLLAMA_TAG}.\n"
             f"  ollama pull {OLLAMA_TAG}")
print(f"  ok  ollama has {OLLAMA_TAG}")

bad = False
for label, hay, anchor in [("the local-heavy config entry", cfg_src, CFG_OLD),
                           ("DUCORN_LOCAL_MODEL in shared/.env", env_src,
                            ENV_OLD)]:
    n = hay.count(anchor)
    print(f"  {'ok ' if n == 1 else '!! '}{label}  ({n} match)")
    bad |= n != 1
if bad:
    sys.exit("\nNOTHING DONE — an anchor did not match exactly once.")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(CFG, CFG.with_name(f"litellm_config.backup-{TAG}-{stamp}.yaml"))
shutil.copy2(ENVF, ENVF.with_name(f".env.backup-{TAG}-{stamp}"))

CFG.write_text(cfg_src.replace(CFG_OLD, CFG_NEW, 1), encoding="utf-8")
ENVF.write_text(env_src.replace(ENV_OLD, ENV_NEW, 1), encoding="utf-8")
print(f"\nwrote litellm_config.yaml and shared/.env, backups tagged "
      f"{TAG}-{stamp}")

after_cfg = CFG.read_text(encoding="utf-8")
after_env = ENVF.read_text(encoding="utf-8")

names = served(after_cfg)
if MODEL_NAME not in names:
    sys.exit(f"⚠️  {MODEL_NAME} is not in the served list — restore the "
             f"backups.")
if len(names) != len(set(names)):
    dupes = sorted({n for n in names if names.count(n) > 1})
    sys.exit(f"⚠️  duplicate model_name entries {dupes} — LiteLLM would "
             f"serve one of them unpredictably. Restore the backups.")
print(f"verified: the config serves {len(names)} models including "
      f"{MODEL_NAME}.")

# Every Ollama-backed model must carry the prefix, not just the new one.
wrong = [n for n, t in ollama_models(after_cfg) if not n.startswith("local-")]
if wrong:
    sys.exit(f"⚠️  Ollama-backed models without a local- prefix: {wrong}. "
             f"The router would give them the remote timeout and no output "
             f"cap. Restore the backups.")
print(f"          every Ollama-backed model is named local-*.")

if f"DUCORN_LOCAL_MODEL={MODEL_NAME}" not in after_env:
    sys.exit(f"⚠️  shared/.env does not set DUCORN_LOCAL_MODEL={MODEL_NAME} — "
             f"restore .env.backup-{TAG}-{stamp}.")
if after_env.count("DUCORN_LOCAL_MODEL=") != 1:
    sys.exit(f"⚠️  shared/.env has "
             f"{after_env.count('DUCORN_LOCAL_MODEL=')} DUCORN_LOCAL_MODEL "
             f"lines; the last one would silently win. Restore the backup.")
print(f"          shared/.env sets DUCORN_LOCAL_MODEL={MODEL_NAME}, once.")

print(f"""
Three steps left, in this order. The grant is the one that has bitten before:
adding a model to the config leaves it INVISIBLE to every per-agent key.

  launchctl kickstart -k gui/$(id -u)/com.ducorn.litellm
  launchctl kickstart -k gui/$(id -u)/com.ducorn.router
  sleep 20

  python3 scripts/litellm_models.py --grant {MODEL_NAME} --apply

  python3 scripts/check_agent_models.py

The last one must end with

  ✅ every agent key can reach {MODEL_NAME}.

Qwen stays served as local-heavy. To go back, set DUCORN_LOCAL_MODEL=local-heavy
in shared/.env — no other change.
""")
