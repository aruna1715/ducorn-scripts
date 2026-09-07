#!/usr/bin/env python3
"""
DuCorn Admin — configuration, services and housekeeping in one place.

    launchctl kickstart -k gui/$(id -u)/com.ducorn.admin
    http://localhost:8099

── WHAT THIS IS ─────────────────────────────────────────────────────────────

A thin UI over the scripts that already exist. It calls ducorn_envfile.py to read
and write shared/.env, doctor.py --json for health, and launchctl for
services. It does not reimplement any of them — a second copy of "is the
router healthy" is exactly the defect this stack has spent a week removing.

── WHY IT HAS ITS OWN LOGIN ─────────────────────────────────────────────────

Cloudflare Access protects the tunnel, so dashboard.ducorn-hq.live is covered.
It does NOT protect the LAN: anything on the local network reaches :8080 and
:8000 directly, and the products themselves advertise LAN URLs.

That is tolerable for a read-mostly dashboard. It is not tolerable for a page
that edits API keys, so this service requires HTTP Basic against UI_USERNAME
and UI_PASSWORD — already provisioned in shared/.env — on every request
including the HTML itself.

── WHAT IT WILL NOT DO ──────────────────────────────────────────────────────

Delete a path that is not in CACHE_TARGETS. Restart a job whose label is not
com.ducorn.*. Run a shell string. Every destructive action names its target
and its cost before you press it.
"""
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from collections import deque
from pathlib import Path

DC = Path(os.environ.get("DUCORN_ROOT", "/Users/ducorn/DC"))
sys.path.insert(0, str(DC / "scripts"))

from fastapi import FastAPI, Depends, HTTPException, Request        # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse            # noqa: E402
from fastapi.security import HTTPBasic, HTTPBasicCredentials        # noqa: E402
from pydantic import BaseModel                                      # noqa: E402

import ducorn_envfile                                                   # noqa: E402

HERE = Path(__file__).resolve().parent
app = FastAPI(title="DuCorn Admin", docs_url=None, redoc_url=None)
security = HTTPBasic()


# ─────────────────────────────────────────────────────────────────────────────
# Auth — the whole surface, including the page
# ─────────────────────────────────────────────────────────────────────────────
def _creds():
    env = ducorn_envfile.effective()
    return env.get("UI_USERNAME", ""), env.get("UI_PASSWORD", "")


def require_login(c: HTTPBasicCredentials = Depends(security)) -> str:
    user, password = _creds()
    if not user or not password:
        # Refuse rather than run open. A config page with no credentials
        # configured is the one thing worse than no config page.
        raise HTTPException(
            503, "UI_USERNAME / UI_PASSWORD are not set in shared/.env — "
                 "this service will not run without them.")
    ok_u = secrets.compare_digest(c.username, user)
    ok_p = secrets.compare_digest(c.password, password)
    if not (ok_u and ok_p):
        raise HTTPException(401, "Not authorised",
                            headers={"WWW-Authenticate": "Basic"})
    return c.username


def audit(who: str, action: str, detail: str = "") -> None:
    """Anything that changes the machine leaves a line behind."""
    from datetime import datetime
    log = DC / "logs" / "admin.log"
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {who:12} "
                    f"{action:22} {detail}\n")
    except OSError:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Services
# ─────────────────────────────────────────────────────────────────────────────
LAUNCHD = DC / "launchd"
_LABEL = re.compile(r"^com\.ducorn\.[A-Za-z0-9._-]+$")


def known_labels() -> list:
    """From the plists on disk. Not a list anyone maintains."""
    out = []
    for p in sorted(LAUNCHD.glob("*.plist")):
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        m = re.search(r"<key>Label</key>\s*<string>([^<]+)</string>", text)
        if m and _LABEL.match(m.group(1)):
            out.append(m.group(1))
    return out


