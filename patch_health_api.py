#!/usr/bin/env python3
"""
Make the health report readable by something other than a terminal.

── WHY ──────────────────────────────────────────────────────────────────────

doctor.py answers "is this machine healthy" for a person at a shell. The person
it does not serve is the one from your independence question — an operator at
the dashboard with no terminal, which is the only interface you have said you
want humans using.

This is the data layer for that: doctor grows --json, and the API grows two
endpoints. The panel is the next patch and consumes these.

── WHY TWO ENDPOINTS AND NOT ONE ────────────────────────────────────────────

The checks take 15 to 30 seconds — Chromium launches, subprocesses spawn,
databases are queried. That cannot happen inside a web request: the browser
would hang, and two people clicking would run it twice.

    POST /health/run       starts a run in the background, returns at once
    GET  /health/report    the last result, its age, and whether one is running

So the panel shows the last known state immediately, with its timestamp, and a
button to refresh. A stale answer clearly labelled is more useful than a
spinner, and much more useful than a page that hangs for half a minute.

── ON PARSING doctor's OUTPUT ───────────────────────────────────────────────

doctor re-execs itself under an interpreter that has psycopg2 and announces it:

    [bootstrap] python3.14 lacks psycopg2; re-running under ...python3.12

That line lands on stdout before anything else, so the JSON is found from the
first "{" rather than by assuming the whole of stdout is JSON. Fixing the
bootstrap to print on stderr would be tidier and would also change behaviour
for every other caller, which is not a thing to do in passing.
"""
import ast
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DOCTOR = Path("/Users/ducorn/DC/scripts/doctor.py")
API = Path("/Users/ducorn/DC/ducorn-products/products/ducorn-activity-api/main.py")

doc_s = DOCTOR.read_text(encoding="utf-8")
api_s = API.read_text(encoding="utf-8")

if "--json" in doc_s and "_HEALTH" in api_s:
    sys.exit("Already patched — the health report is available over HTTP.")
if "def check_regressions" not in doc_s:
    sys.exit("Apply patch_doctor_proof.py first. NOTHING WRITTEN.")
if "def known_slug" not in api_s:
    sys.exit("Apply patch_atlas_failure.py first. NOTHING WRITTEN.")

applied = []


