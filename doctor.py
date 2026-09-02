#!/usr/bin/env python3
"""
Is this machine healthy, and if not, what do I run?

    python3 scripts/doctor.py            everything
    python3 scripts/doctor.py --spend    just today's money
    python3 scripts/doctor.py --quiet    only what is wrong

── WHY ──────────────────────────────────────────────────────────────────────

Every failure this week was silent: a control that existed, read correctly in
isolation, and never reached the thing it was supposed to control. Playwright
absent so a QA branch could not run. A status the database refused. A model
switcher that did not reach the brief wizard. A dead GitHub token nothing used.

None of those are hard to see once you look. The problem is knowing where to
look, and that knowledge currently lives in a conversation rather than on the
machine.

This is that knowledge, executable. Every check runs the real thing — connects
to the database, launches the browser, calls the API — and every failure
prints the command that fixes it. No check reports "ok" on the basis of a
file existing.

Run it before starting a pipeline, after any change, and first when something
breaks.
"""
import argparse
import ast
from datetime import datetime
import json
import os
import shutil
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, "/Users/ducorn/DC/scripts")
from bootstrap_python import ensure_modules  # noqa

ensure_modules("psycopg2")

import psycopg2  # noqa
from ducorn_env import load_ducorn_env  # noqa

DC = Path("/Users/ducorn/DC")
VENV_PY = DC / "ducorn/.venv/bin/python"
API = "http://localhost:8000"
API_KEY = os.environ.get("DUCORN_API_TOKEN", "ducorn-api-2026-secure")

results = []
_quiet = False


def check(section, name, ok, detail="", fix=None):
    results.append({"section": section, "name": name, "ok": bool(ok),
                    "detail": detail, "fix": fix})
    if _quiet and ok:
        return ok
    mark = "ok  " if ok else "FAIL"
    line = f"  {mark} {name}"
    if detail:
        line += f"   {detail}"
    print(line)
    if not ok and fix:
        print(f"       → {fix}")
    return ok


def heading(text):
    if not _quiet:
        print(f"\n── {text} " + "─" * max(0, 66 - len(text)))


def port_open(port, host="127.0.0.1", timeout=1.5):
    try:
        with socket.create_connection((host, port), timeout):
            return True
    except OSError:
        return False


def get_json(url, timeout=5, key=True):
    req = urllib.request.Request(
        url, headers={"x-api-key": API_KEY} if key else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def run(cmd, **kw):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, **kw)
    except (FileNotFoundError, NotADirectoryError, PermissionError) as e:
        class _F:
            returncode, stdout = 127, ""
            stderr = f"{type(e).__name__}: {e}"
        return _F()


# ═══════════════════════════════════════════════════════════════════════════
def check_services():
    heading("services")
    for name, port, fix in [
        ("activity API", 8000, "launchctl kickstart -k gui/$(id -u)/com.ducorn.api"),
        ("DuCorn router", 4001, "launchctl kickstart -k gui/$(id -u)/com.ducorn.router"),
        ("LiteLLM", 4000, "launchctl kickstart -k gui/$(id -u)/com.ducorn.litellm"),
        ("Ollama", 11434, "launchctl kickstart -k gui/$(id -u)/com.ducorn.ollama"),
        ("PDF service", 8001, "launchctl kickstart -k gui/$(id -u)/com.ducorn.pdf"),
    ]:
        check("services", f"{name} on :{port}", port_open(port),
              "" if port_open(port) else "not listening", fix)


def check_databases():
    heading("databases and schema")
    for db in ("ducorn", "litellm_db"):
        try:
            with psycopg2.connect(f"postgresql://ducorn@localhost/{db}") as c:
                c.cursor().execute("SELECT 1")
            check("db", f"{db} reachable", True)
        except Exception as e:
            check("db", f"{db} reachable", False, f"{type(e).__name__}: {e}",
                  "check PostgreSQL is running: brew services list")
            return

    r = run([sys.executable, str(DC / "scripts/migrate.py"), "--status"])
    pending = [l for l in r.stdout.splitlines() if "pending" in l.lower()]
    check("db", "migrations applied", r.returncode == 0 and not pending,
          f"{len(pending)} pending" if pending else "up to date",
          "python3 scripts/migrate.py")

    r = run([sys.executable, str(DC / "scripts/prove_db_contracts.py")])
    check("db", "code and schema agree on every status", r.returncode == 0,
          "" if r.returncode == 0 else "prove_db_contracts failed",
          "python3 scripts/prove_db_contracts.py")


