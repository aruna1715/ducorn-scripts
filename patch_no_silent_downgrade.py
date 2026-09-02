#!/usr/bin/env python3
"""
A production run must never quietly become a cheap one.

── THREE PLACES THAT GUESS "test" WHEN THEY CANNOT TELL ─────────────────────

    _pin_local_for_test_runs
        except Exception as e:
            print(f"⚠️  Could not read environment ... — defaulting to test")
            env_name = "test"          → DUCORN_LOCAL_ONLY=1, everything local

    _load_run_settings
        except Exception as e:
            print(f"⚠️  Could not read run settings ... — assuming no UI")
            return {..., "environment": "test"}

    _get_agent_models
        except Exception as e:
            print(f"⚠️  Could not read agent config ... — defaulting to local-fast")
            return {f"{a}_MODEL": _LOCAL_MODEL for a in _AGENTS}

Each is one line of warning followed by a full run. A momentary database hiccup
or an activity API restarting mid-run, and a production build is written
end-to-end by llama3.1 instead of the model you chose. It does not fail. It
produces a document, passes QA, deploys, and reads like something written by a
much smaller model — which you discover by reading it.

For the tech-stack document that is the whole risk: the failure mode is not a
crash, it is a plausible document.

── THE DISTINCTION THAT MAKES THE FIX SAFE ──────────────────────────────────

There are two different situations behind those except blocks, and treating
them the same is the bug:

  NO ROW      Someone ran the CLI on a topic the dashboard has never seen.
              Real, ordinary, and 'test' is the right, cheap, safe default.
              Every manual run tonight was one of these. Unchanged.

  AN ERROR    The database or the API did not answer. Nothing is known. The
              old code answered anyway.

A missing row is information. An exception is the absence of information, and
you cannot default your way out of that — not when the default silently spends
a different amount of money and produces a different quality of work.

So: no row keeps today's behaviour exactly. An error stops the run, names what
could not be read, and says what to do about it.

── AND ONE THING THAT CANNOT DEFAULT AT ALL ─────────────────────────────────

Once the environment IS known to be production, _get_agent_models failing to
reach the switcher is fatal rather than local-fast. The switcher is the single
source for model choice — you have said so repeatedly — and "the source was
unreachable so I picked one" is not a fallback, it is the switcher not being
the source.

A test run keeps the local default in every case. It is meant to be cheap.
"""
import ast
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

FLOW = Path("/Users/ducorn/DC/ducorn/flows/langgraph_flow.py")
s = FLOW.read_text(encoding="utf-8")

if "DUCORN_ENVIRONMENT" in s:
    sys.exit("Already patched — a production run cannot silently downgrade.")

applied = []


