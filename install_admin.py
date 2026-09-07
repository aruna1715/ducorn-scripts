#!/usr/bin/env python3
"""
Install the DuCorn Admin service.

    python3 scripts/install_admin.py            show what it would do
    python3 scripts/install_admin.py --apply    do it

── WHAT IT CREATES ──────────────────────────────────────────────────────────

    ducorn-products/products/ducorn-admin/main.py        the API
    ducorn-products/products/ducorn-admin/index.html     the page
    ducorn-products/products/ducorn-admin/requirements.txt
    ducorn-products/products/ducorn-admin/.venv          fastapi + uvicorn
    launchd/com.ducorn.admin.plist                       the service

Both main.py and index.html must already be beside this script, as
admin_main.py and admin_index.html.

── ONE DELIBERATE DIFFERENCE FROM YOUR OTHER SERVICES ───────────────────────

Every other DuCorn service binds 0.0.0.0 — reachable from anything on the LAN.
That is fine for a status page. It is not fine for a page that edits API keys,
because Cloudflare Access protects the TUNNEL and not the local network.

This one binds 127.0.0.1. Consequences, both real:

  · from the Mac itself:  http://localhost:8099  works
  · from your phone/LAN:  refused, by the kernel, before any password

If you want it on your phone later, the answer is a Cloudflare tunnel route —
which puts it behind the same Access login you already use, rather than
opening it to the LAN. Changing the plist to 0.0.0.0 would work too, and
would undo the point of this line.

HTTP Basic against UI_USERNAME / UI_PASSWORD applies either way.
"""
import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

DC = Path(os.environ.get("DUCORN_ROOT", "/Users/ducorn/DC"))
HERE = Path(__file__).resolve().parent
PRODUCT = DC / "ducorn-products" / "products" / "ducorn-admin"
PLIST = DC / "launchd" / "com.ducorn.admin.plist"
LABEL = "com.ducorn.admin"
PORT = 8099
PY312 = "/opt/homebrew/bin/python3.12"

REQS = "fastapi==0.115.6\nuvicorn[standard]==0.30.3\npydantic==2.12.5\n"

PLIST_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{PRODUCT}/.venv/bin/python</string>
        <string>-m</string>
        <string>uvicorn</string>
        <string>main:app</string>
        <string>--host</string>
        <string>127.0.0.1</string>
        <string>--port</string>
        <string>{PORT}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{PRODUCT}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>HOME</key>
        <string>{DC.parent}</string>
        <key>PYTHONPATH</key>
        <string>{DC}/scripts</string>
        <key>DUCORN_ROOT</key>
        <string>{DC}</string>
    </dict>
    <key>StandardOutPath</key>
    <string>{DC}/logs/admin.out.log</string>
    <key>StandardErrorPath</key>
    <string>{DC}/logs/admin.out.log</string>
    <key>KeepAlive</key><true/>
    <key>RunAtLoad</key><true/>
    <key>ThrottleInterval</key><integer>10</integer>