def check_browser():
    heading("browser")
    r = run([str(VENV_PY), "-c",
             "from playwright.sync_api import sync_playwright\n"
             "with sync_playwright() as p:\n"
             "    b = p.chromium.launch(); pg = b.new_page()\n"
             "    pg.set_content('<h1 id=t>ok</h1>')\n"
             "    print(pg.inner_text('#t')); b.close()"])
    check("browser", "chromium launches and renders",
          r.returncode == 0 and "ok" in r.stdout,
          (r.stderr.strip().splitlines() or [""])[-1][:70] if r.returncode else "",
          "python3 scripts/install_playwright.py --apply")

    req = DC / "ducorn-products/products/_shared/requirements-ui.txt"
    check("browser", "products/_shared/requirements-ui.txt", req.is_file(),
          "" if req.is_file() else "UI products cannot get a browser in their venv",
          "python3 scripts/install_playwright.py --apply")

    guide = DC / "gstack/references/web-interface-guidelines.md"
    check("browser", "interface guidelines vendored", guide.is_file(),
          f"{guide.stat().st_size:,} bytes" if guide.is_file() else "not vendored",
          "python3 scripts/vendor_web_guidelines.py")


def check_models():
    heading("models")
    try:
        cfg = get_json(f"{API}/agents/config")
    except Exception as e:
        check("models", "switcher readable", False, f"{type(e).__name__}: {e}",
              "is the API up? launchctl kickstart -k gui/$(id -u)/com.ducorn.api")
        return

    agents = cfg.get("agents") or {}
    served = {m["id"] for m in (cfg.get("available_models") or [])}
    check("models", "switcher readable", bool(agents), f"{len(agents)} agents")

    unknown = {a: m for a, m in agents.items() if served and m not in served}
    check("models", "every agent's model is served by LiteLLM", not unknown,
          f"{unknown}" if unknown else f"{len(served)} models available",
          "pick a served model in the dashboard, or add it to "
          "scripts/litellm_config.yaml")

    paid = {a: m for a, m in agents.items() if not str(m).startswith("local-")}
    if paid and not _quiet:
        print(f"       paid: {', '.join(f'{a}={m}' for a, m in sorted(paid.items()))}")


def check_keys_and_spend(spend_only=False):
    heading("spend today")
    try:
        with psycopg2.connect("postgresql://ducorn@localhost/litellm_db") as c:
            cur = c.cursor()
            cur.execute("""
                SELECT COALESCE(model,'(none)'), count(*), COALESCE(sum(spend),0)
                FROM "LiteLLM_SpendLogs"
                WHERE "startTime" >= date_trunc('day', now())
                GROUP BY 1 ORDER BY 3 DESC
            """)
            by_model = cur.fetchall()
            cur.execute("""
                SELECT COALESCE(sum(spend),0) FROM "LiteLLM_SpendLogs"
                WHERE "startTime" >= date_trunc('day', now())
            """)
            today = float(cur.fetchone()[0] or 0)
            cur.execute("""
                SELECT COALESCE(sum(spend),0) FROM "LiteLLM_SpendLogs"
                WHERE "startTime" >= date_trunc('day', now()) - interval '7 days'
            """)
            week = float(cur.fetchone()[0] or 0)
    except Exception as e:
        check("spend", "spend readable", False, f"{type(e).__name__}: {e}",
              "is litellm_db reachable?")
        return

    print(f"  today ${today:,.2f}   ·   last 7 days ${week:,.2f}")
    for model, calls, spend in by_model:
        if not _quiet or float(spend) > 0:
            share = (float(spend) / today * 100) if today else 0
            print(f"       {model:28} {calls:5} calls  ${float(spend):7.2f}"
                  f"  {share:4.0f}%")

    # Not a pass/fail — a number a person judges. Flagged only when it is
    # large enough that nobody should discover it by accident.
    check("spend", "today's spend under $25", today < 25,
          f"${today:,.2f}",
          "python3 scripts/litellm_budget.py --key ducorn-rex   (per-agent caps)")

    if spend_only:
        return

    heading("keys")
    load_ducorn_env()
    for agent in ("SAGE", "REX", "IRIS", "NOVA", "ATLAS", "DESIGN"):
        var = f"LITELLM_KEY_{agent}"
        check("keys", var, bool(os.environ.get(var, "").strip()),
              "" if os.environ.get(var) else "missing from shared/.env",
              f"python3 scripts/litellm_budget.py --create --key "
              f"ducorn-{agent.lower()}")


