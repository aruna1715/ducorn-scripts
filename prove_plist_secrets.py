#!/usr/bin/env python3
"""
Which launchd jobs carry secret VALUES, and which could survive losing them.

    cd ~/DC && python3 scripts/prove_plist_secrets.py

Reads. Changes nothing. Prints no secret values — only key names, a
four-character prefix and a length, which tells two keys apart and cannot be
used as one.

scripts/patch_plist_strip.py imports analyse() from here and acts only on
what it marks safe, so there is one judgement and not two.

── WHAT THE FIRST VERSION GOT WRONG ─────────────────────────────────────────

It looked for a .py in ProgramArguments and checked whether that file existed,
relative to wherever it happened to be run. That is not how these jobs start,
and it produced four wrong verdicts out of six:

    com.ducorn.api            ["python3.12", "main.py"] — a RELATIVE path,
                              resolved by launchd against WorkingDirectory.
                              Reported "entrypoint missing" for a file that
                              exists and a service that is running.
    com.ducorn.litellm        /bin/bash -c 'set -a; . shared/.env; exec …'
                              It sources the env file explicitly — the most
                              env-aware job on the machine, reported as
                              "no python entrypoint".
    the two uvicorn jobs      -m uvicorn main:app names a MODULE. The file is
                              there; the argument is not a path.
    ...-spend-status-web      -m http.server. It reads no environment at all,
                              so its DATABASE_URL is surplus rather than
                              needed — the opposite of the verdict given.

Every error was in the cautious direction, which is not a defence: a verdict
stronger than its evidence is wrong even when it happens to be safe, and the
next reader acts on it.

── WHAT IT ANSWERS NOW ──────────────────────────────────────────────────────

For each job, how it starts and therefore where its environment comes from:

    reads the env file    ducorn_env / load_dotenv in the resolved entrypoint,
                          or a shell wrapper that sources shared/.env
    needs no environment  http.server and friends — a static server that reads
                          nothing, so any credential on it is surplus
    does not              a real blocker: strip a key and it fails on the
                          first call that needed it, hours later

A value already in shared/.env under the same name is fine. A value that
DIFFERS is the one thing that stops a strip outright, because moving it would
change what the service gets.
"""
from __future__ import annotations

import plistlib
import re
from pathlib import Path

DC = Path("/Users/ducorn/DC")
LAUNCHD = DC / "launchd"
ENVFILE = DC / "shared" / ".env"

