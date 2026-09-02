#!/usr/bin/env python3
"""
The product declares what it is. The deployer stops guessing.

── THE TWO PIECES OF LUCK ───────────────────────────────────────────────────

ducorn-spend-status deployed, eventually. Both of the fixes that got it there
rest on a guess:

1. plan_services works out that a product is a page plus an API by looking for
   api/main.py containing the string "FastAPI" and an index.html at the root.
   That describes what REX builds today. A Flask app, a server under src/, or
   anything Node falls through to the generic branch and the API half never
   deploys — the exact failure we spent an hour on, arriving in a new costume.

2. The page found its API because REX happened to build ?api= into it. Nothing
   asked him to. The next product will hardcode localhost:8765 with no override
   and the page will load, look fine, and show "Load failed".

Both are the deployer inferring things the builder already knew and never
wrote down.

── service.json ─────────────────────────────────────────────────────────────

REX declares the services. plan_services reads the declaration when it exists
and falls back to today's heuristic when it does not, so every product already
on disk keeps deploying exactly as it does now.

    {
      "services": [
        {"role": "api", "module": "api.main:app", "health": "/health"},
        {"role": "web", "root": ".", "health": "/"}
      ]
    }

── config.js ────────────────────────────────────────────────────────────────

The deployer writes this into the product at deploy time, every time:

    window.DUCORN = {apiBase: "http://192.168.1.24:8093", ...};

and skill 04 tells REX to read it:

    const API_BASE =
        (window.DUCORN && window.DUCORN.apiBase)
        || new URLSearchParams(location.search).get('api')
        || 'http://localhost:8765';

Three layers, most authoritative first: what the deploy actually chose, a
manual override for debugging, and a development default. The page stops
needing to be lucky, and stops needing the deployer to rewrite its source —
which is the other thing I was not going to do.

config.js is regenerated on every deploy and git-ignored, because it holds
this machine's LAN address and this deploy's ports. It is deployment output,
not source.
"""
import ast
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

TOOL = Path("/Users/ducorn/DC/ducorn/tools/DuCornDeployTool.py")
SKILL = Path("/Users/ducorn/DC/ducorn/skill_runner.py")
GITIGNORE = Path("/Users/ducorn/DC/ducorn-products/.gitignore")

tool_s = TOOL.read_text(encoding="utf-8")
skill_s = SKILL.read_text(encoding="utf-8")

if "def declared_services" in tool_s:
    sys.exit("Already patched — products declare their services.")
if "def plan_services" not in tool_s:
    sys.exit("Apply patch_deploy_services.py first. NOTHING WRITTEN.")
if "def product_urls" not in tool_s:
    sys.exit("Apply patch_product_url.py first. NOTHING WRITTEN.")
if "BUILD_SKILL" not in skill_s:
    sys.exit("Apply patch_build_ui_tests.py first. NOTHING WRITTEN.")

applied = []