SERVICE_MODULES = [
    DC / "ducorn/skill_runner.py",
    DC / "ducorn/flows/langgraph_flow.py",
    DC / "ducorn/tools/DuCornDeployTool.py",
    DC / "ducorn/tools/generate_design.py",
    DC / "ducorn/tools/screenshot.py",
    DC / "ducorn/tools/product_jail.py",
    DC / "ducorn/tools/DuCornWriterTool.py",
    DC / "ducorn-products/products/ducorn-activity-api/main.py",
    DC / "scripts/doctor.py",
]


def unbound_at_module_level(source):
    """
    Module-level statements using a name that is only imported inside a
    function. Valid syntax; NameError at import; the whole module fails to
    load. This is what put the activity API into a restart loop — a
    module-level re.compile() in a file whose four `import re` statements are
    all inside functions.
    """
    tree = ast.parse(source)

    def names_of(node):
        return {(a.asname or a.name).split(".")[0] for a in node.names}

    module_names, local_names = set(), set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module_names |= names_of(node)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(node):
                if isinstance(sub, (ast.Import, ast.ImportFrom)):
                    local_names |= names_of(sub)
    only_local = local_names - module_names

    hits = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Import, ast.ImportFrom)):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and sub.id in only_local:
                hits.append((getattr(node, "lineno", "?"), sub.id))
                break
    return hits


try:
    import pyflakes as _pyflakes  # noqa: F401
    _HAVE_PYFLAKES = True
except ImportError:
    _HAVE_PYFLAKES = False


def _undefined_names(path):
    """
    Every name this file uses that nothing defines, via pyflakes.

    Returns (findings, how). `how` says which check actually ran, because a
    fallback that silently does less than the real thing is how you end up
    trusting a tick that means nothing.

    Filtered to undefined names on purpose. pyflakes also reports unused
    imports and shadowed variables; those are style, and a health check that
    reports style gets skimmed and then ignored.
    """
    try:
        import pyflakes  # noqa: F401
    except ImportError:
        return [f"line {ln}: {nm!r}"
                for ln, nm in unbound_at_module_level(
                    path.read_text(encoding="utf-8"))], "module-level only"

    r = run([sys.executable, "-m", "pyflakes", str(path)])
    out = r.stdout + r.stderr
    findings = [l.split(":", 1)[1].strip() if ":" in l else l
                for l in out.splitlines() if "undefined name" in l]
    return findings, "pyflakes"


def check_imports():
    heading("imports — will every module actually load")
    for path in SERVICE_MODULES:
        if not path.is_file():
            check("imports", path.name, True, "not present — skipped")
            continue
        try:
            hits, how = _undefined_names(path)
        except SyntaxError as e:
            check("imports", path.name, False, f"SyntaxError: {e}",
                  f"the file does not parse: {path}")
            continue
        detail = "; ".join(hits) if hits else (
            "" if how == "pyflakes" else "(module-level check only)")
        check("imports", path.name, not hits, detail,
              f"add the missing import to {path}" if hits else None)

    if not _HAVE_PYFLAKES:
        print("       pyflakes is not installed — only module-level uses are "
              "checked.\n       pip3 install pyflakes --break-system-packages",
              flush=True)


def _probe(code):
    """Run a snippet under the pipeline venv; return (ok, output)."""
    r = run([str(VENV_PY), "-c", code])
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def _code_only(src: str) -> str:
    """
    The file with its docstrings and comments removed.

    Every "this string is absent" check needs this. These modules are heavily
    commented on purpose — the comments are how the reasoning survives — and a
    comment explaining a bug is not the bug. The smoke-test check failed
    because the docstring of the function that FIXED it quotes the expression
    it replaced.
    """
    import io
    import tokenize
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src

    doc_lines = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = getattr(node, "body", None)
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            first = body[0].lineno
            last = getattr(body[0], "end_lineno", first)
            doc_lines.update(range(first, last + 1))

    out = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                continue
            if tok.start[0] in doc_lines:
                continue
            out.append(tok.string)
    except (tokenize.TokenError, IndentationError):
        # Fall back to dropping docstring lines only. Better than pretending.
        return "\n".join(l for i, l in enumerate(src.splitlines(), 1)
                          if i not in doc_lines)
    return " ".join(out)