def swap(label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {text.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    applied.append(label)
    return text.replace(old, new, 1)


# ═══ 1. doctor speaks JSON ═══════════════════════════════════════════════════
doc_s = swap("json flag", doc_s,
             '''    ap.add_argument("--quiet", action="store_true", help="only what is wrong")''',
             '''    ap.add_argument("--quiet", action="store_true", help="only what is wrong")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable, for the dashboard")''')

doc_s = swap("json run", doc_s,
             '''    print("DuCorn doctor — every check runs the real thing\\n")

    if args.spend:''',
             '''    if args.json:
        # Every check prints as it goes, and several print extra detail of
        # their own. Rather than thread a flag through all of them, the whole
        # run is captured — nothing can leak into the JSON by being added
        # later and forgetting.
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            check_services()
            check_databases()
            check_imports()
            check_browser()
            check_deploy()
            check_regressions()
            check_models()
            check_keys_and_spend()
            check_hygiene()
        bad = [r for r in results if not r["ok"]]
        print(json.dumps({
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "total": len(results),
            "failed": len(bad),
            "healthy": not bad,
            "checks": results,
            "transcript": buf.getvalue()[-8000:],
        }))
        return 1 if bad else 0

    print("DuCorn doctor — every check runs the real thing\\n")

    if args.spend:''')

if "\nfrom datetime import datetime\n" not in doc_s.split("results = []", 1)[0]:
    doc_s = swap("datetime", doc_s, "import argparse\nimport ast\n",
                 "import argparse\nimport ast\nfrom datetime import datetime\n")

# ═══ 2. the API serves it ════════════════════════════════════════════════════
# main.py imports `date`, not `datetime`, and the report computes an age. My
# own pyflakes gate caught this before a byte was written — the third import
# mistake it has stopped tonight, which is the argument for running it on
# everything rather than on the files I remember to worry about.
# Anchored at column 0. An unanchored check matched the INDENTED
# `from datetime import date, datetime` inside a function at line 340 and
# concluded the module already had it — the same mistake as a grep matching
# its own docstring, an hour apart. Module-level facts need module-level
# anchors.
if "\nfrom datetime import date, datetime\n" not in api_s:
    # Column 0 again: the bare form also ends four indented imports.
    api_s = swap("datetime import", api_s,
                 "\nfrom datetime import date\n",
                 "\nfrom datetime import date, datetime\n")

api_s = swap("health endpoints", api_s, '''@app.get("/pipeline/failure/{slug}")''',
             '''# The last health report, and whether one is being produced right now. The
# checks take 15-30s, so a request can never run them: the panel shows the last
# result with its age and offers a refresh.
_HEALTH = {"running": False, "generated_at": None, "report": None,
           "error": None}
DOCTOR_PATH = "/Users/ducorn/DC/scripts/doctor.py"


def _run_doctor_now():
    """Run the checks and store the result. Called on a background thread."""
    import subprocess as _sp
    _HEALTH["running"] = True
    _HEALTH["error"] = None
    try:
        r = _sp.run(["python3", DOCTOR_PATH, "--json"],
                    capture_output=True, text=True, timeout=180)
        raw = r.stdout
        # doctor announces its own re-exec on stdout before the JSON:
        #   [bootstrap] python3.14 lacks psycopg2; re-running under ...
        # so the payload starts at the first brace, not at the first byte.
        if "{" not in raw:
            raise ValueError((r.stderr or raw or "no output")[-400:])
        _HEALTH["report"] = _json.loads(raw[raw.index("{"):])
        _HEALTH["generated_at"] = _HEALTH["report"].get("generated_at")
    except Exception as e:
        _HEALTH["error"] = f"{type(e).__name__}: {e}"
        print(f"[health] doctor failed: {_HEALTH['error']}")
    finally:
        _HEALTH["running"] = False


@app.post("/health/run")
async def start_health_run():
    """Kick off a health check. Returns immediately; poll /health/report."""
    if _HEALTH["running"]:
        return {"status": "already running"}
    import threading
    threading.Thread(target=_run_doctor_now, daemon=True).start()
    return {"status": "started"}


@app.get("/health/report")
def get_health_report():
    """
    The last health report, its age, and whether one is running.

    Never runs the checks itself. A web request that waits half a minute for
    Chromium to launch is a page that looks broken.
    """
    age = None
    if _HEALTH["generated_at"]:
        try:
            age = int((datetime.now() - datetime.fromisoformat(
                _HEALTH["generated_at"])).total_seconds())
        except (ValueError, TypeError):
            age = None
    return {"running": _HEALTH["running"], "error": _HEALTH["error"],
            "generated_at": _HEALTH["generated_at"], "age_seconds": age,
            "report": _HEALTH["report"]}


@app.get("/pipeline/failure/{slug}")''')

# ── write both, or neither ───────────────────────────────────────────────────
stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
targets = [(DOCTOR, doc_s), (API, api_s)]
backups = {}
for path, _ in targets:
    b = path.with_name(f"{path.stem}.backup-healthapi-{stamp}{path.suffix}")
    shutil.copy2(path, b)
    backups[path] = b


def die(msg):
    for path, b in backups.items():
        shutil.copy2(b, path)
    sys.exit(f"{msg} — both files reverted")


for path, text in targets:
    path.write_text(text, encoding="utf-8")

for path, _ in targets:
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        die(f"SYNTAX ERROR in {path.name} ({e})")
    r = subprocess.run([sys.executable, "-m", "pyflakes", str(path)],
                       capture_output=True, text=True)
    undef = [l for l in (r.stdout + r.stderr).splitlines()
             if "undefined name" in l]
    if undef:
        die(f"{path.name}: " + "; ".join(undef))
print("syntax and undefined-name checks: clean on both")

# ── run it for real, which is the only way to know ───────────────────────────
print("\nrunning doctor --json (this takes 15-30s, it launches a browser)")
r = subprocess.run(["python3", str(DOCTOR), "--json"],
                   capture_output=True, text=True, timeout=240)
raw = r.stdout
if "{" not in raw:
    die(f"no JSON on stdout:\\n{(r.stderr or raw)[-600:]}")
import json
try:
    payload = json.loads(raw[raw.index("{"):])
except json.JSONDecodeError as e:
    die(f"stdout is not valid JSON ({e}):\\n{raw[:300]}")

for key in ("generated_at", "total", "failed", "healthy", "checks"):
    if key not in payload:
        die(f"the payload is missing {key!r}")
if not isinstance(payload["checks"], list) or not payload["checks"]:
    die("no checks in the payload")
sample = payload["checks"][0]
for key in ("section", "name", "ok", "detail", "fix"):
    if key not in sample:
        die(f"a check is missing {key!r}: {sample}")

print(f"  ok   {payload['total']} checks, {payload['failed']} failing")
print(f"  ok   sections: "
      f"{', '.join(sorted({c['section'] for c in payload['checks']}))}")
print(f"  ok   every failing check carries a fix: "
      f"{all(c['fix'] for c in payload['checks'] if not c['ok'])}")

# the bootstrap banner must be survivable, since that is what tripped me up
if not raw.startswith("{"):
    print(f"  ok   {len(raw) - len(raw[raw.index('{'):])} bytes of preamble "
          f"skipped, as the API does")

print("\napplied: " + ", ".join(applied))
for path, b in backups.items():
    print(f"backup:  {b.name}")
print()
print("Restart the API, then:")
print("  launchctl kickstart -k gui/$(id -u)/com.ducorn.api")
print("  curl -s -XPOST -H \\"x-api-key: $DUCORN_API_TOKEN\\" "
      "localhost:8000/health/run")
print("  sleep 30 && curl -s -H \\"x-api-key: $DUCORN_API_TOKEN\\" "
      "localhost:8000/health/report | head -c 300")
