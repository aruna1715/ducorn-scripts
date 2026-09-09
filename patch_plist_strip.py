#!/usr/bin/env python3
"""
Move secret values out of the plists that can live without them.

    cd ~/DC && python3 scripts/patch_plist_strip.py            show
    cd ~/DC && python3 scripts/patch_plist_strip.py --apply    do it

Needs scripts/prove_plist_secrets.py.

── WHAT IT DOES ─────────────────────────────────────────────────────────────

For every job prove_plist_secrets marks SAFE, and only those:

    the value is ensured present in shared/.env under the same name
    the key is removed from the plist's EnvironmentVariables
    the plist is backed up first

MOVE, not copy. Leaving the value in both places is the situation this is
fixing, one file later.

── WHAT IT WILL NOT DO ──────────────────────────────────────────────────────

Decide safety. It imports analyse() from prove_plist_secrets and acts on that
verdict — the judgement lives in the tool you already read the output of, and
a second copy here would be a second answer to one question.

Touch a job whose entrypoint does not load shared/.env. Those need a change
to the product's own code first, and doing it here would produce a service
that starts fine and fails hours later on the first call needing the key.

Overwrite a differing value in shared/.env. That is reported and skipped.

Rotate anything. A key moved into shared/.env is the same key.

── NO VALUE IS EVER PRINTED ─────────────────────────────────────────────────

Only names, and a masked prefix. That rule exists because I broke it: reading
com.ducorn.slack.plist in full to copy its structure put seven live
credentials into a transcript.
"""
from __future__ import annotations

import argparse
import plistlib
import shutil
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
ENVFILE = DC / "shared" / ".env"
sys.path.insert(0, str(DC / "scripts"))

try:
    from prove_plist_secrets import analyse, mask, env_file
except ImportError:
    sys.exit("NOTHING DONE — scripts/prove_plist_secrets.py is not installed. "
             "This deliberately has no safety logic of its own.")

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

print("patch_plist_strip\n")

if not ENVFILE.is_file():
    sys.exit(f"NOTHING DONE — {ENVFILE} is not there. Moving a value into a "
             f"file that does not exist would delete it.")

rows = analyse()
safe = [r for r in rows if r["safe"]]
unsafe = [r for r in rows if not r["safe"]]

if not safe:
    sys.exit("NOTHING DONE — prove_plist_secrets marks no job safe to strip.")

envv = env_file()
plan = []          # (row, key, action)
for r in safe:
    for k in sorted(r["secrets"]):
        v = r["secrets"][k]
        if k in envv and envv[k] == v:
            plan.append((r, k, "already in shared/.env — remove from plist"))
        elif k in envv:
            plan.append((r, k, "SKIP: shared/.env holds a different value"))
        else:
            plan.append((r, k, "add to shared/.env, then remove from plist"))

for r in safe:
    print(f"── {r['label']}   ({r['detail']})")
    for row, k, action in plan:
        if row is r:
            print(f"     {k:<24} {mask(r['secrets'][k]):<22} {action}")
    print()

if unsafe:
    print("Left alone, because their own code does not read shared/.env:")
    for r in unsafe:
        print(f"  {r['label']:<38} {r['detail']}")
    print()

moves = [p for p in plan if not p[2].startswith("SKIP")]
adds = [p for p in plan if p[2].startswith("add")]
print(f"{len(moves)} key(s) would leave {len(safe)} plist(s); "
      f"{len(adds)} would be written into shared/.env first.")

if not args.apply:
    print("\nNothing written. Re-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

# shared/.env first, and backed up. A key removed from a plist before it is
# safely in the env file is a key that is simply gone.
if adds:
    shutil.copy2(ENVFILE, ENVFILE.with_name(f".env.backup-strip-{stamp}"))
    with ENVFILE.open("a", encoding="utf-8") as fh:
        fh.write(f"\n# moved out of launchd plists {stamp}\n")
        for r, k, _a in adds:
            fh.write(f"{k}={r['secrets'][k]}\n")
    print(f"\nwrote {len(adds)} setting(s) into shared/.env "
          f"(backup .env.backup-strip-{stamp})")

    # Read it BACK and confirm, before anything is deleted anywhere.
    again = env_file()
    lost = [k for r, k, _a in adds if again.get(k) != r["secrets"][k]]
    if lost:
        sys.exit(f"⚠️  {', '.join(lost)} did not land in shared/.env "
                 f"correctly. NOTHING was removed from any plist — restore "
                 f".env.backup-strip-{stamp} and tell me what the file "
                 f"looks like.")
    print("verified: every moved value reads back from shared/.env unchanged.")

touched = []
for r in safe:
    keys = [k for row, k, action in plan
            if row is r and not action.startswith("SKIP")]
    if not keys:
        continue
    pl = plistlib.loads(r["plist"].read_bytes())
    shutil.copy2(r["plist"],
                 r["plist"].with_suffix(f".backup-strip-{stamp}.plist"))
    for k in keys:
        pl.get("EnvironmentVariables", {}).pop(k, None)
    r["plist"].write_bytes(plistlib.dumps(pl))
    # Read back: a plist that no longer parses is a service that will not start.
    back = plistlib.loads(r["plist"].read_bytes())
    still = [k for k in keys if k in (back.get("EnvironmentVariables") or {})]
    if still:
        sys.exit(f"⚠️  {r['label']}: {', '.join(still)} are still in the "
                 f"plist — restore the backup.")
    touched.append((r["label"], len(keys)))
    print(f"  {r['label']}: removed {len(keys)} key(s)")

print(f"""
{sum(n for _, n in touched)} credential(s) are now in shared/.env only.

launchd has the OLD environment until each job is restarted:
""" + "\n".join(f"  launchctl kickstart -k gui/$(id -u)/{lbl}"
                for lbl, _ in touched) + """

Then check each one came back before moving on — a job that fails to read a
key fails on its first real call, not at start.

Still to do, and this does not touch them:
  · the backup plists in launchd/ hold copies of what they carried
  · rotating. A key moved into shared/.env is the same key.
""")