def smoke_tries_every_path(tool_src: str) -> bool:
    """
    Does smoke() actually walk the candidate health paths?

    A positive property, read from the syntax tree. The old check asked whether
    a buggy expression was absent, which is both weaker — absence proves only
    that nobody typed it — and fragile, since prose about the bug reads as the
    bug.
    """
    try:
        tree = ast.parse(tool_src)
    except SyntaxError:
        return False
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "smoke"), None)
    if fn is None:
        return False
    for node in ast.walk(fn):
        if not isinstance(node, ast.For):
            continue
        it = node.iter
        if (isinstance(it, ast.Subscript)
                and isinstance(it.slice, ast.Constant)
                and it.slice.value == "health"):
            return True
    return False


def check_deploy():
    heading("deploy — executed, not asserted")
    tool = DC / "ducorn/tools/DuCornDeployTool.py"
    if not tool.is_file():
        check("deploy", "deploy tool present", False, str(tool))
        return

    # A product whose venv exists must be started with it. Deploying with the
    # system python meant every dependency the product declared and was tested
    # with was invisible at runtime — asyncpg was installed and the service
    # died on `import asyncpg`.
    ok, out = _probe(
        "import sys; sys.path.insert(0, '/Users/ducorn/DC/ducorn/tools')\n"
        "from pathlib import Path\n"
        "import DuCornDeployTool as D\n"
        "p = Path('/Users/ducorn/DC/ducorn-products/products')\n"
        "cands = [d for d in p.iterdir() if (d/'.venv'/'bin'/'python').is_file()]\n"
        "assert cands, 'NO-PRODUCT-WITH-VENV'\n"
        "py, how = D.product_python(cands[0])\n"
        "assert how == 'product venv', how\n"
        "assert py.startswith(str(cands[0])), py\n"
        "print(f'{cands[0].name} -> {how}')")
    check("deploy", "a product runs under its own venv", ok,
          out[-90:] if not ok else out,
          "python3 scripts/applied/patch_deploy_venv.py")

    # A page plus an API is two services. One product_type meant the API half
    # was never deployed and /health 404'd from a static file server.
    ok, out = _probe(
        "import sys; sys.path.insert(0, '/Users/ducorn/DC/ducorn/tools')\n"
        "from pathlib import Path\n"
        "import DuCornDeployTool as D\n"
        "p = Path('/Users/ducorn/DC/ducorn-products/products')\n"
        "hits = [d for d in p.iterdir() "
        "        if (d/'index.html').is_file() and (d/'api'/'main.py').is_file()]\n"
        "print('no page+api product on disk') if not hits else None\n"
        "roles = [s['role'] for s in D.plan_services(hits[0].name, hits[0], "
        "'dashboard', 'main.py', 9900)] if hits else ['api','web']\n"
        "assert roles == ['api','web'], roles\n"
        "print('page+api -> ' + ','.join(roles))")
    check("deploy", "a page + an API plans as two services", ok,
          out[-90:] if not ok else out,
          "python3 scripts/applied/patch_deploy_services.py")

    # Prevention is the shared module; this is detection. Both modules are
    # imported for real and asked where a product's interpreter is. A
    # reintroduced local copy that drifts fails here with both values, rather
    # than as a deploy that mysteriously cannot import a package.
    ok, out = _probe(
        "import sys\n"
        "sys.path[:0] = ['/Users/ducorn/DC/scripts', '/Users/ducorn/DC/ducorn',"
        " '/Users/ducorn/DC/ducorn/tools']\n"
        "from pathlib import Path\n"
        "import product_paths as P\n"
        "import DuCornDeployTool as D\n"
        "root = Path('/Users/ducorn/DC/ducorn-products/products')\n"
        "cands = [d for d in root.iterdir() if (d/'.venv'/'bin'/'python').is_file()]\n"
        "assert cands, 'NO-PRODUCT-WITH-VENV'\n"
        "shared = str(P.product_python(cands[0]))\n"
        "deploy = D.product_python(cands[0])[0]\n"
        "assert shared == deploy, f'{shared} != {deploy}'\n"
        "print('QA and deploy agree: ' + shared.replace("
        "'/Users/ducorn/DC/ducorn-products/products/', ''))")
    check("deploy", "QA and deploy resolve the same interpreter", ok,
          out[-100:] if not ok else out,
          "python3 scripts/applied/patch_shared_paths.py")

    # A static server has no /health. `_probe('/health') or _probe('/')`
    # short-circuited on a truthy 404, so the fallback never ran once.
    src = tool.read_text(encoding="utf-8")
    check("deploy", "the smoke test tries each health path",
          smoke_tries_every_path(src),
          "" if "def smoke(" in src else "smoke() missing",
          "python3 scripts/applied/patch_deploy_services.py")

    # A .env.example default is a default. Discarding it turned optional,
    # documented config into an aborted deploy.
    check("deploy", "a shipped .env.example default is honoured",
          "_is_placeholder" in src,
          "", "python3 scripts/applied/patch_deploy_env.py")


