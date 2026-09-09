#!/usr/bin/env python3
"""
Run the reaper every five minutes.

    cd ~/DC && python3 scripts/install_reaper.py            show
    cd ~/DC && python3 scripts/install_reaper.py --apply    write the plist

Needs scripts/reap_runs.py and scripts/run_liveness.py.

── THE JOB ──────────────────────────────────────────────────────────────────

    com.ducorn.reaper   every 300s, one shot, exits immediately

It is the sixteenth launchd job on this machine and the first scheduled one —
every other is a long-running service with KeepAlive. This has no KeepAlive
on purpose: a script that exits in under a second and is restarted forever is
a busy loop, not a schedule.

── NO SECRETS IN IT ─────────────────────────────────────────────────────────

The existing plists carry live API keys as literal strings — SLACK_BOT_TOKEN,
ANTHROPIC_API_KEY and five more are sitting in com.ducorn.slack.plist right
now, readable by anything that can read the file, and copied into every
backup of it.

This one carries HOME and PYTHONPATH and nothing else. It does not need more:
ducorn_db connects to postgresql://localhost/ducorn as the local user, and
the reaper touches nothing else.

Stripping the values out of the OTHER plists is a separate job, and it is
worth doing — but rotate what has already leaked first, because a key moved
into shared/.env is still the same key.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
LAUNCHD = DC / "launchd"
PLIST = LAUNCHD / "com.ducorn.reaper.plist"
LIVE = Path.home() / "Library" / "LaunchAgents" / "com.ducorn.reaper.plist"
VENV = DC / "ducorn" / ".venv" / "bin" / "python"
NEEDED = [DC / "scripts" / "reap_runs.py", DC / "scripts" / "run_liveness.py"]
INTERVAL = 300

BODY = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.ducorn.reaper</string>
    <key>ProgramArguments</key>
    <array>
        <string>{VENV}</string>
        <string>-u</string>
        <string>{DC}/scripts/reap_runs.py</string>
        <string>--apply</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{DC}</string>
    <!-- No API keys. This job talks to postgresql://localhost/ducorn as the
         local user and to pgrep, and needs nothing else. -->
    <key>EnvironmentVariables</key>
    <dict>
        <key>HOME</key><string>/Users/ducorn</string>
        <key>PYTHONPATH</key><string>{DC}/scripts</string>
    </dict>
    <key>StandardOutPath</key>
    <string>{DC}/logs/reaper.log</string>
    <key>StandardErrorPath</key>
    <string>{DC}/logs/reaper.log</string>
    <!-- StartInterval, not KeepAlive: this exits in well under a second, and
         KeepAlive would restart it immediately, forever. -->
    <key>StartInterval</key><integer>{INTERVAL}</integer>
    <key>RunAtLoad</key><true/>
</dict>
</plist>
"""

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

print("install_reaper\n")

missing = [f for f in NEEDED if not f.is_file()]
if missing:
    sys.exit("NOTHING DONE — install these first:\n  "
             + "\n  ".join(str(m) for m in missing))
print("  ok  reap_runs.py and run_liveness.py are in scripts/")

if not VENV.exists():
    sys.exit(f"NOTHING DONE — {VENV} is not there. The reaper needs an "
             f"interpreter with psycopg2; the system python3 does not have it, "
             f"which is the mistake that made doctor produce nothing.")
print(f"  ok  {VENV.name} exists (system python3 has no psycopg2)")

# The job is only ever safe if the matching rules hold. Run their self-tests
# BEFORE scheduling something that writes to the database unattended.
for mod, flag in (("run_liveness.py", "--test"),):
    r = subprocess.run([str(VENV), str(DC / "scripts" / mod), flag],
                       capture_output=True, text=True)
    ok = "OK" in r.stdout and r.returncode == 0
    print(f"  {'ok ' if ok else '!! '}{mod} {flag}: {r.stdout.strip()[:60]}")
    if not ok:
        sys.exit(f"\nNOTHING DONE — {mod} does not pass its own tests. This "
                 f"job would run unattended every {INTERVAL}s and write to "
                 f"pipeline_runs; it is not going on a schedule until the "
                 f"matcher is right.\n{r.stderr[-300:]}")

# What it would do RIGHT NOW, before it is ever scheduled to do it.
r = subprocess.run([str(VENV), str(DC / "scripts" / "reap_runs.py")],
                   capture_output=True, text=True, cwd=str(DC))
print("\n  a dry run, right now:")
for line in (r.stdout or r.stderr).strip().splitlines():
    print(f"    {line}")

if not args.apply:
    print("\nRe-run with --apply to write the plist.")
    raise SystemExit(0)

LAUNCHD.mkdir(parents=True, exist_ok=True)
if PLIST.exists():
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy2(PLIST, PLIST.with_suffix(f".backup-{stamp}.plist"))
PLIST.write_text(BODY, encoding="utf-8")
print(f"\nwrote {PLIST}")

r = subprocess.run(["plutil", "-lint", str(PLIST)],
                   capture_output=True, text=True)
if r.returncode != 0:
    sys.exit(f"⚠️  the plist is malformed — do not load it:\n{r.stdout}{r.stderr}")
print("verified: plutil -lint accepts it.")

print(f"""
launchd reads from ~/Library/LaunchAgents, so link and load it:

  ln -sf {PLIST} {LIVE}
  launchctl bootstrap gui/$(id -u) {LIVE}
  launchctl list | grep ducorn.reaper

It runs once at load. Watch the first pass:

  tail -f {DC}/logs/reaper.log

To stop it:  launchctl bootout gui/$(id -u)/com.ducorn.reaper
""")
