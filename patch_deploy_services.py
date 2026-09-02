#!/usr/bin/env python3
"""
A product may be more than one service. The deployer assumed otherwise.

── WHY THE SMOKE TEST FAILED ────────────────────────────────────────────────

    GET /health HTTP/1.1  404
    ❌ Deploy failed the smoke test — the service is not serving.

ducorn-spend-status is two services, and the pipeline built it that way on
purpose. Its README documents both:

    uvicorn api.main:app --host 0.0.0.0 --port 8765     # the API, has /health
    python3 -m http.server 8766                          # the page

That is also why .env.example sets ALLOWED_ORIGINS=http://localhost:8766 — the
page calls the API cross-origin, which only makes sense across two ports.

The deploy tool carries one product_type and starts one launchd service. This
product was labelled `dashboard`, so it got the static file server and nothing
else. /health 404s because http.server has no such route, and the API — the
half with the data — was never deployed at all.

── THE SECOND BUG, WHICH WOULD HAVE BITTEN A PLAIN DASHBOARD TOO ────────────

    code = _probe("/health") or _probe("/")

_probe returns an HTTP status. 404 is truthy, so `or` short-circuits and the
fallback to "/" never runs. A purely static dashboard — index.html, no API,
nothing wrong with it — fails this smoke test every time, because the first
probe returns 404 rather than None. The fallback has never once executed.

── THE FIX ──────────────────────────────────────────────────────────────────

plan_services() decides what a product actually is, from what is on disk:

    api/main.py with a FastAPI app   → a uvicorn service, health /health
    index.html at the product root   → a static service, health /
    both                             → both, on two ports

Each service gets its own plist, its own log, and its own smoke test against
its own health path. A product that is one service deploys exactly as before.

Ports are allocated by the deployer, so ALLOWED_ORIGINS is corrected to name
the port the page is really served on — appended rather than replaced, so an
origin someone set deliberately survives.

And the probe tries each candidate path properly: a success wins, anything
else moves on to the next, and the last status seen is what gets reported.
"""
import ast
import shutil
import sys
from datetime import datetime
from pathlib import Path

TOOL = Path("/Users/ducorn/DC/ducorn/tools/DuCornDeployTool.py")
s = TOOL.read_text(encoding="utf-8")

if "def plan_services" in s:
    sys.exit("Already patched — a product may be several services.")
if "_is_placeholder" not in s:
    sys.exit("Apply patch_deploy_env.py first — this builds on the env "
             "resolution it adds. NOTHING WRITTEN.")

tree = ast.parse(s)

# The whole _run method is replaced, located by ast rather than by matching a
# hundred lines of whitespace. Anchoring on text that long is how a patch
# corrupts a file it only meant to edit.
cls = next((n for n in tree.body
            if isinstance(n, ast.ClassDef) and n.name == "DuCornDeployTool"), None)
if cls is None:
    sys.exit("DuCornDeployTool class not found. NOTHING WRITTEN.")
run = next((n for n in cls.body
            if isinstance(n, ast.FunctionDef) and n.name == "_run"), None)
if run is None:
    sys.exit("_run not found. NOTHING WRITTEN.")

old_run = ast.get_source_segment(s, run)
if not old_run or s.count(old_run) != 1:
    sys.exit("could not isolate _run uniquely. NOTHING WRITTEN.")

