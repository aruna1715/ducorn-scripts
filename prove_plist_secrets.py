#!/usr/bin/env python3
"""
Which launchd jobs carry secret VALUES, and which could survive losing them.

    cd ~/DC && python3 scripts/prove_plist_secrets.py

Reads. Changes nothing. Prints no secret values, ever — only the key names,
a four-character prefix and a length, which is enough to tell two keys apart
and not enough to use one.

── WHY ──────────────────────────────────────────────────────────────────────

com.ducorn.slack.plist holds seven live credentials as literal strings:
SLACK_BOT_TOKEN, SLACK_APP_TOKEN, ANTHROPIC_API_KEY, DEEPSEEK_API_KEY,
SERPER_API_KEY, LITELLM_KEY_ATLAS and DUCORN_API_TOKEN. Anything that can
read the file can read them, and every backup of that file carries them too —
this repo has twenty-odd .backup-*.plist files.

shared/.env already exists, is already the file the admin page is being built
to manage, and is already loaded by the processes that use ducorn_env.

── WHY THIS IS A REPORT AND NOT A PATCH ─────────────────────────────────────

Deleting a variable from a plist only works if the process reads it from
somewhere else. A job whose entrypoint never loads shared/.env would start
fine, run for hours, and fail on the first call that needed the key — the
worst possible shape of breakage, and one that a patch applying to sixteen
jobs at once would cause sixteen times.

So this answers, per job, three questions:

    is the value also in shared/.env, and is it the SAME value
    does this job's entrypoint load shared/.env at all
    is it therefore safe to strip

and the patch that follows will only touch the jobs where the answer is yes.

── WHAT IT DOES NOT DO ──────────────────────────────────────────────────────

Rotate anything. A key moved from a plist to shared/.env is the same key. If
it has leaked, it stays leaked, and this changes nothing about that.
"""
from __future__ import annotations

import plistlib
import re
from pathlib import Path

DC = Path("/Users/ducorn/DC")
LAUNCHD = DC / "launchd"
ENVFILE = DC / "shared" / ".env"

# Matched ANYWHERE in the name, not only at the end: LITELLM_KEY_ATLAS and
# DATABASE_URL both matter and neither ends in the word.
SECRETISH = re.compile(
    r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|DATABASE_URL", re.I)

# What "this process loads shared/.env" looks like in a DuCorn entrypoint.
LOADERS = re.compile(r"ducorn_env|load_ducorn_env|load_dotenv|dotenv")


def mask(v: str) -> str:
    """Enough to tell two values apart. Not enough to use one."""
    v = v or ""
    return f"{v[:4]}…({len(v)} chars)" if v else "(empty)"


def env_file() -> dict:
    out = {}
    if not ENVFILE.is_file():
        return out
    for line in ENVFILE.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def entrypoint(pl: dict):
    """The script a job runs, if it runs one."""
    for a in pl.get("ProgramArguments") or []:
        if isinstance(a, str) and a.endswith(".py"):
            return Path(a)
    return None


def loads_env(script) -> str:
    """
    Does this entrypoint read shared/.env?

    Answered from the file, one level only. A module that imports something
    that imports ducorn_env reads as "not obviously" — deliberately, because
    this decides whether it is safe to take a key away, and a guess in the
    permissive direction breaks a service hours later.
    """
    if script is None:
        return "no python entrypoint"
    if not script.is_file():
        return "entrypoint missing"
    text = script.read_text(errors="replace")
    if LOADERS.search(text):
        return "yes"
    return "not obviously"


def main() -> int:
    envv = env_file()
    print(f"shared/.env holds {len(envv)} settings\n")

    plists = sorted(p for p in LAUNCHD.glob("*.plist")
                    if ".backup-" not in p.name)
    backups = sorted(p for p in LAUNCHD.glob("*.plist")
                     if ".backup-" in p.name)

    safe, unsafe, exposed_keys = [], [], set()

    for path in plists:
        try:
            pl = plistlib.loads(path.read_bytes())
        except Exception as e:
            print(f"{path.name}: could not parse ({e})")
            continue

        env = pl.get("EnvironmentVariables") or {}
        secrets = {k: v for k, v in env.items()
                   if isinstance(v, str) and SECRETISH.search(k)}
        if not secrets:
            continue

        script = entrypoint(pl)
        verdict = loads_env(script)
        label = pl.get("Label", path.stem)
        print(f"── {label}")
        print(f"     runs      {script.name if script else '(not python)'}")
        print(f"     loads .env  {verdict}")

        all_matched = True
        for k in sorted(secrets):
            exposed_keys.add(k)
            v = secrets[k]
            if k not in envv:
                state = "NOT in shared/.env"
                all_matched = False
            elif envv[k] != v:
                state = "DIFFERS from shared/.env"
                all_matched = False
            else:
                state = "same as shared/.env"
            print(f"       {k:<24} {mask(v):<22} {state}")

        if verdict == "yes" and all_matched:
            safe.append(label)
            print("     → safe to strip: it reads the env file and every "
                  "value is already there")
        else:
            unsafe.append(label)
            why = []
            if verdict != "yes":
                why.append("its entrypoint does not obviously load the file")
            if not all_matched:
                why.append("a value is missing from or differs in shared/.env")
            print(f"     → NOT safe yet: {'; '.join(why)}")
        print()

    print("─" * 72)
    print(f"{len(exposed_keys)} distinct credential(s) sit in plists: "
          f"{', '.join(sorted(exposed_keys))}")
    print(f"{len(backups)} backup plist(s) in launchd/ carry copies of "
          f"whatever they held when they were made")
    print(f"safe to strip now  : {', '.join(safe) or '(none)'}")
    print(f"needs work first   : {', '.join(unsafe) or '(none)'}")
    print("""
Rotating comes first and this does not do it. A key moved into shared/.env
is the same key; if it has been seen, it stays seen.""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