def service_state() -> list:
    """label, pid, last exit — straight from launchctl."""
    try:
        r = subprocess.run(["launchctl", "list"], capture_output=True,
                           text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as e:
        return [{"label": "launchctl", "pid": None, "exit": None,
                 "error": str(e)}]
    rows = {}
    for line in r.stdout.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) >= 3 and _LABEL.match(parts[2].strip()):
            pid = parts[0].strip()
            rows[parts[2].strip()] = {
                "pid": int(pid) if pid.isdigit() else None,
                "exit": int(parts[1]) if parts[1].strip().lstrip("-").isdigit()
                        else None,
            }
    out = []
    for label in known_labels():
        s = rows.get(label, {})
        out.append({"label": label,
                    "short": label.replace("com.ducorn.", ""),
                    "pid": s.get("pid"),
                    "exit": s.get("exit"),
                    "running": s.get("pid") is not None,
                    "loaded": label in rows})
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Logs
#
# The paths are read out of the plists, not listed here. Every launchd job
# already declares StandardOutPath and StandardErrorPath; that IS where its
# output goes, by definition. A second list in this file would be a second
# copy of one fact, and the first time someone changed a plist the admin page
# would quietly show them the wrong file — which is the failure mode this
# stack keeps producing.
#
# Files in logs/ that no plist claims are listed separately as unclaimed,
# rather than hidden. They are usually the ones worth looking at.
# ─────────────────────────────────────────────────────────────────────────────
LOGS = DC / "logs"
PRODUCTS = DC / "ducorn-products" / "products"
_OUT = re.compile(r"<key>StandardOutPath</key>\s*<string>([^<]+)</string>")
_ERR = re.compile(r"<key>StandardErrorPath</key>\s*<string>([^<]+)</string>")
_WD = re.compile(r"<key>WorkingDirectory</key>\s*<string>([^<]+)</string>")


def product_dirs() -> set:
    try:
        return {p.name for p in PRODUCTS.iterdir() if p.is_dir()}
    except OSError:
        return set()


def classify(short: str, dirs: set):
    """
    Stack service, or pipeline-built product?

    NOT a list in this file. The deployer names each launchd label after the
    product it is deploying, so a product's label suffix IS its directory
    name — com.ducorn.ducorn-run-history -> products/ducorn-run-history. The
    stack services were named by hand and match no directory: com.ducorn.admin
    runs out of products/ducorn-admin, but "admin" is not "ducorn-admin".

    WorkingDirectory cannot do this job. admin, api and pdf all run from
    inside products/ and are stack services; ducorn-spend-status-web is a
    product and runs from ~/DC.

    The -web / -api suffix is the deployer's own, for the two halves of a
    page+api product, so it comes off before the comparison.

    If the deployer's naming ever changes, this misfiles rather than crashing
    — which is why every row carries the directory it matched, visible in the
    page, instead of a verdict you have to trust.
    """
    if short in dirs:
        return "product", short
    for suffix in ("-web", "-api"):
        if short.endswith(suffix) and short[: -len(suffix)] in dirs:
            return "product", short[: -len(suffix)]
    return "stack", None

# A filtered search reads the file. Past this, only the tail is scanned —
# a runaway log should not turn one click into a minute of disk.
SCAN_CAP = 64 * 1024 * 1024
MAX_LINES = 5000


def _under_dc(raw: str):
    """A path from a plist, accepted only if it lands inside ~/DC."""
    try:
        p = Path(raw).expanduser().resolve()
        p.relative_to(DC.resolve())
    except (ValueError, OSError):
        return None
    return p