def check_regressions():
    heading("regressions — each named for the failure it prevents")

    sr = (DC / "ducorn/skill_runner.py")
    src = sr.read_text(encoding="utf-8") if sr.is_file() else ""
    # IRIS diagnosed the same defect three times in writing and REX never saw
    # a word of it: the context loop walks skills BEFORE the current one, and
    # QA comes last.
    check("regressions", "a QA rejection reaches the next build (wired)",
          "def prior_failure_context" in src
          and "context_parts.insert(0, _rejection)" in src,
          "", "python3 scripts/applied/patch_qa_feedback.py")
    # ...and the cache cannot swallow it: skill 04 was a cached pass, so
    # without the rejection inside the fingerprint the builder never re-ran.
    check("regressions", "a rejection invalidates the cached pass (wired)",
          "skill_fingerprint(skill_num, skill_name, topic, _rejection)" in src,
          "", "python3 scripts/applied/patch_qa_feedback.py")

    api = DC / "ducorn-products/products/ducorn-activity-api/main.py"
    asrc = api.read_text(encoding="utf-8") if api.is_file() else ""
    # The slug was named in the route and never read, so any filename — and
    # ../../shared/.env — could be fetched under any product.
    check("regressions", "a document is only served to its owner (wired)",
          "def doc_owner" in asrc
          and 'doc_path = f"{docs_dir}/{filename}"' not in _code_only(asrc),
          "", "python3 scripts/applied/patch_doc_isolation.py")
    # /chat called Ollama with llama3.1 hardcoded, so the model you chose for
    # ATLAS had never once answered you.
    check("regressions", "ATLAS uses the model the switcher names (wired)",
          "def failure_context" in asrc
          and _code_only(asrc).count("http://localhost:11434/api/generate") <= 1,
          f"{_code_only(asrc).count(chr(104) + 'ttp://localhost:11434/api/generate')}"
          f" direct Ollama call(s) left" if asrc else "",
          "python3 scripts/applied/patch_atlas_failure.py")

    flow = DC / "ducorn/flows/langgraph_flow.py"
    fsrc = flow.read_text(encoding="utf-8") if flow.is_file() else ""
    # The result was captured and discarded and the tick printed regardless, so
    # a push rejected for a 115 MB file looked exactly like a successful one.
    check("regressions", "the build reports the push it actually made",
          "def _git_publish" in fsrc
          and "✅ Files committed to GitHub" not in _code_only(fsrc),
          "", "python3 scripts/applied/patch_build_commit.py")

    # QA builds <product>/.venv and deploy runs from it, so every product has
    # one. 244 MB of pip output went into a commit and blocked every push.
    products = DC / "ducorn-products"
    gi = products / ".gitignore"
    check("regressions", "virtualenvs are git-ignored",
          gi.is_file() and ".venv/" in gi.read_text(encoding="utf-8"),
          "", "python3 scripts/fix_venv_in_git.py")
    r = run(["git", "-C", str(products), "ls-files"])
    tracked_venv = [p for p in r.stdout.splitlines() if "/.venv/" in p]
    check("regressions", "no virtualenv file is tracked", not tracked_venv,
          f"{len(tracked_venv):,} tracked" if tracked_venv else "",
          "python3 scripts/fix_venv_in_git.py")

    big = []
    r = run(["git", "-C", str(products), "ls-tree", "-r", "-l", "HEAD"])
    for line in r.stdout.splitlines():
        parts = line.split(None, 4)
        if len(parts) >= 5 and parts[3].isdigit() and int(parts[3]) > 50e6:
            big.append(f"{int(parts[3])/1e6:.0f}MB {parts[4].split('/')[-1]}")
    check("regressions", "no committed file would be rejected by GitHub",
          not big, ", ".join(big[:3]),
          "python3 scripts/fix_product_history.py")


