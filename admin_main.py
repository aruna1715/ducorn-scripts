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
    f = HERE / "index.html"
    if not f.is_file():
        return HTMLResponse("<h1>index.html is missing</h1>", status_code=500)
    return HTMLResponse(f.read_text(encoding="utf-8"))


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