def log_sources() -> list:
    """Every log this stack writes, discovered from the plists."""
    out, claimed, dir_kind = [], set(), {}
    dirs = product_dirs()

    for plist in sorted(LAUNCHD.glob("*.plist")):
        try:
            text = plist.read_text(errors="replace")
        except OSError:
            continue
        m = re.search(r"<key>Label</key>\s*<string>([^<]+)</string>", text)
        if not m or not _LABEL.match(m.group(1)):
            continue
        label = m.group(1)
        short = label.replace("com.ducorn.", "")

        seen = {}
        for stream, rx in (("out", _OUT), ("err", _ERR)):
            hit = rx.search(text)
            if not hit:
                continue
            p = _under_dc(hit.group(1))
            if p is None:
                continue
            seen[stream] = p

        # Most of these plists send stdout and stderr to the same file. Listing
        # it twice would be two buttons opening one thing.
        if seen.get("out") and seen.get("out") == seen.get("err"):
            seen = {"log": seen["out"]}

        kind, product = classify(short, dirs)

        # Remember how the JOB that runs out of a directory was classified.
        # products/ducorn-admin is the admin service's working directory, not
        # a pipeline product, and only the label knows that — so a stray .log
        # in there must inherit the job's verdict, not the folder's name.
        wd = _WD.search(text)
        if wd:
            wp = _under_dc(wd.group(1))
            if wp is not None and wp.parent == PRODUCTS.resolve():
                dir_kind[wp.name] = (kind, product)

        for stream, p in seen.items():
            claimed.add(p)
            out.append({"id": f"{short}:{stream}", "service": short,
                        "label": label, "stream": stream, "path": str(p),
                        "claimed": True, "kind": kind, "product": product})

    # Files nothing declares.
    #
    # flow_<topic>.log is one pipeline run. It is neither a stack service nor
    # a running product — it is the record of a product being BUILT, and most
    # of them name a topic with no product directory at all: superseded
    # versions, renamed runs, tests. Filing them with the services was wrong;
    # filing them with the products would bury seven live products behind
    # twenty-seven build logs. They are their own thing.
    #
    # Everything else under logs/ is a script — slack_bot.log, digest.log —
    # and belongs with the stack.
    if LOGS.is_dir():
        for p in sorted(LOGS.glob("*.log")):
            rp = _under_dc(str(p))
            if rp is None or rp in claimed:
                continue
            if p.name.startswith("flow_"):
                topic = p.stem[len("flow_"):]
                out.append({"id": f"flow:{topic}", "service": topic,
                            "label": None, "stream": "run", "path": str(rp),
                            "claimed": False, "kind": "pipeline",
                            "product": topic if topic in dirs else None})
            else:
                out.append({"id": f"unclaimed:{p.name}", "service": p.stem,
                            "label": None, "stream": "log", "path": str(rp),
                            "claimed": False, "kind": "stack",
                            "product": None})

    if PRODUCTS.is_dir():
        for d in sorted(PRODUCTS.iterdir()):
            if not d.is_dir():
                continue
            for p in sorted(list(d.glob("*.log")) + list(d.glob("logs/*.log"))):
                rp = _under_dc(str(p))
                if rp is None or rp in claimed:
                    continue
                kind, product = dir_kind.get(d.name, ("product", d.name))
                out.append({"id": f"unclaimed:{d.name}/{p.name}",
                            "service": d.name, "label": None, "stream": "log",
                            "path": str(rp), "claimed": False,
                            "kind": kind, "product": product})

    for s in out:
        p = Path(s["path"])
        try:
            st = p.stat()
            s.update(exists=True, size=st.st_size, mtime=int(st.st_mtime))
        except OSError:
            s.update(exists=False, size=0, mtime=None)
    return out


def read_log(path: Path, lines: int, q: str, *, regex: bool, case: bool,
             invert: bool) -> dict:
    """Last `lines` lines, or the last `lines` that match `q`."""
    try:
        size = path.stat().st_size
    except OSError as e:
        return {"error": str(e), "lines": [], "size": 0}

    matcher = None
    if q:
        if regex:
            try:
                matcher = re.compile(q, 0 if case else re.I).search
            except re.error as e:
                return {"error": f"bad pattern: {e}", "lines": [], "size": size}
        else:
            needle = q if case else q.lower()
            matcher = (lambda s: needle in s) if case \
                else (lambda s: needle in s.lower())

    start = max(0, size - SCAN_CAP)
    keep, scanned, matched = deque(maxlen=lines), 0, 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            if start:
                fh.seek(start)
                fh.readline()                 # drop the half line we landed in
            for line in fh:
                scanned += 1
                line = line.rstrip("\n")
                if matcher is not None and bool(matcher(line)) == invert:
                    continue
                matched += 1
                keep.append(line)
    except OSError as e:
        return {"error": str(e), "lines": [], "size": size}

    return {"lines": list(keep), "size": size, "scanned": scanned,
            "matched": matched if q else scanned,
            "capped": start > 0,
            "truncated": (matched if q else scanned) > len(keep)}