PLANNER = '''

# ── what is this product, really? ────────────────────────────────────────────

def _used_ports() -> set:
    """Every port already spoken for, from the registry and from launchd."""
    import glob
    used = set(PORT_REGISTRY.values())
    for plist_file in glob.glob(
            "/Users/ducorn/Library/LaunchAgents/com.ducorn.*.plist"):
        try:
            for p in re.findall("<string>([0-9]{4,5})</string>",
                                open(plist_file).read()):
                used.add(int(p))
        except OSError:
            pass
    return used


def _free_port(start: int, used: set) -> int:
    import socket
    port = start
    while True:
        if port not in used:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                if sock.connect_ex(("127.0.0.1", port)) != 0:
                    return port
        port += 1


def plan_services(slug: str, product_dir: Path, product_type: str,
                  entry_point: str, first_port: int) -> list:
    """
    The services this product needs, from what is on disk.

    One product_type could not describe ducorn-spend-status: it ships a
    FastAPI app under api/ AND an index.html, its README documents starting
    both, and its ALLOWED_ORIGINS default names the second port. Labelling it
    `dashboard` started the page and left the API — the half with the data —
    undeployed.
    """
    used = _used_ports()
    used.add(first_port)
    services = []

    api_module = None
    for rel, module in (("api/main.py", "api.main:app"),
                        ("main.py", "main:app"),
                        ("app/main.py", "app.main:app")):
        f = product_dir / rel
        if f.is_file():
            try:
                text = f.read_text(errors="replace")
            except OSError:
                continue
            if "FastAPI" in text:
                api_module = module
                break

    has_page = (product_dir / "index.html").is_file()

    if api_module:
        services.append({
            "role": "api",
            "label": f"com.ducorn.{slug}",
            "port": first_port,
            "health": ["/health", "/docs", "/"],
            "args": ["/opt/homebrew/bin/python3.12", "-m", "uvicorn",
                     api_module, "--host", "0.0.0.0", "--port", str(first_port)],
            "cwd": str(product_dir),
            "log": f"/Users/ducorn/DC/logs/{slug}.log",
        })

    if has_page and (api_module or product_type == "dashboard"):
        page_port = _free_port(first_port + 1, used) if api_module else first_port
        used.add(page_port)
        services.append({
            "role": "web",
            "label": f"com.ducorn.{slug}-web" if api_module else f"com.ducorn.{slug}",
            "port": page_port,
            # A static server has no /health and never will. Asking for one and
            # calling the 404 a failure is what broke this deploy.
            "health": ["/", "/index.html"],
            "args": ["/opt/homebrew/bin/python3.12", "-m", "http.server",
                     str(page_port), "--directory", str(product_dir)],
            "cwd": "/Users/ducorn/DC",
            "log": f"/Users/ducorn/DC/logs/{slug}-web.log" if api_module
                   else f"/Users/ducorn/DC/logs/{slug}.log",
        })

    if not services:
        # A plain script, or anything this cannot recognise: unchanged
        # behaviour, one service, exactly as before.
        ep = entry_point or "main.py"
        services.append({
            "role": "software",
            "label": f"com.ducorn.{slug}",
            "port": first_port,
            "health": ["/health", "/"],
            "args": ["/opt/homebrew/bin/python3.12", str(product_dir / ep)],
            "cwd": str(product_dir),
            "log": f"/Users/ducorn/DC/logs/{slug}.log",
        })

    return services


def _plist_xml(spec: dict, env_entries: dict) -> str:
    args_xml = "\\n".join(f"        <string>{a}</string>" for a in spec["args"])
    env_xml = "\\n".join(
        f"        <key>{k}</key><string>{_xml_escape(v)}</string>"
        for k, v in env_entries.items())
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{spec['label']}</string>
    <key>ProgramArguments</key>
    <array>
{args_xml}
    </array>
    <key>WorkingDirectory</key>
    <string>{spec['cwd']}</string>
    <key>EnvironmentVariables</key>
    <dict>
{env_xml}
    </dict>
    <key>StandardOutPath</key>
    <string>{spec['log']}</string>
    <key>StandardErrorPath</key>
    <string>{spec['log']}</string>
    <key>KeepAlive</key><true/>
    <key>RunAtLoad</key><true/>
    <key>ThrottleInterval</key><integer>10</integer>
</dict>
</plist>"""


def _job_state(label: str):
    out = subprocess.run(["launchctl", "list", label],
                         capture_output=True, text=True).stdout
    pid = re.search(r'"PID"\\s*=\\s*(\\d+)', out)
    ex = re.search(r'"LastExitStatus"\\s*=\\s*(-?\\d+)', out)
    return (int(pid.group(1)) if pid else None,
            int(ex.group(1)) if ex else None)


def _probe(port: int, path: str):
    import urllib.request, urllib.error
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}{path}", timeout=4) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return None


def smoke(spec: dict, attempts: int = 6):
    """
    Is it actually serving?

    Each candidate path is tried on its own merits. The previous version was
    `_probe("/health") or _probe("/")`, and 404 is truthy — so the fallback
    never ran once, and any product without a /health route failed no matter
    how well it was serving its actual content.
    """
    import time
    code = pid = last_exit = None
    for _ in range(attempts):
        time.sleep(3)
        pid, last_exit = _job_state(spec["label"])
        if not pid:
            continue
        for path in spec["health"]:
            c = _probe(spec["port"], path)
            if c is not None:
                code = c
            if c is not None and 200 <= c < 300:
                return True, c, pid, last_exit, path
    return False, code, pid, last_exit, None

'''

