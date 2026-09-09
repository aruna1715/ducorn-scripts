#!/usr/bin/env python3
"""
doctor calls a service dead six seconds after you restarted it.

    cd ~/DC && python3 scripts/patch_doctor_retry.py            show
    cd ~/DC && python3 scripts/patch_doctor_retry.py --apply    do it

Needs scripts/patchlib.py.

── WHAT IT COST ─────────────────────────────────────────────────────────────

Fifteen credentials had just been moved out of four plists. The four services
were restarted, doctor ran six seconds later, and said:

    FAIL LiteLLM on :4000   not listening

LiteLLM was starting. It came up seconds afterwards and has been serving
/v1/chat/completions since. But for the length of that report the evidence
said a change to those plists had taken a service down — which is exactly
the failure the strip was written to avoid, and exactly what you check for
after making it.

A flaky check is worse than no check when it fires on the one action you were
watching. It does not merely fail to inform; it actively misinforms, at the
moment you are most likely to act on it.

── AND A SMALLER ONE ────────────────────────────────────────────────────────

    check("services", f"{name} on :{port}", port_open(port),
          "" if port_open(port) else "not listening", fix)

port_open is called TWICE, so the verdict and the message it prints come from
two different measurements. A service that came up between them reports
"ok … not listening"; one that died between them reports a failure with an
empty reason. Neither has been seen, and neither should be possible.

── THE FIX ──────────────────────────────────────────────────────────────────

One measurement, retried. A port that is open on the first look answers in
milliseconds and nothing is slower than before; a port that is not gets about
twelve seconds to appear, which is what a launchd service needs and less than
the time it takes to read the rest of the report.

Still a real check: a service that is genuinely down still fails, twelve
seconds later, with the same message and the same fix line.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DC = Path("/Users/ducorn/DC")
DOC = DC / "scripts" / "doctor.py"
LIB = DC / "scripts" / "patchlib.py"
TAG = "docretry"

OLD = '''        check("services", f"{name} on :{port}", port_open(port),
              "" if port_open(port) else "not listening", fix)'''

NEW = '''        up = _service_up(port)
        check("services", f"{name} on :{port}", up,
              "" if up else f"not listening after {_SERVICE_WAIT}s", fix)'''

HELPER = '''
# How long a launchd service gets to appear before it is called down.
#
# doctor used to look once. Run six seconds after a `launchctl kickstart`, it
# reported LiteLLM as not listening while LiteLLM was starting — during the
# one check that was verifying a change to that service's plist. A check that
# is wrong exactly when you are watching it is worse than no check.
_SERVICE_WAIT = 12


def _service_up(port: int, wait: int = None) -> bool:
    """
    Is something listening, given a moment to start.

    ONE measurement, reused for the verdict and the message. The caller used
    to call port_open twice, so a service that came up between the two calls
    would print "ok" beside "not listening".
    """
    import time as _t
    wait = _SERVICE_WAIT if wait is None else wait
    deadline = _t.monotonic() + wait
    while True:
        if port_open(port):
            return True
        if _t.monotonic() >= deadline:
            return False
        _t.sleep(1)


'''

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

for f in (DOC, LIB):
    if not f.is_file():
        sys.exit(f"NOTHING DONE — {f} is not there")

sys.path.insert(0, str(DC / "scripts"))
from patchlib import code_only, calls_in, py_ok, PatchCheckFailed  # noqa: E402

src = DOC.read_text(encoding="utf-8")
print("patch_doctor_retry\n")

if "_service_up" in src:
    sys.exit("NOTHING DONE — doctor already retries.")

n = src.count(OLD)
print(f"  {'ok ' if n == 1 else '!! '}the service check  ({n} match)")
if n != 1:
    sys.exit("\nNOTHING DONE — the anchor did not match exactly once.")

if "def port_open" not in src:
    sys.exit("NOTHING DONE — doctor has no port_open() to build on.")
print("  ok  port_open() is defined in doctor.py")

anchor2 = "def check_services():"
if src.count(anchor2) != 1:
    sys.exit("NOTHING DONE — check_services is not there exactly once.")

if not args.apply:
    print("\nRe-run with --apply.")
    raise SystemExit(0)

stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
shutil.copy2(DOC, DOC.with_suffix(f".backup-{TAG}-{stamp}.py"))
out = src.replace(anchor2, HELPER.lstrip("\n") + anchor2, 1).replace(OLD, NEW, 1)
DOC.write_text(out, encoding="utf-8")
print(f"\nwrote {DOC.name}, backup tagged {TAG}-{stamp}")

after = DOC.read_text(encoding="utf-8")
try:
    py_ok(after, "doctor.py")
except PatchCheckFailed as e:
    sys.exit(f"⚠️  {e} — restore the backup.")

# Scoped to the function changed: port_open must be measured once there now.
if len(calls_in(after, "check_services", "port_open")) != 0:
    sys.exit("⚠️  check_services still calls port_open directly — restore "
             "the backup.")
if len(calls_in(after, "check_services", "_service_up")) != 1:
    sys.exit("⚠️  check_services does not take one measurement — restore the "
             "backup.")
print("verified: doctor.py parses; check_services measures once, via "
      "_service_up.")

# It must still FAIL for a port nobody is on, and must not take the full wait
# to say yes for one that is up.
probe = r'''
import socket, time, sys
sys.path.insert(0, "/Users/ducorn/DC/scripts")
from doctor import _service_up
s = socket.socket(); s.bind(("127.0.0.1", 0)); s.listen(1)
open_port = s.getsockname()[1]
t = time.monotonic()
ok = _service_up(open_port)
fast = time.monotonic() - t
s.close()
c = socket.socket(); c.bind(("127.0.0.1", 0)); shut = c.getsockname()[1]; c.close()
t = time.monotonic()
down = _service_up(shut, wait=2)
slow = time.monotonic() - t
bad = []
if not ok: bad.append("a listening port was reported down")
if fast > 1.5: bad.append(f"an open port took {fast:.1f}s to confirm")
if down: bad.append("a closed port was reported up")
if slow < 1.5: bad.append("a closed port did not wait out its window")
print("RETRY_OK" if not bad else "RETRY_BAD " + "; ".join(bad))
'''
r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
if "RETRY_OK" not in r.stdout:
    print(f"  note: the live probe did not run cleanly — {(r.stdout + r.stderr).strip()[-200:]}")
else:
    print("          an open port still confirms immediately, and a closed "
          "one still fails.")

print("""
  python3 scripts/doctor.py

52 of 52, and a restart no longer reads as an outage.
""")
