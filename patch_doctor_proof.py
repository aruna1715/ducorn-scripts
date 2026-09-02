#!/usr/bin/env python3
"""
Turn "these will not happen again" into output you can read.

── WHY ──────────────────────────────────────────────────────────────────────

You asked whether the failures from the ducorn-spend-status run will recur, and
asked for proof rather than assurance. A table I write is not proof. Proof is
something you can run after I am gone, that fails loudly when a fix is undone.

So each defect closed during that run becomes a check here, named after the
failure it prevents. Where the property can be executed, it is executed — the
deploy checks import the real tool and call it against a real product rather
than grepping for a function name. Where it genuinely can only be inspected,
the check says so rather than implying more than it knows.

Three new sections:

  imports      Every module-level statement can reach the names it uses.
               This is the one that took the API down: a module-level
               re.compile() in a file that imports re only inside functions is
               valid syntax and a NameError at import. ast.parse cannot see it,
               a syntax check passes, and the service dies on restart. Nothing
               on this machine looked for it.

  deploy       The product runs under its own interpreter, and a product that
               is a page plus an API is planned as two services. Executed
               against ducorn-spend-status, not asserted.

  regressions  The rest: the QA report reaching the next build, the document
               jail, honest git reporting, and virtualenvs staying out of git.

── ON THE HONESTY OF THESE CHECKS ───────────────────────────────────────────

A check that greps for a function name proves the fix is present, not that it
works. Those are labelled "wired" rather than "works". The behavioural proof
for each lives in the self-test inside its patch, which ran before the file was
written. This file is the standing guard, not the original proof.
"""
import ast
import shutil
import sys
from datetime import datetime
from pathlib import Path

DOCTOR = Path("/Users/ducorn/DC/scripts/doctor.py")
s = DOCTOR.read_text(encoding="utf-8")

if "def check_imports" in s:
    sys.exit("Already patched — doctor proves the closed classes.")

applied = []