# ast.get_source_segment hands back the method with its `def` at column zero
# and the body still at its original depth, so the replacement must match that
# shape — indenting the def as it looks in the file double-indents it.
NEW_RUN = '''def _run(self, slug: str, entry_point: str = "main.py",
         port: int = None, product_type: str = "software") -> str:
        try:
            LOGS_DIR.mkdir(exist_ok=True)
            product_dir = Path(f"/Users/ducorn/DC/ducorn-products/products/{slug}")
            if not product_dir.is_dir():
                return f"❌ No such product: {product_dir}"

            if port is None:
                port = _free_port(NEXT_PORT_START, _used_ports())

            services = plan_services(slug, product_dir, product_type,
                                     entry_point, port)
            print(f"📦 {slug}: "
                  + ", ".join(f"{sp['role']} on :{sp['port']}" for sp in services),
                  flush=True)

            product_env, missing_env = resolve_product_env(product_dir, port)
            if missing_env:
                _names = ", ".join(missing_env)
                return (
                    "❌ Deploy aborted — the product declares configuration "
                    f"with no value anywhere: {_names}.\\n"
                    "Checked, in order: the product's own .env, the deploy "
                    "environment, shared/.env, and the default in the "
                    "product's .env.example.\\n"
                    "Put a per-product setting (ports, origins, paths) in "
                    f"{product_dir}/.env — NOT in shared/.env, which is "
                    "machine-wide and would hand this product's values to "
                    "every other product.\\n"
                    "Put a shared secret (an API key the whole machine uses) "
                    "in /Users/ducorn/DC/shared/.env.")

            # The deployer picks the ports, so it owns the origin the page is
            # really served from. Appended, never replaced: an origin someone
            # set deliberately is not ours to discard.
            web = next((sp for sp in services if sp["role"] == "web"), None)
            if web and "ALLOWED_ORIGINS" in product_env:
                mine = (f"http://localhost:{web['port']},"
                        f"http://127.0.0.1:{web['port']}")
                if f":{web['port']}" not in product_env["ALLOWED_ORIGINS"]:
                    product_env["ALLOWED_ORIGINS"] = (
                        product_env["ALLOWED_ORIGINS"].rstrip(",") + "," + mine)
                    print(f"🔧 ALLOWED_ORIGINS          ← deployer "
                          f"(page is on :{web['port']})", flush=True)

            env_entries = {"HOME": "/Users/ducorn",
                           "PYTHONPATH": "/Users/ducorn/DC/scripts",
                           **product_env}

            LAUNCHD_DIR.mkdir(exist_ok=True)
            started = []
            for spec in services:
                plist = _plist_xml(spec, env_entries)
                plist_path = LAUNCH_AGENTS / f"{spec['label']}.plist"
                plist_path.write_text(plist)
                (LAUNCHD_DIR / f"{spec['label']}.plist").write_text(plist)

                subprocess.run(["launchctl", "unload", str(plist_path)],
                               capture_output=True)
                result = subprocess.run(["launchctl", "load", str(plist_path)],
                                        capture_output=True, text=True)
                if result.returncode != 0:
                    return (f"❌ Error loading {spec['label']}: "
                            f"{result.stderr}")
                spec["plist"] = str(plist_path)
                started.append(spec)

            # Every service is smoke tested on its own health path. One of them
            # serving is not the product working.
            failures, lines = [], []
            for spec in started:
                ok, code, pid, last_exit, path = smoke(spec)
                if ok:
                    lines.append(f"  {spec['role']:8} :{spec['port']}  "
                                 f"HTTP {code} from {path}  (pid {pid})")
                else:
                    try:
                        tail = Path(spec["log"]).read_text()[-500:]
                    except Exception:
                        tail = "(no log)"
                    failures.append(
                        f"{spec['role']} on :{spec['port']} ({spec['label']})\\n"
                        f"  PID: {pid or 'none'} | last exit: {last_exit} | "
                        f"HTTP: {code if code is not None else 'no response'}\\n"
                        f"  tried: {', '.join(spec['health'])}\\n"
                        f"  log tail:\\n{tail}")

            if failures:
                return ("❌ Deploy failed the smoke test — "
                        f"{len(failures)} of {len(started)} service(s) not "
                        "serving.\\n\\n" + "\\n\\n".join(failures))

            return (f"✅ {slug} deployed and serving\\n"
                    + "\\n".join(lines)
                    + f"\\nLogs: " + ", ".join(sp["log"] for sp in started))

        except Exception as e:
            import traceback
            return f"❌ Deploy error: {e}\\n{traceback.format_exc()[-800:]}"
'''

s = s.replace(old_run, NEW_RUN.rstrip("\n"), 1)

# helpers go in above the class
marker = "class DuCornDeployTool(BaseTool):"
if s.count(marker) != 1:
    sys.exit("ANCHOR MISS [class]. NOTHING WRITTEN.")
s = s.replace(marker, PLANNER.strip("\n") + "\n\n\n" + marker, 1)

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = TOOL.with_name(f"DuCornDeployTool.backup-services-{stamp}.py")
shutil.copy2(TOOL, backup)
TOOL.write_text(s, encoding="utf-8")


def die(msg):
    shutil.copy2(backup, TOOL)
    sys.exit(f"{msg} — reverted from {backup.name}")


try:
    ast.parse(s)
except SyntaxError as e:
    die(f"SYNTAX ERROR ({e})")