</dict>
</plist>
"""

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()

src_api = HERE / "admin_main.py"
src_html = HERE / "admin_index.html"
missing = [str(p) for p in (src_api, src_html) if not p.is_file()]
if missing:
    sys.exit("NOTHING DONE — these must be beside this script:\n  "
             + "\n  ".join(missing))

# ── credentials must exist, or the service refuses to run anyway ─────────────
sys.path.insert(0, str(DC / "scripts"))
try:
    import ducorn_envfile
    env = ducorn_envfile.effective()
except Exception as e:
    sys.exit(f"NOTHING DONE — ducorn_envfile.py will not load: {e}")

if not env.get("UI_USERNAME") or not env.get("UI_PASSWORD"):
    sys.exit("NOTHING DONE — UI_USERNAME and UI_PASSWORD must be set in "
             "shared/.env. The admin service refuses to start without them.")

print(f"DuCorn Admin → {PRODUCT}\n")
print(f"  {'product directory':26} {PRODUCT}")
print(f"  {'launchd job':26} {LABEL}")
print(f"  {'bind':26} 127.0.0.1:{PORT}   (localhost only — see the docstring)")
print(f"  {'login':26} UI_USERNAME / UI_PASSWORD from shared/.env")
print(f"  {'user':26} {env['UI_USERNAME']}")

if PLIST.is_file():
    print(f"\n  note: {PLIST.name} already exists and will be replaced")

# ── does the page even load? ─────────────────────────────────────────────────
# A page whose top-level code throws is dead in every tab, and neither
# `node --check` nor this installer's own byte comparison can see it — the
# file is valid JavaScript that happens to explode when run. Installing one
# is strictly worse than not installing: the old working page is replaced by
# a blank screen. So this gates the install rather than warning after it.
checker = HERE / "prove_admin_page.js"
node = shutil.which("node")

if not checker.is_file():
    print(f"\n⚠️  {checker.name} is not beside this script — the page will be "
          f"installed WITHOUT being loaded first.")
elif not node:
    print("\n⚠️  node is not on PATH — the page will be installed WITHOUT "
          "being loaded first.\n     brew install node, then re-run, to get "
          "this check back.")
else:
    r = subprocess.run([node, str(checker), str(src_html)],
                       capture_output=True, text=True, timeout=60)
    out = (r.stdout + r.stderr).strip()
    if r.returncode != 0:
        sys.exit(f"""
NOTHING DONE — {src_html.name} does not load.

  {out}