def swap(label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {text.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    applied.append(label)
    return text.replace(old, new, 1)


# ── 1. resolving the environment: no row is fine, an error is not ────────────
s = swap("pin local", s, '''    try:
        from ducorn_db import get_conn
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT environment FROM pipeline_runs WHERE slug=%s", (topic,))
            row = cur.fetchone()
        env_name = (row[0] if row else None) or "test"
    except Exception as e:
        print(f"⚠️  Could not read environment for '{topic}' ({e}) — defaulting to test")
        env_name = "test"''',
         '''    try:
        from ducorn_db import get_conn
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT environment FROM pipeline_runs WHERE slug=%s", (topic,))
            row = cur.fetchone()
        # No row is information: the dashboard has never seen this topic, which
        # is what a manual CLI run looks like. 'test' is the right cheap
        # default and this is unchanged.
        env_name = (row[0] if row else None) or "test"
        if not row:
            print(f"ℹ️  no pipeline_runs row for '{topic}' — treating this as a "
                  f"test run")
    except Exception as e:
        # An exception is the ABSENCE of information. Defaulting to test here
        # means a production run silently executes on local models: it does not
        # fail, it produces a plausible document written by a much smaller
        # model, and you find out by reading it.
        raise RuntimeError(
            f"Could not read the environment for '{topic}': {e}\\n"
            f"Refusing to guess. A wrong guess here runs production on local "
            f"models without failing.\\n"
            f"  check the database:  python3 scripts/doctor.py --quiet\\n"
            f"  or force it:         DUCORN_ENVIRONMENT=test <command>"
        ) from e''')

# ── 2. once known, downstream can stop guessing too ──────────────────────────
s = swap("export environment", s, '''    if env_name != "production":
        os.environ["DUCORN_LOCAL_ONLY"] = "1"
        print(f"🔒 environment={env_name} — all agents pinned to local models")
    else:
        os.environ.pop("DUCORN_LOCAL_ONLY", None)''',
         '''    # Recorded so every later step knows what kind of run this is without
    # asking the database again — and so _get_agent_models knows that a
    # failure to reach the switcher is fatal rather than a reason to pick a
    # model itself.
    os.environ["DUCORN_ENVIRONMENT"] = env_name

    if env_name != "production":
        os.environ["DUCORN_LOCAL_ONLY"] = "1"
        print(f"🔒 environment={env_name} — all agents pinned to local models")
    else:
        os.environ.pop("DUCORN_LOCAL_ONLY", None)''')

# ── 3. the switcher is the source, or the run stops ──────────────────────────
s = swap("agent models", s, '''    except Exception as e:
        print(f"⚠️  Could not read agent config: {e} — defaulting all to {_LOCAL_MODEL}")
        return {f"{a}_MODEL": _LOCAL_MODEL for a in _AGENTS}''',
         '''    except Exception as e:
        # On a production run this cannot be defaulted. The switcher is the
        # single source for model choice; "the source was unreachable so I
        # chose one" is not a fallback, it is the switcher not being the
        # source. A test run stays cheap, which is what it is for.
        if os.environ.get("DUCORN_ENVIRONMENT") == "production":
            raise RuntimeError(
                f"Could not read the model switcher: {e}\\n"
                f"This is a PRODUCTION run and every agent would silently drop "
                f"to {_LOCAL_MODEL}.\\n"
                f"  is the API up?  launchctl kickstart -k "
                f"gui/$(id -u)/com.ducorn.api\\n"
                f"  then:           python3 scripts/doctor.py --quiet"
            ) from e
        print(f"⚠️  Could not read agent config: {e} — defaulting all to "
              f"{_LOCAL_MODEL} (test run)")
        return {f"{a}_MODEL": _LOCAL_MODEL for a in _AGENTS}''')

# ── 4. run settings: same distinction ────────────────────────────────────────
s = swap("run settings", s, '''    except Exception as e:
        # Deliberately NOT defaulting has_ui to True. Generating designs nobody
        # asked for costs money; skipping them is visible and recoverable.
        print(f"⚠️  Could not read run settings for '{topic}' ({e}) — assuming no UI")
        return {"has_ui": False, "design_model": None, "environment": "test"}''',
         '''    except Exception as e:
        # has_ui=False on a missing row is still right — generating designs
        # nobody asked for costs money, and skipping them is visible and
        # recoverable. But claiming environment="test" when the read FAILED is
        # an assertion this code cannot support, and it is the expensive half.
        raise RuntimeError(
            f"Could not read run settings for '{topic}': {e}\\n"
            f"Refusing to assume this is a test run — that decides which "
            f"models the whole run uses.\\n"
            f"  python3 scripts/doctor.py --quiet"
        ) from e''')

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = FLOW.with_name(f"langgraph_flow.backup-nodowngrade-{stamp}.py")
shutil.copy2(FLOW, backup)
FLOW.write_text(s, encoding="utf-8")


def die(msg):
    shutil.copy2(backup, FLOW)
    sys.exit(f"{msg} — reverted from {backup.name}")


try:
    ast.parse(s)
except SyntaxError as e:
    die(f"SYNTAX ERROR ({e})")

r = subprocess.run([sys.executable, "-m", "pyflakes", str(FLOW)],
                   capture_output=True, text=True)
if [l for l in (r.stdout + r.stderr).splitlines() if "undefined name" in l]:
    die("undefined name:\\n" + r.stdout + r.stderr)
print("syntax and undefined-name checks: clean")

# ── the four branches, as a decision table ───────────────────────────────────
src = FLOW.read_text(encoding="utf-8")


def mirror(situation, env_known):
    """Mirrors the patched branches, for a table you can read."""
    if situation == "no row":
        return "test run, local models — unchanged"
    if situation == "db error":
        return "STOPS with the reason"
    if situation == "switcher unreachable":
        return ("STOPS — production must not pick its own model"
                if env_known == "production" else "local models (test run)")
    return "?"


print("\nwhat happens when something cannot be read:")
CASES = [
    ("no row", None, "a manual CLI run on a fresh topic"),
    ("db error", None, "postgres blinked"),
    ("switcher unreachable", "production", "the API restarted mid-run"),
    ("switcher unreachable", "test", "same, on a test run"),
]
for situation, env, why in CASES:
    print(f"  {situation:22} {str(env or '—'):11} → "
          f"{mirror(situation, env):46} {why}")

for must, why in [
    ('os.environ["DUCORN_ENVIRONMENT"] = env_name',
     "the environment is recorded for later steps"),
    ('if os.environ.get("DUCORN_ENVIRONMENT") == "production":',
     "the switcher failure is fatal only in production"),
    # Short enough that the emitted f-string cannot wrap through it. Checking
    # for 'treating this as a test run' failed on correct code, because the
    # generated source breaks the line mid-phrase. Fifth time tonight.
    ("no pipeline_runs row for",
     "a missing row still says so out loud"),
]:
    if must not in src:
        die(f"missing: {why}")
    print(f"  ok   {why}")

if 'print(f"⚠️  Could not read environment for' in src:
    die("the silent environment default is still there")
print("  ok   no path silently claims 'test' after a failed read")

print("\napplied: " + ", ".join(applied))
print(f"backup:  {backup.name}")
print()
print("Nothing to restart. A manual CLI run behaves exactly as before — it")
print("just says so:")
print("  ℹ️  no pipeline_runs row for 'x' — treating this as a test run")