def unbound_at_module_level(source):
    t = ast.parse(source)

    def names_of(n):
        return {(a.asname or a.name).split(".")[0] for a in n.names}

    mod, loc = set(), set()
    for n in t.body:
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            mod |= names_of(n)
    for n in ast.walk(t):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(n):
                if isinstance(sub, (ast.Import, ast.ImportFrom)):
                    loc |= names_of(sub)
    only_local = loc - mod
    hits = []
    for n in t.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                          ast.Import, ast.ImportFrom)):
            continue
        for sub in ast.walk(n):
            if isinstance(sub, ast.Name) and sub.id in only_local:
                hits.append((getattr(n, "lineno", "?"), sub.id))
                break
    return hits


bad = unbound_at_module_level(TOOL.read_text(encoding="utf-8"))
if bad:
    die("would NameError at import: " + ", ".join(f"line {l} uses {n!r}"
                                                  for l, n in bad))

src = TOOL.read_text(encoding="utf-8")
t2 = ast.parse(src)
cls2 = next(n for n in t2.body
            if isinstance(n, ast.ClassDef) and n.name == "DuCornDeployTool")
if not any(isinstance(n, ast.FunctionDef) and n.name == "_run" for n in cls2.body):
    die("_run is gone from the class")
print("import check: clean, and the class still has _run")

# ── exercise the planner against a product shaped like tonight's ─────────────
import tempfile
seg = {n.name: ast.get_source_segment(src, n) for n in t2.body
       if isinstance(n, ast.FunctionDef)}
for need in ("plan_services", "smoke", "_free_port"):
    if need not in seg:
        die(f"{need} did not land")

ns = {"Path": Path, "PORT_REGISTRY": {}, "re": __import__("re"),
      "_used_ports": lambda: set(), "_free_port": lambda start, used: start}
exec(seg["plan_services"], ns)
plan = ns["plan_services"]

root = Path(tempfile.mkdtemp())

both = root / "both"
(both / "api").mkdir(parents=True)
(both / "api" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()")
(both / "index.html").write_text("<h1>hi</h1>")

page = root / "page"
page.mkdir()
(page / "index.html").write_text("<h1>hi</h1>")

api = root / "api-only"
(api / "api").mkdir(parents=True)
(api / "api" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()")

script = root / "script"
script.mkdir()
(script / "main.py").write_text("print('plain script')")

print("\nwhat each product shape deploys as:")
cases = [
    (both, "dashboard", ["api", "web"], "TONIGHT: page + API, and it got only the page"),
    (page, "dashboard", ["web"], "a static dashboard"),
    (api, "api", ["api"], "an API on its own"),
    (script, "software", ["software"], "a plain script"),
]
for d, ptype, want, why in cases:
    got = [sp["role"] for sp in plan("zz", d, ptype, "main.py", 8090)]
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {d.name:10} {str(got):22} {why}")
    if not ok:
        die(f"{d.name}: expected {want}, got {got}")

svcs = plan("zz", both, "dashboard", "main.py", 8090)
if svcs[0]["health"][0] != "/health":
    die("the API must be probed on /health")
if svcs[1]["health"][0] != "/":
    die("a static server must be probed on / — asking it for /health is the bug")
if svcs[0]["label"] == svcs[1]["label"]:
    die("two services cannot share one launchd label")
if svcs[0]["log"] == svcs[1]["log"]:
    die("two services cannot share one log file")
print(f"  ok   distinct labels ({svcs[0]['label']}, {svcs[1]['label']}) and logs")

# the truthiness bug, proven directly
ns2 = {"subprocess": __import__("subprocess"), "re": __import__("re"),
       "_job_state": lambda label: (123, 0)}
probes = {"/health": 404, "/": 200}
ns2["_probe"] = lambda port, path: probes.get(path)
exec(seg["smoke"], ns2)
ok, code, pid, ex, path = ns2["smoke"]({"label": "x", "port": 1,
                                        "health": ["/health", "/"]}, attempts=1)
print("\nthe probe fallback that never used to run:")
print(f"  /health→404, /→200  ⇒  served={ok}, via {path!r}, code {code}")
if not ok or path != "/":
    die("the fallback probe still does not run — 404 is truthy and short-circuits")

print("\napplied: plan_services + per-service plist/smoke, _run replaced")
print(f"backup:  {backup.name}")
print()
print("Nothing to restart. Re-run the deploy:")
print("  cd ~/DC/ducorn && .venv/bin/python flows/langgraph_flow.py "
      "ducorn-spend-status --phase deploy --engine gstack --coder crewai "
      "--complexity simple")
print()
print("Expect:  📦 ducorn-spend-status: api on :8090, web on :8091")
print("         ✅ ducorn-spend-status deployed and serving")
