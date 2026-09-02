#!/usr/bin/env python3
"""
Exercise the deploy path. It produced four bugs tonight and had no test.

    python3 scripts/prove_deploy.py

── WHY THIS EXISTS ──────────────────────────────────────────────────────────

Every deploy defect this evening was found by a real product hitting it, in
production, one at a time, each costing a cycle:

    the .env.example default was discarded      → deploy aborted on optional config
    one product_type per product                → the API half was never started
    the system interpreter, not the product's   → ModuleNotFoundError: asyncpg
    _probe("/health") or _probe("/")            → 404 is truthy; the fallback
                                                   had never once run

None of them needed a pipeline to find. Every one is a property of a function
that takes a directory and returns a plan. This runs those functions against
synthetic products and asserts the properties, in about a second.

── WHAT IT DOES NOT DO ──────────────────────────────────────────────────────

It never touches launchd, never writes to ~/Library/LaunchAgents, and never
starts a process. Registering services would make a test that changes the
machine it is testing. Everything up to and including the generated plist is
checked — the plist is parsed with plistlib and its ProgramArguments read —
and the act of loading it is the one step taken on faith.

Each check is named for the bug it prevents, so a failure here says which
regression came back rather than which assertion tripped.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

VENV = "/Users/ducorn/DC/ducorn/.venv/bin/python"
TOOLS = "/Users/ducorn/DC/ducorn/tools"
SCRIPTS = "/Users/ducorn/DC/scripts"

# DuCornDeployTool imports crewai. Rather than making you remember which
# interpreter to use, re-exec under the one that has it.
try:
    import crewai  # noqa: F401
except ImportError:
    if os.environ.get("_PROVE_DEPLOY_REEXEC") == "1":
        sys.exit("crewai is not importable even under the pipeline venv.")
    if not os.path.exists(VENV):
        sys.exit(f"crewai is not importable and {VENV} does not exist.")
    os.environ["_PROVE_DEPLOY_REEXEC"] = "1"
    sys.exit(subprocess.call([VENV, os.path.abspath(__file__)] + sys.argv[1:],
                             env=os.environ))

sys.path[:0] = [SCRIPTS, TOOLS]
import DuCornDeployTool as D  # noqa: E402

PASSED, FAILED = [], []


def check(name, ok, detail=""):
    (PASSED if ok else FAILED).append(name)
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + (f"   {detail}" if detail else ""))
    return ok


def product(root, name, *, api=None, page=False, script=False,
            manifest=None, env_example=None, own_env=None, venv=False):
    """A synthetic product on disk. No network, no launchd, no side effects."""
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    if api:
        (d / api).parent.mkdir(parents=True, exist_ok=True)
        (d / api).write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    if page:
        (d / "index.html").write_text("<h1>hi</h1>")
    if script:
        (d / "main.py").write_text("print('hello')\n")
    if manifest is not None:
        (d / "service.json").write_text(
            manifest if isinstance(manifest, str) else json.dumps(manifest))
    if env_example is not None:
        (d / ".env.example").write_text(env_example)
    if own_env is not None:
        (d / ".env").write_text(own_env)
    if venv:
        (d / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
        (d / ".venv" / "bin" / "python").write_text("#!/bin/sh\n")
        (d / ".venv" / "bin" / "python").chmod(0o755)
    return d


root = Path(tempfile.mkdtemp(prefix="prove-deploy-"))
print(f"DuCorn deploy proof — synthetic products under {root}\n")

# ── the interpreter ──────────────────────────────────────────────────────────
print("── the interpreter a product runs under " + "─" * 30)
with_venv = product(root, "with-venv", api="api/main.py", venv=True)
without = product(root, "no-venv", api="api/main.py")

py, how = D.product_python(with_venv)
check("a product with a venv is started with it  [asyncpg]",
      how == "product venv" and py.startswith(str(with_venv)), how)
py2, how2 = D.product_python(without)
check("a product without one falls back to the system python",
      how2 == "system python", how2)

# QA and deploy must agree, or the tests prove nothing about what runs
sys.path.insert(0, SCRIPTS)
import product_paths as P  # noqa: E402
check("QA and deploy resolve the same interpreter  [drift]",
      str(P.product_python(with_venv)) == py)

# ── how many services, and which ─────────────────────────────────────────────
print("\n── what a product is planned as " + "─" * 38)
both = product(root, "page-and-api", api="api/main.py", page=True, venv=True)
roles = [s["role"] for s in D.plan_services("page-and-api", both, "dashboard",
                                            "main.py", 9800, py)]
check("a page + an API plans as TWO services  [the API never started]",
      roles == ["api", "web"], str(roles))

svcs = D.plan_services("page-and-api", both, "dashboard", "main.py", 9800, py)
check("the two get distinct ports",
      svcs[0]["port"] != svcs[1]["port"],
      f"{svcs[0]['port']}, {svcs[1]['port']}")
check("the two get distinct launchd labels",
      svcs[0]["label"] != svcs[1]["label"])
check("the two get distinct log files",
      svcs[0]["log"] != svcs[1]["log"])
check("the API is probed on /health, the page on /  [truthy 404]",
      svcs[0]["health"][0] == "/health" and svcs[1]["health"][0] == "/",
      f"{svcs[0]['health'][0]} / {svcs[1]['health'][0]}")
check("every service starts with the product's interpreter",
      all(s["args"][0] == py for s in svcs))

page_only = product(root, "page-only", page=True)
check("a static dashboard plans as one web service",
      [s["role"] for s in D.plan_services("page-only", page_only, "dashboard",
                                          "main.py", 9800, py)] == ["web"])
api_only = product(root, "api-only", api="api/main.py")
check("an API alone plans as one api service",
      [s["role"] for s in D.plan_services("api-only", api_only, "api",
                                          "main.py", 9800, py)] == ["api"])
plain = product(root, "plain", script=True)
check("a plain script is untouched by any of this",
      [s["role"] for s in D.plan_services("plain", plain, "software",
                                          "main.py", 9800, py)] == ["software"])

# ── the declaration, if the product makes one ────────────────────────────────
if hasattr(D, "declared_services"):
    print("\n── service.json, when the product declares itself " + "─" * 21)
    flask = product(root, "flask-src", manifest={"services": [
        {"role": "api", "module": "src.server:app", "health": "/ping"}]})
    (flask / "src").mkdir(exist_ok=True)
    got = D.plan_services("flask-src", flask, "software", "main.py", 9800, py)
    check("a server the file-inspection could never find is deployed",
          [s["role"] for s in got] == ["api"]
          and "src.server:app" in got[0]["args"], str(got[0]["args"][-4:]))
    check("its declared health path is used",
          got[0]["health"][0] == "/ping", got[0]["health"][0])

    broken = product(root, "broken-manifest", page=True, manifest="{not json")
    check("a malformed manifest falls back rather than failing the deploy",
          [s["role"] for s in D.plan_services("broken-manifest", broken,
                                              "dashboard", "main.py", 9800, py)]
          == ["web"])
else:
    print("\n(service.json support not installed — patch_service_contract.py)")

# ── configuration ────────────────────────────────────────────────────────────
print("\n── configuration " + "─" * 53)
EXAMPLE = ("# a comment\n"
           "DATABASE_URL=postgresql://ducorn@localhost/litellm_db\n"
           "ALLOWED_ORIGINS=http://localhost:8766,http://127.0.0.1:8766\n"
           "SECRET_TOKEN=changeme\n")
cfg = product(root, "cfg", api="api/main.py", page=True, env_example=EXAMPLE)
resolved, missing = D.resolve_product_env(cfg, 8766)
check("a shipped .env.example default is used  [aborted deploy]",
      resolved.get("ALLOWED_ORIGINS", "").startswith("http://localhost:8766"),
      resolved.get("ALLOWED_ORIGINS", "(absent)")[:40])
check("a placeholder is still reported missing",
      missing == ["SECRET_TOKEN"], str(missing))

own = product(root, "own-env", api="api/main.py", env_example=EXAMPLE,
              own_env="ALLOWED_ORIGINS=https://mine.example\n")
resolved2, _ = D.resolve_product_env(own, 8766)
check("the product's own .env outranks the shipped default",
      resolved2.get("ALLOWED_ORIGINS") == "https://mine.example",
      resolved2.get("ALLOWED_ORIGINS", "(absent)"))

if hasattr(D, "write_page_config"):
    services = D.plan_services("cfg", cfg, "dashboard", "main.py", 9800, py)
    written = D.write_page_config(services, cfg)
    body = Path(written).read_text() if written else ""
    api_port = next(s["port"] for s in services if s["role"] == "api")
    check("config.js names the port this deploy actually chose  [Load failed]",
          f":{api_port}" in body and "window.DUCORN" in body,
          f"apiBase :{api_port}")
    check("a product with no API gets no config.js",
          D.write_page_config([{"role": "web", "port": 1, "root": str(cfg)}],
                              cfg) == "")

if hasattr(D, "product_urls"):
    smart = product(root, "smart-page", api="api/main.py", page=True)
    (smart / "index.html").write_text(
        "<script>const A = params.get('api') || 'http://localhost:8765';</script>")
    svc = D.plan_services("smart-page", smart, "dashboard", "main.py", 9800, py)
    url, public = D.product_urls(svc, {}, smart)
    api_port = next(s["port"] for s in svc if s["role"] == "api")
    check("the published URL carries the API address  [hardcoded 8765]",
          "?api=" in url and f":{api_port}" in url, url)
    check("public stays opt-in", public == "", public or "(none)")
    check("PUBLIC_HOSTNAME opts in explicitly",
          D.product_urls(svc, {"PUBLIC_HOSTNAME": "x.example"}, smart)[1]
          == "https://x.example")

# ── the smoke test ───────────────────────────────────────────────────────────
print("\n── the smoke test " + "─" * 52)
if hasattr(D, "smoke"):
    real_probe, real_state = D._probe, D._job_state
    try:
        D._job_state = lambda label: (4242, 0)
        D._probe = lambda port, path: {"/health": 404, "/": 200}.get(path)
        ok, code, pid, ex, path = D.smoke(
            {"label": "x", "port": 1, "health": ["/health", "/"]}, attempts=1)
        check("a 404 on /health does not stop it trying /  [truthy 404]",
              ok and path == "/" and code == 200, f"served via {path}")

        D._probe = lambda port, path: None
        ok2, code2, _, _, _ = D.smoke(
            {"label": "x", "port": 1, "health": ["/health"]}, attempts=1)
        check("a service answering nothing is a failure", not ok2)

        D._probe = lambda port, path: 500
        ok3, *_ = D.smoke({"label": "x", "port": 1, "health": ["/"]}, attempts=1)
        check("a 500 is not 'serving'", not ok3)
    finally:
        D._probe, D._job_state = real_probe, real_state

# ── the plist, parsed rather than eyeballed ──────────────────────────────────
print("\n── the launchd job that would be written " + "─" * 30)
if hasattr(D, "_plist_xml"):
    import plistlib
    spec = D.plan_services("page-and-api", both, "dashboard", "main.py",
                           9800, py)[0]
    xml = D._plist_xml(spec, {"HOME": "/Users/ducorn", "FOO": "b&r<z>"})
    try:
        parsed = plistlib.loads(xml.encode())
        check("the generated plist is valid XML", True)
        check("its ProgramArguments start with the product's interpreter",
              parsed["ProgramArguments"][0] == py)
        check("its label and log match the plan",
              parsed["Label"] == spec["label"]
              and parsed["StandardOutPath"] == spec["log"])
        check("environment values with & < > survive escaping",
              parsed["EnvironmentVariables"]["FOO"] == "b&r<z>",
              parsed["EnvironmentVariables"]["FOO"])
    except Exception as e:
        check("the generated plist is valid XML", False, f"{type(e).__name__}: {e}")

# nothing here may have touched the machine
agents = Path.home() / "Library/LaunchAgents"
strays = list(agents.glob("com.ducorn.page-and-api*")) if agents.is_dir() else []
print()
check("no launchd job was registered by this proof", not strays,
      ", ".join(p.name for p in strays))

print("\n" + "─" * 70)
if FAILED:
    print(f"{len(FAILED)} of {len(PASSED) + len(FAILED)} checks FAILED:\n")
    for n in FAILED:
        print(f"  · {n}")
    print("\nEach name is the bug it prevents. Find that patch in scripts/.")
    sys.exit(1)
print(f"{len(PASSED)} checks passed. The deploy path holds.")