Installing this would replace a working page with a blank one. Fix the page
and re-run; nothing has been written.
""")
    print(f"\n  page loads   {out}")

if not args.apply:
    print("\nRe-run with --apply to install.")
    raise SystemExit(0)

# ── write ────────────────────────────────────────────────────────────────────
PRODUCT.mkdir(parents=True, exist_ok=True)
(DC / "logs").mkdir(parents=True, exist_ok=True)
shutil.copy2(src_api, PRODUCT / "main.py")
shutil.copy2(src_html, PRODUCT / "index.html")
(PRODUCT / "requirements.txt").write_text(REQS, encoding="utf-8")

# What actually landed. "wrote index.html" is not evidence that the file the
# service will serve is the file you just edited — a stale copy, a half write
# or a copy into the wrong tree all print the same sentence.
def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:12]


for src, dst in ((src_api, PRODUCT / "main.py"),
                 (src_html, PRODUCT / "index.html")):
    if sha(src) != sha(dst):
        sys.exit(f"the copy of {dst.name} does not match {src} — stop.")

html = src_html.read_text(encoding="utf-8", errors="replace")
tabs = re.findall(r'data-tab="([a-z]+)"', html)
print(f"\nwrote main.py, index.html, requirements.txt")
print(f"  page  {sha(src_html)}  ·  tabs: {', '.join(tabs) or 'NONE FOUND'}")

# ── venv ─────────────────────────────────────────────────────────────────────
venv_py = PRODUCT / ".venv" / "bin" / "python"
if not venv_py.exists():
    base = PY312 if Path(PY312).exists() else sys.executable
    print(f"creating .venv with {base} …")
    r = subprocess.run([base, "-m", "venv", str(PRODUCT / ".venv")],
                       capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        sys.exit(f"venv failed:\n{r.stderr[-600:]}")

print("installing fastapi, uvicorn, pydantic …")
r = subprocess.run([str(venv_py), "-m", "pip", "install", "-q", "-r",
                    "requirements.txt"], cwd=str(PRODUCT),
                   capture_output=True, text=True, timeout=600)
if r.returncode != 0:
    sys.exit(f"pip failed:\n{r.stderr[-800:]}")

# ── the service ──────────────────────────────────────────────────────────────
PLIST.parent.mkdir(parents=True, exist_ok=True)
PLIST.write_text(PLIST_XML, encoding="utf-8")
agents = Path.home() / "Library" / "LaunchAgents"
agents.mkdir(parents=True, exist_ok=True)
link = agents / PLIST.name
# COPIED, not symlinked. launchctl bootstrap returned "5: Input/output error"
# on a symlinked plist and left the job unloaded — the service had already been
# booted out, so it stayed down.
try:
    if link.exists() or link.is_symlink():
        link.unlink()
    shutil.copy2(PLIST, link)
except OSError as e:
    sys.exit(f"could not write {link}: {e}\n"
             f"Copy it by hand, then:\n"
             f"  launchctl bootstrap gui/$(id -u) {link}")

uid = os.getuid()
import time


def lc(*a, timeout=30):
    return subprocess.run(["launchctl", *a], capture_output=True, text=True,
                          timeout=timeout)


# 1 ── is the file launchd is being handed even valid? EIO on bootstrap is
#      what a malformed plist looks like from the outside.
lint = subprocess.run(["plutil", "-lint", str(link)],
                      capture_output=True, text=True)
if lint.returncode != 0:
    sys.exit(f"the plist is malformed — launchd cannot read it:\n"
             f"  {(lint.stdout + lint.stderr).strip()[:300]}\n"
             f"  {link}")

# 2 ── a label in launchd's disabled list bootstraps with EIO and no
#      explanation. `bootout -w`, `unload -w` and `disable` all put it there,
#      and it survives reboots and reinstalls — which is why reinstalling
#      "the same way that worked last time" stops working.
dis = lc("print-disabled", f"gui/{uid}")
disabled = f'"{LABEL}" => disabled' in dis.stdout or \
           f'"{LABEL}" => true' in dis.stdout
if disabled:
    print(f"{LABEL} is in launchd's disabled list — enabling it")
    lc("enable", f"gui/{uid}/{LABEL}")

# 3 ── two plists claiming one label is the other EIO. Find them.
#      NOT counting this installer's own pair: launchd/com.ducorn.admin.plist
#      is the source and LaunchAgents/com.ducorn.admin.plist is the copy of
#      it, so they always both declare the label. Warning on that fired on
#      every single run — and a warning that is always wrong is how the one
#      real duplicate gets ignored when it finally appears.
dupes = []
for d in (agents, DC / "launchd", Path("/Library/LaunchAgents")):
    try:
        for p in d.glob("*.plist"):
            if p in (link, PLIST):
                continue
            try:
                if f"<string>{LABEL}</string>" in p.read_text(errors="replace"):
                    dupes.append(p)
            except OSError:
                pass
    except OSError:
        pass
if dupes:
    print(f"⚠️  another plist declares Label {LABEL}. launchd will not "
          f"bootstrap two:")
    for p in dupes:
        print(f"      {p}")

# 4 ── bootout, then WAIT for it to be gone. Bootstrapping a label that is
#      still tearing down is the third EIO, and the old code did exactly that:
#      bootout and bootstrap back to back, with no check in between.
lc("bootout", f"gui/{uid}/{LABEL}")
for _ in range(15):
    if lc("print", f"gui/{uid}/{LABEL}").returncode != 0:
        break                     # gone
    time.sleep(1)
else:
    print(f"⚠️  {LABEL} is still registered after 15s of waiting")

# 5 ── now bootstrap, and retry rather than declaring defeat on one EIO
boot = None
for attempt in range(1, 4):
    boot = lc("bootstrap", f"gui/{uid}", str(link))
    if boot.returncode == 0:
        break
    msg = (boot.stdout + boot.stderr).strip()[:160]
    print(f"   bootstrap attempt {attempt}/3: {msg}")
    time.sleep(2)

if boot is not None and boot.returncode != 0:
    print(f"\n⚠️  bootstrap failed three times. Diagnostics:")
    print(f"      plist       {link}  (plutil: valid)")
    print(f"      disabled    {'was disabled, enabled above' if disabled else 'no'}")
    print(f"      duplicates  {len(dupes)}")
    pr = lc("print", f"gui/{uid}/{LABEL}")
    print(f"      print       {(pr.stdout + pr.stderr).strip()[:200]}")

lc("kickstart", "-k", f"gui/{uid}/{LABEL}")

# Did it actually start? The previous version printed "installed and started"
# unconditionally — including the run where bootstrap failed and the service
# stayed down. A success message that is not gated on a result is not a
# success message.
time.sleep(2)
check = subprocess.run(["launchctl", "list", LABEL],
                       capture_output=True, text=True)
if check.returncode != 0:
    log = DC / "logs" / "admin.out.log"
    tail = ""
    try:
        tail = "\n".join(log.read_text(errors="replace").splitlines()[-25:])
    except OSError:
        tail = "(no log yet — it never got far enough to write one)"
    sys.exit(f"""