def swap(label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {text.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    applied.append(label)
    return text.replace(old, new, 1)


# ═══ 1. the deployer reads the declaration ═══════════════════════════════════
tool_s = swap("declared", tool_s, "def plan_services(",
              '''SERVICE_MANIFEST = "service.json"
VALID_ROLES = {"api", "web", "software"}


def declared_services(product_dir: Path, first_port: int, python: str,
                      used: set) -> list:
    """
    The services the product says it has, or [] if it does not say.

    Reading a declaration instead of inferring one. The inference is right
    about what REX builds today and wrong about anything else — a Flask app or
    a server under src/ deploys as a plain script and its API never starts.

    A malformed manifest is reported and ignored rather than fatal: a product
    that mis-declares itself should fall back to the guess, not fail to deploy.
    """
    mf = product_dir / SERVICE_MANIFEST
    if not mf.is_file():
        return []
    try:
        import json as _json
        data = _json.loads(mf.read_text(errors="replace"))
        declared = data.get("services") or []
        if not isinstance(declared, list) or not declared:
            raise ValueError("no services listed")
    except Exception as e:
        print(f"⚠️  {SERVICE_MANIFEST} is unusable ({e}) — falling back to "
              f"inspecting the files", flush=True)
        return []

    slug = product_dir.name
    out, port = [], first_port
    for entry in declared:
        role = str(entry.get("role", "")).strip()
        if role not in VALID_ROLES:
            print(f"⚠️  {SERVICE_MANIFEST}: unknown role {role!r} — ignored",
                  flush=True)
            continue
        port = _free_port(port, used)
        used.add(port)
        health = [h for h in [entry.get("health")] if h] or (
            ["/health", "/docs", "/"] if role == "api" else ["/", "/index.html"])
        suffix = "" if not out else f"-{role}"
        spec = {"role": role, "label": f"com.ducorn.{slug}{suffix}",
                "port": port, "health": health, "cwd": str(product_dir),
                "log": f"/Users/ducorn/DC/logs/{slug}{suffix}.log"}

        if role == "api":
            module = str(entry.get("module") or "main:app")
            spec["args"] = [python, "-m", "uvicorn", module,
                            "--host", "0.0.0.0", "--port", str(port)]
            spec["module"] = module.split(":")[0]
        elif role == "web":
            root = product_dir / str(entry.get("root") or ".")
            spec["args"] = [python, "-m", "http.server", str(port),
                            "--directory", str(root)]
            spec["cwd"] = "/Users/ducorn/DC"
            spec["root"] = str(root)
        else:
            spec["args"] = [python, str(product_dir / str(entry.get("entry")
                                                          or "main.py"))]
        out.append(spec)
        port += 1

    if out:
        print(f"📋 {slug}: {SERVICE_MANIFEST} declares "
              + ", ".join(f"{s['role']} on :{s['port']}" for s in out),
              flush=True)
    return out


def write_page_config(services: list, product_dir: Path) -> str:
    """
    Tell the page where its API is, at deploy time.

    The alternative is what happened tonight: a page with localhost:8765 baked
    in, a deployer that allocated 8093, and a product that loaded perfectly and
    showed "Load failed". It worked in the end only because REX had built a
    ?api= override nobody asked him for.

    Regenerated every deploy and git-ignored — it holds this machine's address
    and this deploy's ports, which is output, not source.
    """
    web = next((sp for sp in services if sp["role"] == "web"), None)
    api = next((sp for sp in services if sp["role"] == "api"), None)
    if not web or not api:
        return ""
    root = Path(web.get("root") or product_dir)
    cfg = root / "config.js"
    body = (
        "// Written by DuCorn at deploy time. Do not edit — regenerated on\\n"
        "// every deploy, and git-ignored. Read it as:\\n"
        "//   (window.DUCORN && window.DUCORN.apiBase) || <your dev default>\\n"
        "window.DUCORN = {\\n"
        f'  apiBase: "http://{lan_ip()}:{api["port"]}",\\n'
        f'  deployedAt: "{__import__("datetime").datetime.now().isoformat(timespec="seconds")}"\\n'
        "};\\n")
    try:
        cfg.write_text(body, encoding="utf-8")
    except OSError as e:
        print(f"⚠️  could not write {cfg} ({e})", flush=True)
        return ""
    print(f"🔧 config.js          ← apiBase http://{lan_ip()}:{api['port']}",
          flush=True)
    return str(cfg)


def plan_services(''')

tool_s = swap("prefer declaration", tool_s, '''    used = _used_ports()
    used.add(first_port)
    services = []''',
              '''    used = _used_ports()
    used.add(first_port)

    # What the product says about itself wins over what its files suggest.
    declared = declared_services(product_dir, first_port, python, used)
    if declared:
        return declared

    services = []''')

tool_s = swap("write config", tool_s,
              '''            LAUNCHD_DIR.mkdir(exist_ok=True)
            started = []''',
              '''            # Before the services start, so the page has it on first load.
            write_page_config(services, product_dir)

            LAUNCHD_DIR.mkdir(exist_ok=True)
            started = []''')

# ═══ 2. REX is told the convention ═══════════════════════════════════════════
skill_s = swap("contract fn", skill_s, "def ui_test_contract(topic: str) -> str:",
               '''def deployment_contract(topic: str) -> str:
    """
    How this product will be started, and how its page finds its API.

    Both were guesses until now. The deployer inferred the shape from the file
    layout and the page found its backend because REX happened to add a ?api=
    override. Neither is a contract, and the next product would not be lucky
    twice.
    """
    return """

======================================================================
HOW THIS PRODUCT WILL BE DEPLOYED — TWO FILES YOU MUST GET RIGHT
======================================================================

1. service.json, in the product root. Declare every process this product
   needs. The deployer reads this and starts exactly what it says; without it
   the deployer inspects your files and guesses, and the guess only knows
   FastAPI under api/main.py plus an index.html at the root.

   A page backed by an API:

     {
       "services": [
         {"role": "api", "module": "api.main:app", "health": "/health"},
         {"role": "web", "root": ".", "health": "/"}
       ]
     }

   An API on its own:   [{"role": "api", "module": "main:app", "health": "/health"}]
   A page on its own:   [{"role": "web", "root": ".", "health": "/"}]
   A plain script:      [{"role": "software", "entry": "main.py"}]

   role must be api, web or software. health is the path the deploy smoke test
   will request; it MUST return 2xx once the service is up. A static page has
   no /health — say "/".

2. PORTS ARE NOT YOURS TO CHOOSE. The deployer allocates them at deploy time
   and they will not be the ones in your README. So a page must never hardcode
   its API address. Read it in this order:

     const API_BASE =
         (window.DUCORN && window.DUCORN.apiBase)      // written by the deploy
         || new URLSearchParams(location.search).get('api')   // manual override
         || 'http://localhost:8765';                   // local development

   Load config.js BEFORE your own script, and do not create it yourself — the
   deployer writes it on every deploy:

     <script src="config.js"></script>
     <script>/* your code, using API_BASE */</script>

   Add config.js to .gitignore. It holds one machine's address and one
   deploy's ports.

   A page that hardcodes its API URL will load, look correct, and show a
   connection error, because the port it was built against is not the port it
   was deployed on. This has already happened once.
======================================================================
"""


def ui_test_contract(topic: str) -> str:''')

skill_s = swap("inject", skill_s, '''    if skill_num == BUILD_SKILL:
        if _has_ui(topic):
            if not quiet:
                print(f"🖥️  skill {skill_num}: this product has an approved "
                      f"design — requiring browser tests", flush=True)
            return text + ui_test_contract(topic)
        return text''',
               '''    if skill_num == BUILD_SKILL:
        # Every product is deployed, so every build is told how deployment
        # works. The UI contract is additional, for products that ship a page.
        text = text + deployment_contract(topic)
        if _has_ui(topic):
            if not quiet:
                print(f"🖥️  skill {skill_num}: this product has an approved "
                      f"design — requiring browser tests", flush=True)
            return text + ui_test_contract(topic)
        return text''')

# ═══ 3. config.js is deployment output ═══════════════════════════════════════
gi = GITIGNORE.read_text(encoding="utf-8") if GITIGNORE.is_file() else ""
if "config.js" not in gi:
    GITIGNORE.write_text(
        gi.rstrip("\n") + "\n\n"
        "# Written by the deployer on every deploy: this machine's LAN address\n"
        "# and this deploy's ports. Output, not source.\n"
        "products/*/config.js\n", encoding="utf-8")
    applied.append("gitignore config.js")

# ── write both, or neither ───────────────────────────────────────────────────
stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backups = {}
for path in (TOOL, SKILL):
    b = path.with_name(f"{path.stem}.backup-manifest-{stamp}{path.suffix}")
    shutil.copy2(path, b)
    backups[path] = b


def die(msg):
    for path, b in backups.items():
        shutil.copy2(b, path)
    sys.exit(f"{msg} — both files reverted")


TOOL.write_text(tool_s, encoding="utf-8")
SKILL.write_text(skill_s, encoding="utf-8")

for path in (TOOL, SKILL):
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        die(f"SYNTAX ERROR in {path.name} ({e})")

import subprocess
for path in (TOOL, SKILL):
    r = subprocess.run([sys.executable, "-m", "pyflakes", str(path)],
                       capture_output=True, text=True)
    if [l for l in (r.stdout + r.stderr).splitlines() if "undefined name" in l]:
        die(f"{path.name} uses a name nothing defines:\\n{r.stdout}{r.stderr}")
print("syntax and undefined-name checks: clean")

# ── exercise the declaration ─────────────────────────────────────────────────
src = TOOL.read_text(encoding="utf-8")
t = ast.parse(src)
seg = {n.name: ast.get_source_segment(src, n) for n in t.body
       if isinstance(n, ast.FunctionDef)}
for need in ("declared_services", "write_page_config", "plan_services"):
    if need not in seg:
        die(f"{need} did not land")

import tempfile
ns = {"Path": Path, "_free_port": lambda p, used: p,
      "lan_ip": lambda: "192.168.1.24",
      "SERVICE_MANIFEST": "service.json",
      "VALID_ROLES": {"api", "web", "software"}}
exec(seg["declared_services"], ns)
exec(seg["write_page_config"], ns)
declare, writecfg = ns["declared_services"], ns["write_page_config"]

root = Path(tempfile.mkdtemp())


def product(name, manifest=None):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    if manifest is not None:
        (d / "service.json").write_text(json.dumps(manifest), encoding="utf-8")
    return d


print("\nwhat a declaration produces:")
CASES = [
    ("page+api", {"services": [
        {"role": "api", "module": "api.main:app", "health": "/health"},
        {"role": "web", "root": ".", "health": "/"}]},
     ["api", "web"], "the shape that took an hour to deploy"),
    ("flask-src", {"services": [
        {"role": "api", "module": "src.server:app", "health": "/ping"}]},
     ["api"], "a server the heuristic would never have found"),
    ("script", {"services": [{"role": "software", "entry": "run.py"}]},
     ["software"], "a plain script"),
    ("bad-role", {"services": [{"role": "wat"},
                               {"role": "web", "health": "/"}]},
     ["web"], "an unknown role is skipped, the rest still deploys"),
]
for name, manifest, want, why in CASES:
    got = [s["role"] for s in declare(product(name, manifest), 8100,
                                      "/py", set())]
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {name:12} {str(got):18} {why}")
    if not ok:
        die(f"{name}: expected {want}, got {got}")

for name, manifest, why in [
    ("none", None, "no manifest → fall back to inspecting the files"),
    ("empty", {"services": []}, "an empty list → fall back"),
]:
    got = declare(product(name, manifest), 8100, "/py", set())
    print(f"  {'ok  ' if got == [] else 'FAIL'} {name:12} {'[]':18} {why}")
    if got:
        die(f"{name} should have fallen back, got {got}")

broken = product("broken")
(broken / "service.json").write_text("{not json", encoding="utf-8")
if declare(broken, 8100, "/py", set()) != []:
    die("a malformed manifest must fall back, not deploy something wrong")
print("  ok   broken       []                 malformed → warned and ignored")

svcs = declare(product("ports", {"services": [
    {"role": "api", "module": "a:app"}, {"role": "web"}]}), 8100, "/py", set())
if svcs[0]["port"] == svcs[1]["port"]:
    die(f"declared services collided on a port: {[s['port'] for s in svcs]}")
if svcs[0]["label"] == svcs[1]["label"]:
    die("declared services share a launchd label")
print(f"  ok   ports        {[s['port'] for s in svcs]}         distinct ports and labels")

# config.js
d = product("cfg")
(d / "index.html").write_text("<h1>x</h1>", encoding="utf-8")
path = writecfg([{"role": "api", "port": 8093},
                 {"role": "web", "port": 8096, "root": str(d)}], d)
body = Path(path).read_text()
print("\nconfig.js the deployer writes:")
for line in body.strip().splitlines():
    print(f"    {line}")
if 'apiBase: "http://192.168.1.24:8093"' not in body:
    die("config.js does not carry the API base")
if writecfg([{"role": "web", "port": 8096, "root": str(d)}], d) != "":
    die("a product with no API must not get a config.js")
print("  ok   written only when there is an API to point at")

# the contract REX receives
ssrc = SKILL.read_text(encoding="utf-8")
st = ast.parse(ssrc)
dseg = next((ast.get_source_segment(ssrc, n) for n in st.body
             if isinstance(n, ast.FunctionDef)
             and n.name == "deployment_contract"), None)
if dseg is None:
    die("deployment_contract did not land")
ns2 = {}
exec(dseg, ns2)
contract = ns2["deployment_contract"]("zz")
for must in ("service.json", "window.DUCORN", "PORTS ARE NOT YOURS TO CHOOSE",
             "config.js", '"role": "api"', "URLSearchParams"):
    if must not in contract:
        die(f"the contract does not mention {must!r}")
print(f"\n  ok   the build contract is {len(contract):,} chars and names both files")

print("\napplied: " + ", ".join(applied))
for path, b in backups.items():
    print(f"backup:  {b.name}")
print()
print("Existing products have no service.json and keep deploying exactly as")
print("they do now — the declaration is preferred, never required.")
print()
print("The next build will be told the convention. To see it:")
print("  cd ~/DC && python3 scripts/doctor.py")