# ─────────────────────────────────────────────────────────────────────────────
# Caches — a fixed allowlist. Nothing else is ever deleted.
# ─────────────────────────────────────────────────────────────────────────────
CACHE_TARGETS = {
    "pycache": {
        "label": "Python bytecode (__pycache__)",
        "globs": ["**/__pycache__"], "dirs": True,
        "cost": "Nothing. Regenerated on next import.", "risk": "none",
    },
    "pytest": {
        "label": "pytest cache",
        "globs": ["**/.pytest_cache"], "dirs": True,
        "cost": "Nothing.", "risk": "none",
    },
    "dryrun": {
        "label": "Dry-run prompt dumps",
        "globs": ["ducorn-products/docs/*DRYRUN*.txt"], "dirs": False,
        "cost": "Nothing. Rewritten by the next --dry-run.", "risk": "none",
    },
    "product_venvs": {
        "label": "Product virtualenvs",
        "globs": ["ducorn-products/products/*/.venv"], "dirs": True,
        "cost": "The next test run reinstalls dependencies — minutes, not data.",
        "risk": "low",
    },
    "patch_backups": {
        "label": "Patch backup files (*.backup-*)",
        "globs": ["ducorn/*.backup-*", "ducorn/**/*.backup-*",
                  "scripts/*.backup-*"], "dirs": False,
        "cost": "Loses the rollback point for every patch applied so far.",
        "risk": "medium",
    },
    "skill_outputs": {
        "label": "Skill output artifacts",
        "globs": ["ducorn-products/docs/*skill*-output.txt"], "dirs": False,
        "cost": "A re-run loses the previous skill's work as context. "
                "Checkpoints still hold the verdicts.",
        "risk": "medium",
    },
    "gstack_checkpoints": {
        "label": "G-Stack checkpoints",
        "globs": ["ducorn-products/docs/*gstack-checkpoint.json"], "dirs": False,
        "cost": "EVERY product re-runs EVERY skill from scratch on its next "
                "run. This is the expensive one.",
        "risk": "high",
    },
}


def _resolve(glob: str) -> list:
    """Matches under DC only. A path that escapes is dropped, not deleted."""
    out = []
    for p in DC.glob(glob):
        try:
            rp = p.resolve()
            rp.relative_to(DC.resolve())
        except (ValueError, OSError):
            continue
        out.append(rp)
    return out


def _size(paths: list) -> int:
    total = 0
    for p in paths:
        try:
            if p.is_dir():
                total += sum(f.stat().st_size for f in p.rglob("*")
                             if f.is_file())
            elif p.is_file():
                total += p.stat().st_size
        except OSError:
            continue
    return total


def cache_state() -> list:
    out = []
    for key, spec in CACHE_TARGETS.items():
        paths = []
        for g in spec["globs"]:
            paths += _resolve(g)
        paths = [p for p in paths if p.is_dir() == spec["dirs"]]
        out.append({"key": key, "label": spec["label"], "cost": spec["cost"],
                    "risk": spec["risk"], "count": len(paths),
                    "bytes": _size(paths)})
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def page(who: str = Depends(require_login)):
    """
    no-store, deliberately.

    The page is one file with no version in its URL, so a browser that
    heuristically caches it keeps serving the old markup after a reinstall —
    the service restarts, the install reports success, and the new tab is
    simply not there. That is indistinguishable from a broken deploy, and it
    cost a round trip to work out. An admin page is not worth caching.

    The build stamp goes in a header so `curl -I` can answer "is the running
    page the one I just installed?" without reading the HTML.
    """
    f = HERE / "index.html"
    if not f.is_file():
        return HTMLResponse("<h1>index.html is missing</h1>", status_code=500)
    try:
        stamp = str(int(f.stat().st_mtime))
    except OSError:
        stamp = "unknown"
    return HTMLResponse(
        f.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store, must-revalidate",
                 "Pragma": "no-cache",
                 "X-DuCorn-Page-Built": stamp})