INSTALLED, BUT NOT RUNNING — launchctl does not have {LABEL} loaded.

  {(check.stdout + check.stderr).strip()[:200]}

Last 25 lines of {log.name} — if uvicorn started and died, the reason is here:

{tail}

By hand:
  launchctl enable    gui/{uid}/{LABEL}
  launchctl bootstrap gui/{uid} {link}
  launchctl kickstart -k gui/{uid}/{LABEL}
  tail -f {log}

Or run it in the foreground, which prints the real error immediately:
  cd {PRODUCT} && PYTHONPATH={DC}/scripts DUCORN_ROOT={DC} \\
    .venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port {PORT}
""")

pid = ""
for line in check.stdout.splitlines():
    if '"PID"' in line:
        pid = line.split("=")[-1].strip().rstrip(";")

# ── does the RUNNING service serve the page we just installed? ───────────────
# Loaded and listening is not the same as serving the right file. The Logs tab
# was added, the installer said "installed and running", and the page had no
# Logs tab — because the new index.html had never reached scripts/ at all.
# Nothing in the install checked, so nothing said so.
import base64
import urllib.error
import urllib.request

served = None
for attempt in range(6):
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}/")
        tok = base64.b64encode(
            f"{env['UI_USERNAME']}:{env['UI_PASSWORD']}".encode()).decode()
        req.add_header("Authorization", "Basic " + tok)
        with urllib.request.urlopen(req, timeout=5) as resp:
            served = resp.read().decode("utf-8", "replace")
        break
    except (urllib.error.URLError, OSError):
        time.sleep(1)

if served is None:
    print(f"\n⚠️  the service is loaded but did not answer on :{PORT}. "
          f"Check {DC}/logs/admin.out.log")
else:
    served_tabs = re.findall(r'data-tab="([a-z]+)"', served)
    if served_tabs != tabs:
        sys.exit(f"""
INSTALLED, BUT SERVING A DIFFERENT PAGE.

  on disk   {', '.join(tabs)}
  served    {', '.join(served_tabs) or '(none)'}

The running service is not showing the file you just installed. Restart it
and look at the log:
  launchctl kickstart -k gui/{uid}/{LABEL}
  tail -20 {DC}/logs/admin.out.log
""")
    print(f"\nserving: {', '.join(served_tabs)}  "
          f"({len(served):,} bytes, no-store)")

print("\ninstalled and running" + (f" (pid {pid})" if pid else "") + ".\n")
print(f"  open   http://localhost:{PORT}")
print(f"  log    tail -f {DC}/logs/admin.out.log")
print(f"  audit  tail -f {DC}/logs/admin.log")
print(f"  stop   launchctl bootout gui/{uid}/{LABEL}")
print(f"""
It will ask for {env['UI_USERNAME']} and the UI_PASSWORD from shared/.env.

Reachable from this Mac only. That is on purpose — Cloudflare Access covers
the tunnel, not the LAN, and this page edits your keys. To reach it from your
phone, add a Cloudflare tunnel route to localhost:{PORT} so it sits behind the
same Access login as the dashboard.
""")