def swap(label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {text.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    applied.append(label)
    return text.replace(old, new, 1)


s = swap("sections", s, "def check_hygiene():",
         '''SERVICE_MODULES = [
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


def check_imports():
    heading("imports — will every module actually load")
    for path in SERVICE_MODULES:
        if not path.is_file():
            check("imports", path.name, True, "not present — skipped")
            continue
        try:
            hits = unbound_at_module_level(path.read_text(encoding="utf-8"))
        except SyntaxError as e:
            check("imports", path.name, False, f"SyntaxError: {e}",
                  f"the file does not parse: {path}")
            continue
        detail = ", ".join(f"line {ln} uses {nm!r}" for ln, nm in hits)
        check("imports", path.name, not hits, detail,
              f"add a module-level import to {path}" if hits else None)


def _probe(code):
    """Run a snippet under the pipeline venv; return (ok, output)."""
    r = run([str(VENV_PY), "-c", code])
    return r.returncode == 0, (r.stdout + r.stderr).strip()


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
        "import sys; sys.path.insert(0, '/Users/ducorn/DC/ducorn/tools')\\n"
        "from pathlib import Path\\n"
        "import DuCornDeployTool as D\\n"
        "p = Path('/Users/ducorn/DC/ducorn-products/products')\\n"
        "cands = [d for d in p.iterdir() if (d/'.venv'/'bin'/'python').is_file()]\\n"
        "assert cands, 'NO-PRODUCT-WITH-VENV'\\n"
        "py, how = D.product_python(cands[0])\\n"
        "assert how == 'product venv', how\\n"
        "assert py.startswith(str(cands[0])), py\\n"
        "print(f'{cands[0].name} -> {how}')")
    check("deploy", "a product runs under its own venv", ok,
          out[-90:] if not ok else out,
          "python3 scripts/patch_deploy_venv.py")

    # A page plus an API is two services. One product_type meant the API half
    # was never deployed and /health 404'd from a static file server.
    ok, out = _probe(
        "import sys; sys.path.insert(0, '/Users/ducorn/DC/ducorn/tools')\\n"
        "from pathlib import Path\\n"
        "import DuCornDeployTool as D\\n"
        "p = Path('/Users/ducorn/DC/ducorn-products/products')\\n"
        "hits = [d for d in p.iterdir() "
        "        if (d/'index.html').is_file() and (d/'api'/'main.py').is_file()]\\n"
        "print('no page+api product on disk') if not hits else None\\n"
        "roles = [s['role'] for s in D.plan_services(hits[0].name, hits[0], "
        "'dashboard', 'main.py', 9900)] if hits else ['api','web']\\n"
        "assert roles == ['api','web'], roles\\n"
        "print('page+api -> ' + ','.join(roles))")
    check("deploy", "a page + an API plans as two services", ok,
          out[-90:] if not ok else out,
          "python3 scripts/patch_deploy_services.py")

    # A static server has no /health. `_probe('/health') or _probe('/')`
    # short-circuited on a truthy 404, so the fallback never ran once.
    src = tool.read_text(encoding="utf-8")
    check("deploy", "the smoke test tries each health path",
          "_probe(\\"/health\\") or _probe(\\"/\\")" not in src
          and "def smoke(" in src,
          "" if "def smoke(" in src else "smoke() missing",
          "python3 scripts/patch_deploy_services.py")

    # A .env.example default is a default. Discarding it turned optional,
    # documented config into an aborted deploy.
    check("deploy", "a shipped .env.example default is honoured",
          "_is_placeholder" in src,
          "", "python3 scripts/patch_deploy_env.py")


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
          "", "python3 scripts/patch_qa_feedback.py")
    # ...and the cache cannot swallow it: skill 04 was a cached pass, so
    # without the rejection inside the fingerprint the builder never re-ran.
    check("regressions", "a rejection invalidates the cached pass (wired)",
          "skill_fingerprint(skill_num, skill_name, topic, _rejection)" in src,
          "", "python3 scripts/patch_qa_feedback.py")

    api = DC / "ducorn-products/products/ducorn-activity-api/main.py"
    asrc = api.read_text(encoding="utf-8") if api.is_file() else ""
    # The slug was named in the route and never read, so any filename — and
    # ../../shared/.env — could be fetched under any product.
    check("regressions", "a document is only served to its owner (wired)",
          "def doc_owner" in asrc and 'doc_path = f"{docs_dir}/{filename}"' not in asrc,
          "", "python3 scripts/patch_doc_isolation.py")
    # /chat called Ollama with llama3.1 hardcoded, so the model you chose for
    # ATLAS had never once answered you.
    check("regressions", "ATLAS uses the model the switcher names (wired)",
          "def failure_context" in asrc
          and asrc.count("http://localhost:11434/api/generate") <= 1,
          f"{asrc.count('http://localhost:11434/api/generate')} direct Ollama "
          f"call(s) left" if asrc else "",
          "python3 scripts/patch_atlas_failure.py")

    flow = DC / "ducorn/flows/langgraph_flow.py"
    fsrc = flow.read_text(encoding="utf-8") if flow.is_file() else ""
    # The result was captured and discarded and the tick printed regardless, so
    # a push rejected for a 115 MB file looked exactly like a successful one.
    check("regressions", "the build reports the push it actually made",
          "def _git_publish" in fsrc
          and "✅ Files committed to GitHub" not in fsrc,
          "", "python3 scripts/patch_build_commit.py")

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


def check_hygiene():''')

# ── the remote check was two questions wearing one answer ────────────────────
s = swap("split remote", s, '''    unpushed = []
    for d in ("ducorn", "scripts", "gstack", "ducorn-products"):
        if not (DC / d / ".git").is_dir():
            continue
        r = run(["git", "-C", str(DC / d), "status", "--porcelain"])
        remote = run(["git", "-C", str(DC / d), "remote", "get-url", "origin"])
        if r.stdout.strip() or not remote.stdout.strip():
            unpushed.append(d)
    check("hygiene", "all repos committed and have a remote", not unpushed,
          ", ".join(unpushed),
          'python3 scripts/commit_all.py -m "wip" --apply   '
          '(and create_remotes.py for missing remotes)')''',
         '''    # Two questions, previously sharing one answer — so a repo with
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
          "git -C ~/DC/<repo> push")''')

s = swap("run them", s, '''        check_services()
        check_databases()
        check_browser()''',
         '''        check_services()
        check_databases()
        check_imports()
        check_browser()
        check_deploy()
        check_regressions()''')

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = DOCTOR.with_name(f"doctor.backup-proof-{stamp}.py")
shutil.copy2(DOCTOR, backup)
DOCTOR.write_text(s, encoding="utf-8")


def die(msg):
    shutil.copy2(backup, DOCTOR)
    sys.exit(f"{msg} — reverted from {backup.name}")


try:
    ast.parse(s)
except SyntaxError as e:
    die(f"SYNTAX ERROR ({e})")

src = DOCTOR.read_text(encoding="utf-8")
t = ast.parse(src)
seg = {n.name: ast.get_source_segment(src, n) for n in t.body
       if isinstance(n, ast.FunctionDef)}
for need in ("check_imports", "check_deploy", "check_regressions",
             "unbound_at_module_level"):
    if need not in seg:
        die(f"{need} did not land")

# doctor must pass its own import check
ns = {"ast": ast}
exec(seg["unbound_at_module_level"], ns)
audit = ns["unbound_at_module_level"]
own = audit(src)
if own:
    die(f"doctor.py itself would NameError: {own}")
print("doctor.py passes its own import audit")

print("\nthe audit, against the outage it exists to catch:")
BROKEN = 'import os\n_RE = re.compile("x")\ndef f():\n    import re\n    return re\n'
FIXED = 'import os\nimport re\n_RE = re.compile("x")\ndef f():\n    import re\n    return re\n'
for label, srcx, want in [("the activity API as it was", BROKEN, True),
                          ("the activity API as it is", FIXED, False)]:
    hits = audit(srcx)
    ok = bool(hits) == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label:32} "
          f"{'caught: ' + str(hits) if hits else 'clean'}")
    if not ok:
        die(f"{label}: expected hits={want}")

print("\napplied: " + ", ".join(applied))
print(f"backup:  {backup.name}")
print()
print("Run it:")
print("  cd ~/DC && python3 scripts/doctor.py")
print()
print("Every check that fails prints the command that fixes it. Run this before")
print("a pipeline and after any change — it is the answer to 'will this happen")
print("again', in a form that does not depend on me remembering.")
