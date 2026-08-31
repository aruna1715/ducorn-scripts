"""
Find an interpreter that has the modules a script needs, and re-run under it.

WHY THIS IS A MODULE AND NOT A COPIED BLOCK
-------------------------------------------
This Mac has at least four pythons and the libraries are spread across them:

    python3 on PATH        3.14, homebrew  — neither psycopg2 nor google-api
    python3.12             homebrew        — the Google API libraries
    ducorn/.venv/bin/python                — psycopg2, crewai, langgraph

So "run it with python3" is wrong about half the time, and which half depends
on the script. reorganize_drive.py grew a probe for this; migrate.py then hit
the identical wall with a different module and I nearly pasted the same twenty
lines into it. Two copies drift; this is the same argument as one router, one
model registry, one place that decides where a file goes in Drive.

USAGE
-----
    from bootstrap_python import ensure_modules
    ensure_modules("psycopg2")          # at the top, before importing them

If the current interpreter has them, this returns immediately and nothing
happens. Otherwise it finds one that does, says so, and re-execs. If nothing
on the machine has them it exits with the pip line you need, naming a real
interpreter rather than telling you to try the one that just failed.
"""
import glob
import os
import shutil
import subprocess
import sys

_GUARD = "_DUCORN_BOOTSTRAPPED"


def candidates():
    out = []
    for name in ("python3.12", "python3.11", "python3.13", "python3.10"):
        found = shutil.which(name)
        if found:
            out.append(found)
    out.append("/Users/ducorn/DC/ducorn/.venv/bin/python")
    out += sorted(glob.glob("/opt/homebrew/opt/python@3.*/bin/python3.*"))
    out += sorted(glob.glob("/opt/homebrew/bin/python3.1*"))
    out.append("/usr/bin/python3")
    return out


def _has(interpreter, modules):
    try:
        r = subprocess.run(
            [interpreter, "-c", "import " + ", ".join(modules)],
            capture_output=True, timeout=25)
        return r.returncode == 0
    except Exception:
        return False


def ensure_modules(*modules, pip=None):
    """
    Re-exec under an interpreter that can import every named module.

    `pip` is what to install if none has them, when that differs from the
    import name — googleapiclient is imported but google-api-python-client is
    installed, and printing the wrong one sends you to a pip error.
    """
    missing = []
    for m in modules:
        try:
            __import__(m)
        except ImportError:
            missing.append(m)
    if not missing:
        return

    if os.environ.get(_GUARD):
        # Already re-execed once. Something is inconsistent between the probe
        # and the real import; stop rather than bouncing between interpreters.
        sys.exit(f"Re-exec under {sys.executable} still cannot import "
                 f"{', '.join(missing)}. Stopping rather than looping.")

    seen = set()
    for c in candidates():
        if not os.path.exists(c):
            continue
        real = os.path.realpath(c)
        if real in seen:
            continue
        seen.add(real)
        if _has(c, modules):
            print(f"[bootstrap] {os.path.basename(sys.executable)} lacks "
                  f"{', '.join(missing)}; re-running under {c}\n")
            os.environ[_GUARD] = "1"
            os.execv(c, [c, os.path.abspath(sys.argv[0])] + sys.argv[1:])

    install = " ".join(pip or modules)
    sys.exit(
        f"No interpreter on this Mac can import {', '.join(missing)}.\n\n"
        f"Install into the one you want to use, e.g.:\n"
        f"  /Users/ducorn/DC/ducorn/.venv/bin/python -m pip install {install}\n"
        f"  python3.12 -m pip install {install}")