# Matched ANYWHERE in the name: LITELLM_KEY_ATLAS and DATABASE_URL both
# matter and neither ends in the word.
SECRETISH = re.compile(
    r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|DATABASE_URL", re.I)

LOADERS = re.compile(r"ducorn_env|load_ducorn_env|load_dotenv|dotenv")

# Module runners that read no environment of their own. Being wrong here is
# safe in the strict direction only — an entry NOT on this list is examined
# as code, never assumed.
NO_ENV_MODULES = {"http.server", "SimpleHTTPServer"}


def mask(v: str) -> str:
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


def _resolve(arg: str, wd: Path):
    """A ProgramArguments entry as a path, relative ones against WorkingDirectory."""
    p = Path(arg)
    return p if p.is_absolute() else (wd / p)


def entrypoint(pl: dict):
    """
    The file a job actually executes, and how it was worked out.

    Four shapes, because these jobs use four:
      python foo.py                 a path, possibly relative to WorkingDirectory
      python -m uvicorn a.b:app     a MODULE — a.b becomes a/b.py under the wd
      python -m http.server         a stdlib server that reads nothing
      /bin/bash -c '…'              a wrapper; the command string is the thing
    """
    args = [a for a in (pl.get("ProgramArguments") or []) if isinstance(a, str)]
    wd = Path(pl.get("WorkingDirectory") or DC)
    if not args:
        return None, "no ProgramArguments", None

    if args[0].endswith(("bash", "sh", "zsh")) and "-c" in args:
        cmd = args[args.index("-c") + 1] if args.index("-c") + 1 < len(args) else ""
        return None, "shell wrapper", cmd

    if "-m" in args:
        i = args.index("-m")
        mod = args[i + 1] if i + 1 < len(args) else ""
        if mod in NO_ENV_MODULES:
            return None, f"python -m {mod}", None
        if mod == "uvicorn":
            target = args[i + 2] if i + 2 < len(args) else ""
            dotted = target.split(":", 1)[0]
            return (wd / Path(*dotted.split("."))).with_suffix(".py"), \
                   f"uvicorn {target}", None
        return (wd / Path(*mod.split("."))).with_suffix(".py"), \
               f"python -m {mod}", None

    for a in args[1:]:
        if a.endswith(".py"):
            return _resolve(a, wd), a, None
    return None, " ".join(args[:2]), None


def env_source(pl: dict) -> tuple:
    """(verdict, detail). verdict is 'yes', 'not needed' or 'no'."""
    path, how, shell_cmd = entrypoint(pl)

    if shell_cmd is not None:
        if re.search(r"(^|;|\s)(\.|source)\s+\S*shared/\.env", shell_cmd):
            return "yes", "the wrapper sources shared/.env"
        return "no", "a shell wrapper that does not source shared/.env"

    if path is None:
        if how.startswith("python -m ") and how.split()[-1] in NO_ENV_MODULES:
            return "not needed", f"{how} reads no environment"
        return "no", f"could not identify an entrypoint ({how})"

    if not path.is_file():
        return "no", f"entrypoint {path} does not exist"
    if LOADERS.search(path.read_text(errors="replace")):
        return "yes", f"{path.name} loads the env file"
    return "no", f"{path.name} does not load the env file"


def analyse() -> list:
    """
    One record per job that carries a secret value. The single judgement.

    patch_plist_strip imports this rather than repeating it — a second copy
    of "is this safe to strip" is how two answers to one question start.
    """
    envv = env_file()
    out = []
    for path in sorted(p for p in LAUNCHD.glob("*.plist")
                       if ".backup-" not in p.name):
        try:
            pl = plistlib.loads(path.read_bytes())
        except Exception as e:
            out.append({"plist": path, "label": path.stem, "error": str(e),
                        "secrets": {}, "safe": False})
            continue

        env = pl.get("EnvironmentVariables") or {}
        secrets = {k: v for k, v in env.items()
                   if isinstance(v, str) and SECRETISH.search(k)}
        if not secrets:
            continue

        verdict, detail = env_source(pl)
        conflicts = [k for k, v in secrets.items()
                     if k in envv and envv[k] != v]
        out.append({
            "plist": path,
            "label": pl.get("Label", path.stem),
            "how": entrypoint(pl)[1],
            "reads_env": verdict,
            "detail": detail,
            "secrets": secrets,
            "in_env": {k: (k in envv) for k in secrets},
            "conflicts": conflicts,
            # Safe means: taking the key away does not break it, and moving
            # the value does not change what it gets.
            "safe": verdict in ("yes", "not needed") and not conflicts,
            "error": None,
        })
    return out


def main() -> int:
    envv = env_file()
    print(f"shared/.env holds {len(envv)} settings\n")
    rows = analyse()
    keys = set()

    for r in rows:
        print(f"── {r['label']}")
        if r["error"]:
            print(f"     could not parse: {r['error']}\n")
            continue
        print(f"     starts as   {r['how']}")
        print(f"     environment {r['reads_env']} — {r['detail']}")
        for k in sorted(r["secrets"]):
            keys.add(k)
            state = ("differs from shared/.env" if k in r["conflicts"]
                     else "already in shared/.env" if r["in_env"][k]
                     else "not yet in shared/.env — would be moved there")
            print(f"       {k:<24} {mask(r['secrets'][k]):<22} {state}")
        print(f"     → {'SAFE to strip' if r['safe'] else 'NOT safe'}"
              + ("" if r["safe"] else f": {r['detail']}"
                 + (f"; conflicting values: {', '.join(r['conflicts'])}"
                    if r["conflicts"] else "")))
        print()

    backups = [p for p in LAUNCHD.glob("*.plist") if ".backup-" in p.name]
    safe = [r["label"] for r in rows if r["safe"]]
    unsafe = [r["label"] for r in rows if not r["safe"]]
    print("─" * 72)
    print(f"{len(keys)} distinct credential(s) in plists: {', '.join(sorted(keys))}")
    print(f"{len(backups)} backup plist(s) in launchd/ hold copies of "
          f"whatever they carried when they were made")
    print(f"safe to strip : {', '.join(safe) or '(none)'}")
    print(f"not safe      : {', '.join(unsafe) or '(none)'}")
    print("""
A job marked NOT safe needs its own code to load shared/.env before its keys
can move. That is a change to that product, not to its plist.

Rotating is separate and comes first. A key moved into shared/.env is the
same key.""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