@app.get("/api/env")
def api_env(who: str = Depends(require_login)):
    entries, seen = [], set()
    for e in reversed(ducorn_envfile.parse()):       # last definition wins
        if e["name"] in seen:
            continue
        seen.add(e["name"])
        entries.append({
            "name": e["name"],
            "masked": ducorn_envfile.mask(e["name"], e["value"]),
            "secret": ducorn_envfile.is_secret(e["name"]),
            "empty": not e["value"],
            "restarts": [s.replace("com.ducorn.", "")
                         for s in ducorn_envfile.affects(e["name"])],
        })
    entries.sort(key=lambda e: e["name"])
    return {"entries": entries, "problems": ducorn_envfile.check()}


class Reveal(BaseModel):
    name: str


@app.post("/api/env/reveal")
def api_reveal(body: Reveal, who: str = Depends(require_login)):
    v = ducorn_envfile.effective().get(body.name)
    if v is None:
        raise HTTPException(404, f"{body.name} is not set")
    audit(who, "revealed", body.name)
    return {"name": body.name, "value": v}


class Changes(BaseModel):
    changes: dict


@app.post("/api/env")
def api_env_write(body: Changes, who: str = Depends(require_login)):
    try:
        r = ducorn_envfile.write(body.changes)
    except ducorn_envfile.EnvError as e:
        # A refusal is a 400 with the reason, not a 500 with a traceback.
        return JSONResponse({"error": str(e)}, status_code=400)
    audit(who, "wrote .env", ", ".join(sorted(body.changes)))
    return r


@app.get("/api/env/backups")
def api_backups(who: str = Depends(require_login)):
    return {"backups": [{"name": p.name, "bytes": p.stat().st_size}
                        for p in ducorn_envfile.backups()[:40]]}


class RestoreBody(BaseModel):
    name: str


@app.post("/api/env/restore")
def api_restore(body: RestoreBody, who: str = Depends(require_login)):
    try:
        src = ducorn_envfile.restore(body.name)
    except ducorn_envfile.EnvError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    audit(who, "restored .env", body.name)
    return {"restored": src}


@app.get("/api/services")
def api_services(who: str = Depends(require_login)):
    return {"services": service_state()}


class ServiceBody(BaseModel):
    label: str


@app.post("/api/services/restart")
def api_restart(body: ServiceBody, who: str = Depends(require_login)):
    if body.label not in known_labels():
        raise HTTPException(400, f"{body.label} is not a DuCorn launchd job")
    uid = os.getuid()
    r = subprocess.run(
        ["launchctl", "kickstart", "-k", f"gui/{uid}/{body.label}"],
        capture_output=True, text=True, timeout=30)
    audit(who, "restarted", f"{body.label} (exit {r.returncode})")
    return {"label": body.label, "exit": r.returncode,
            "output": (r.stdout + r.stderr).strip()[:400]}


@app.get("/api/logs")
def api_logs(kind: str = "", who: str = Depends(require_login)):
    every = log_sources()                       # one scan, not four
    kinds = ("stack", "product", "pipeline")
    counts = {k: sum(1 for s in every if s["kind"] == k) for k in kinds}
    if kind in kinds:
        every = [s for s in every if s["kind"] == kind]
    return {"sources": every, "counts": counts}