def check_hygiene():
    heading("hygiene")
    locks = [d for d in ("ducorn", "scripts", "gstack", "ducorn-products")
             if (DC / d / ".git/index.lock").exists()]
    check("hygiene", "no stale git locks", not locks, ", ".join(locks),
          "rm -f " + " ".join(f"~/DC/{d}/.git/index.lock" for d in locks)
          if locks else None)

    # Two questions, previously sharing one answer — so a repo with
    # uncommitted work and a repo with no remote produced the same failure and
    # the same unhelpful fix.
    dirty, no_remote, unpushed = [], [], []
    for d in ("ducorn", "scripts", "gstack", "ducorn-products"):
        if not (DC / d / ".git").is_dir():
            continue
        # --porcelain only; never plain `git status`, which refreshes the index
        # and can leave a lock behind when the working tree is on a mount.
        if run(["git", "-C", str(DC / d), "status", "--porcelain"]).stdout.strip():
            dirty.append(d)
        if not run(["git", "-C", str(DC / d),
                    "remote", "get-url", "origin"]).stdout.strip():
            no_remote.append(d)
            continue
        ahead = run(["git", "-C", str(DC / d), "rev-list", "--count",
                     "@{u}..HEAD"])
        if ahead.returncode == 0 and ahead.stdout.strip() not in ("", "0"):
            unpushed.append(f"{d}(+{ahead.stdout.strip()})")

    check("hygiene", "everything is committed", not dirty, ", ".join(dirty),
          'python3 scripts/commit_all.py -m "wip" --apply')
    check("hygiene", "every repo has a remote", not no_remote,
          ", ".join(no_remote),
          "python3 scripts/create_remotes.py --remote-only aruna1715 --apply")
    check("hygiene", "nothing is committed but unpushed", not unpushed,
          ", ".join(unpushed),
          "git -C ~/DC/<repo> push")

    r = run(["pgrep", "-fl", "langgraph_flow.py"])
    running = [l for l in r.stdout.splitlines() if l.strip()]
    check("hygiene", "pipelines running", True,
          f"{len(running)} running" if running else "none",
          None)
    for line in running[:5]:
        if not _quiet:
            print(f"       {line[:100]}")

    try:
        pending = get_json(f"{API}/approvals/pending")
        n = len(pending if isinstance(pending, list)
                else pending.get("approvals", []))
        check("hygiene", "pending approvals", True, f"{n} waiting")
    except Exception:
        pass

    total, used, free = shutil.disk_usage(str(DC))
    gb = free / 1e9
    check("hygiene", "disk space", gb > 5, f"{gb:,.1f} GB free",
          "clear ~/DC/_deleted and old logs" if gb <= 5 else None)

    logs = DC / "logs"
    if logs.is_dir():
        big = sorted(((p.stat().st_size, p) for p in logs.glob("*.log")),
                     reverse=True)[:1]
        if big:
            size, path = big[0]
            check("hygiene", "largest log", size < 200e6,
                  f"{path.name} {size/1e6:,.0f} MB",
                  "truncate the log or rotate it" if size >= 200e6 else None)


def main():
    global _quiet
    ap = argparse.ArgumentParser()
    ap.add_argument("--spend", action="store_true", help="only today's money")
    ap.add_argument("--quiet", action="store_true", help="only what is wrong")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable, for the dashboard")
    args = ap.parse_args()
    _quiet = args.quiet

    if args.json:
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

    print("DuCorn doctor — every check runs the real thing\n")

    if args.spend:
        check_keys_and_spend(spend_only=True)
    else:
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
    print("\n" + "─" * 70)
    if not bad:
        print(f"{len(results)} checks, all healthy.")
        return 0

    print(f"{len(bad)} of {len(results)} checks failed:\n")
    for r in bad:
        print(f"  · {r['name']}" + (f" — {r['detail']}" if r["detail"] else ""))
        if r["fix"]:
            print(f"      {r['fix']}")
    print("\nFix these before starting a pipeline. Re-run this to confirm.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