@app.get("/api/logs/read")
def api_logs_read(id: str, lines: int = 500, q: str = "",
                  regex: int = 0, case: int = 0, invert: int = 0,
                  who: str = Depends(require_login)):
    # The id is looked up in the discovered set. No path from the browser is
    # ever opened — the caller picks a row, not a filename.
    src = next((s for s in log_sources() if s["id"] == id), None)
    if src is None:
        raise HTTPException(404, f"no such log: {id}")
    if not src["exists"]:
        return {"source": src, "lines": [],
                "note": "the service has not written this file yet"}

    lines = max(50, min(int(lines), MAX_LINES))
    out = read_log(Path(src["path"]), lines, q.strip(),
                   regex=bool(regex), case=bool(case), invert=bool(invert))
    if out.get("error") and not out["lines"]:
        return JSONResponse({"error": out["error"], "source": src},
                            status_code=400)
    out["source"] = src
    return out


def doctor_python() -> str:
    """
    An interpreter that can actually reach the database.

    This used to be shutil.which("python3"). Under launchd the PATH is
    /usr/bin:/bin:/usr/sbin:/sbin, so that resolved to the macOS system
    python — no psycopg2, no DuCorn modules — and doctor produced nothing.
    ducorn/.venv/bin/python is the one the pipeline itself runs on.
    """
    for c in (DC / "ducorn" / ".venv" / "bin" / "python",
              Path("/opt/homebrew/bin/python3.12")):
        if c.exists():
            return str(c)
    return shutil.which("python3") or sys.executable


@app.get("/api/health")
def api_health(who: str = Depends(require_login)):
    """doctor.py --json. Not a second opinion about the same things."""
    py = doctor_python()
    cmd = [py, str(DC / "scripts" / "doctor.py"), "--json"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180,
                           cwd=str(DC))
    except (OSError, subprocess.SubprocessError) as e:
        return JSONResponse({"error": f"could not run doctor.py: "
                                      f"{type(e).__name__}: {e}",
                             "command": " ".join(cmd)}, status_code=502)

    # bootstrap_python prints "[bootstrap] re-running under …" on stdout before
    # doctor's own output, so the payload does not start at character zero.
    out = r.stdout or ""
    i = out.find("{")
    if i >= 0:
        try:
            return json.loads(out[i:])
        except json.JSONDecodeError:
            pass

    # NOT {}. The old code did `json.loads(r.stdout or "{}")`, so a doctor that
    # produced nothing rendered as an empty page with no explanation — the
    # silent-default defect, in the health check.
    return JSONResponse({
        "error": "doctor.py did not return JSON",
        "command": " ".join(cmd),
        "exit": r.returncode,
        "stdout": out[-1500:],
        "stderr": (r.stderr or "")[-1500:],
    }, status_code=502)


@app.get("/api/caches")
def api_caches(who: str = Depends(require_login)):
    return {"caches": cache_state()}


class CacheBody(BaseModel):
    key: str
    confirm: str = ""


@app.post("/api/caches/clear")
def api_cache_clear(body: CacheBody, who: str = Depends(require_login)):
    spec = CACHE_TARGETS.get(body.key)
    if not spec:
        raise HTTPException(400, f"{body.key} is not a known cache target")
    if spec["risk"] == "high" and body.confirm != body.key:
        raise HTTPException(
            400, f"This one is destructive: {spec['cost']} "
                 f"Send confirm='{body.key}' to proceed.")
    paths = []
    for g in spec["globs"]:
        paths += _resolve(g)
    paths = [p for p in paths if p.is_dir() == spec["dirs"]]

    removed, failed, freed = 0, [], _size(paths)
    for p in paths:
        try:
            shutil.rmtree(p) if p.is_dir() else p.unlink()
            removed += 1
        except OSError as e:
            failed.append(f"{p.name}: {e}")
    audit(who, "cleared cache", f"{body.key} — {removed} removed, "
                                f"{freed:,} bytes")
    return {"key": body.key, "removed": removed, "freed": freed,
            "failed": failed[:10]}


@app.get("/api/whoami")
def api_whoami(who: str = Depends(require_login)):
    return {"user": who, "root": str(DC)}


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    return JSONResponse({"error": f"{type(exc).__name__}: {exc}"},
                        status_code=500)
