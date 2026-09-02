#!/usr/bin/env python3
"""
A product that ships a working default should deploy with it.

── WHAT BLOCKED THE DEPLOY ──────────────────────────────────────────────────

    Deploy FAILED — ducorn-spend-status
    the product declares configuration that could not be resolved:
    ['ALLOWED_ORIGINS']. Add them to /Users/ducorn/DC/shared/.env and redeploy.

REX wrote this in the product's own .env.example, deliberately, with a comment
explaining it:

    # Comma-separated list of origins allowed by the CORS middleware.
    # Set to the exact URL where index.html is served from.
    ALLOWED_ORIGINS=http://localhost:8766,http://127.0.0.1:8766

The code uses os.environ.get("ALLOWED_ORIGINS", <same default>). The README
lists it as Required: No. Skill 05 and skill 06 both noted it defaults safely.
Every layer of the pipeline agreed this variable is optional and documented.

Then the deploy guard read the file like this:

    key = line.split("=", 1)[0].strip()
    val = os.environ.get(key) or shared.get(key) or ""

It takes the key and throws the value away. The default the product ships —
the entire point of a .env.example — is never consulted. So an optional
setting with a working default is reported as unresolvable configuration and
the deploy stops.

── AND THE ADVICE IS WORSE THAN THE ERROR ───────────────────────────────────

"Add them to /Users/ducorn/DC/shared/.env" is the wrong instruction for this
key. shared/.env is machine-wide. ALLOWED_ORIGINS is a per-product CORS list —
put this product's origins there and every other product that reads
ALLOWED_ORIGINS inherits them. That is configuration bleeding from one product
into another, which is a quieter form of the isolation rule you called a
showstopper.

An operator with no Claude would have followed that instruction, because it is
specific, confident and wrong. This is the failure mode that matters for
independence: not a missing message, but a misleading one.

── THE SAME BUG IN THE OTHER DIRECTION ──────────────────────────────────────

    val = os.environ.get(key) or shared.get(key)

shared/.env silently outranks everything the product says about itself. This
product's .env.example documents DATABASE_URL as litellm_db and warns, in
capitals, that the database holds live LangGraph checkpoints and a write could
corrupt a running pipeline. If shared/.env names a different database, the
product gets it, silently, with no record of the substitution.

── THE RULE ─────────────────────────────────────────────────────────────────

Most specific source wins, and every choice is printed:

    1. the product's own .env      — the operator's choice for THIS product
    2. the deploy environment
    3. shared/.env                 — the machine's shared secrets
    4. the .env.example default    — what the product ships
    5. nothing → genuinely missing

A default is only a default if it is a real value: empty, `changeme`,
`your-key-here`, `<fill me in>` and friends are placeholders and do not count.

At deploy time the resolution is printed, one line per key with its source, so
a substitution is visible rather than assumed:

    🔧 ALLOWED_ORIGINS      ← .env.example default
    🔧 DATABASE_URL         ← shared/.env

And "missing" now means what it says: no source anywhere supplies a value.
"""
import ast
import shutil
import sys
from datetime import datetime
from pathlib import Path

TOOL = Path("/Users/ducorn/DC/ducorn/tools/DuCornDeployTool.py")
s = TOOL.read_text(encoding="utf-8")

if "_is_placeholder" in s:
    sys.exit("Already patched — shipped defaults are honoured.")

applied = []


def swap(label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {text.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    applied.append(label)
    return text.replace(old, new, 1)


# ── module-level import, because _PLACEHOLDER_RE needs it ────────────────────
#
# This file imports re inside a function (the port scan). A module-level
# re.compile without a module-level import is a NameError at import time, which
# is how I took the activity API down an hour ago. Not twice.
if "\nimport re\n" not in s.split("class DuCornDeployTool", 1)[0]:
    s = swap("import re", s, "import os\nimport subprocess\n",
             "import os\nimport re\nimport subprocess\n")

# ── placeholders and value parsing ───────────────────────────────────────────
s = swap("helpers", s, '''def resolve_product_env(product_dir: Path, port):''',
         '''# A .env.example value that is not really a value. These are prompts to a
# human, not defaults, and a product shipping one has not configured itself.
_PLACEHOLDER_RE = re.compile(
    r"^(changeme|change_me|change-me|todo|tbd|none|null|xxx+|"
    r"your[-_ ].*|my[-_ ](key|token|secret).*|<.*>|\\.\\.\\.|"
    r"replace[-_ ].*|fill[-_ ].*|example|placeholder)$", re.I)


def _is_placeholder(value: str) -> bool:
    return not value or bool(_PLACEHOLDER_RE.match(value.strip()))


def _strip_value(raw: str) -> str:
    """The value side of a .env line: quotes off, trailing comment off.

    Only a comment with whitespace before it — `KEY=a#b` is a value containing
    a hash, not a commented one, and guessing otherwise silently corrupts it.
    """
    v = raw.strip()
    for i in range(1, len(v)):
        if v[i] == "#" and v[i - 1] in " \\t":
            v = v[:i]
            break
    return v.strip().strip('"').strip("'")


def resolve_product_env(product_dir: Path, port):''')

# ── the product's own file joins the search ──────────────────────────────────
s = swap("sources", s, '''    shared = _read_env_file(SHARED_ENV)
    resolved, missing = {}, []''',
         '''    shared = _read_env_file(SHARED_ENV)
    # The operator's choice for THIS product outranks the machine's shared
    # file, which outranks the default the product ships with.
    product_own = _read_env_file(product_dir / ".env")
    resolved, missing, sources = {}, [], {}''')

# ── resolution, most specific first, and the shipped default counts ──────────
s = swap("resolve", s, '''        key = line.split("=", 1)[0].strip()
        val = os.environ.get(key) or shared.get(key) or ""''',
         '''        key, _raw_default = line.split("=", 1)
        key = key.strip()
        shipped = _strip_value(_raw_default)

        # The .env.example default used to be discarded — only the key was
        # read — so a documented, working default read as missing
        # configuration and stopped the deploy.
        if product_own.get(key):
            val, src = product_own[key], "product .env"
        elif os.environ.get(key):
            val, src = os.environ[key], "deploy environment"
        elif shared.get(key):
            val, src = shared[key], "shared/.env"
        elif not _is_placeholder(shipped):
            val, src = shipped, ".env.example default"
        else:
            val, src = "", ""''')

s = swap("record", s,
         '''        (resolved.__setitem__(key, val) if val else missing.append(key))
    return resolved, missing''',
         '''        if val:
            resolved[key] = val
            sources[key] = src
        else:
            missing.append(key)

    for k in sorted(resolved):
        print(f"🔧 {k:24} ← {sources.get(k, 'unknown')}", flush=True)
    return resolved, missing''')

# the deployer-only fallbacks need to record a source too
s = swap("fallback source", s, '''            if key.endswith("_PORT") and port:
                val = str(port)
            elif key.endswith("_HOST"):
                val = "127.0.0.1"''',
         '''            if key.endswith("_PORT") and port:
                val, src = str(port), "allocated by the deployer"
            elif key.endswith("_HOST"):
                val, src = "127.0.0.1", "deploy default"''')

# ── and the abort says something true ────────────────────────────────────────
s = swap("message", s, '''                return ("❌ Deploy aborted — the product declares configuration that "
                        f"could not be resolved: {missing_env}. "
                        "Add them to /Users/ducorn/DC/shared/.env and redeploy.")''',
         '''                _names = ", ".join(missing_env)
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
                    "in /Users/ducorn/DC/shared/.env.")''')

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = TOOL.with_name(f"DuCornDeployTool.backup-envdefaults-{stamp}.py")
shutil.copy2(TOOL, backup)
TOOL.write_text(s, encoding="utf-8")


def die(msg):
    shutil.copy2(backup, TOOL)
    sys.exit(f"{msg} — reverted from {backup.name}")


try:
    ast.parse(s)
except SyntaxError as e:
    die(f"SYNTAX ERROR ({e})")


# ── will it import? the check that would have saved the API ──────────────────
def unbound_at_module_level(source):
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


bad = unbound_at_module_level(TOOL.read_text(encoding="utf-8"))
if bad:
    die("the patched file would NameError at import: " +
        ", ".join(f"line {ln} uses {nm!r}" for ln, nm in bad))
print("import check: every module-level statement can reach the names it uses")

# ── exercise the resolution against tonight's actual product ─────────────────
src = TOOL.read_text(encoding="utf-8")
tree = ast.parse(src)


def seg(name):
    return next((ast.get_source_segment(src, n) for n in tree.body
                 if isinstance(n, ast.FunctionDef) and n.name == name), None)


import re as _re
import tempfile
ns = {"re": _re}
for fn in ("_is_placeholder", "_strip_value"):
    if seg(fn) is None:
        die(f"{fn} did not land")
    exec(seg(fn), ns)
ns["_PLACEHOLDER_RE"] = _re.compile(
    r"^(changeme|change_me|change-me|todo|tbd|none|null|xxx+|"
    r"your[-_ ].*|my[-_ ](key|token|secret).*|<.*>|\.\.\.|"
    r"replace[-_ ].*|fill[-_ ].*|example|placeholder)$", _re.I)

print("\nwhat counts as a shipped default:")
for value, is_ph, why in [
    ("http://localhost:8766,http://127.0.0.1:8766", False, "tonight's actual value"),
    ("postgresql://ducorn@localhost/litellm_db", False, "a real DSN"),
    ("", True, "empty"),
    ("changeme", True, "the classic"),
    ("your-api-key-here", True, "a prompt to a human"),
    ("<fill me in>", True, "angle brackets"),
    ("xxxxx", True, "placeholder"),
    ("8766", False, "a bare port is a real value"),
]:
    got = ns["_is_placeholder"](value)
    ok = got == is_ph
    print(f"  {'ok  ' if ok else 'FAIL'} {value[:42]:44} "
          f"{'placeholder' if got else 'real default':13} {why}")
    if not ok:
        die(f"{value!r}: expected placeholder={is_ph}")

print("\nvalue parsing:")
for raw, want in [('  http://a,http://b ', 'http://a,http://b'),
                  ('"quoted"', 'quoted'),
                  ('value  # trailing note', 'value'),
                  ('a#b', 'a#b')]:
    got = ns["_strip_value"](raw)
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {raw!r:28} → {got!r}")
    if not ok:
        die(f"{raw!r}: expected {want!r}, got {got!r}")

# and the whole function, against the real .env.example
fn_src = seg("resolve_product_env")
if fn_src is None:
    die("resolve_product_env did not land")
ns2 = dict(ns)
ns2.update({"Path": Path, "os": __import__("os"),
            "_read_env_file": lambda p: ({"DATABASE_URL": "postgresql://ducorn@localhost/litellm_db"}
                                         if str(p).endswith("shared/.env") else {}),
            "SHARED_ENV": Path("/Users/ducorn/DC/shared/.env")})
exec(fn_src, ns2)
tmp = Path(tempfile.mkdtemp())
(tmp / ".env.example").write_text(
    "# comment\nDATABASE_URL=postgresql://ducorn@localhost/litellm_db\n"
    "ALLOWED_ORIGINS=http://localhost:8766,http://127.0.0.1:8766\n"
    "SECRET_TOKEN=changeme\n", encoding="utf-8")
resolved, missing = ns2["resolve_product_env"](tmp, 8766)

print("\nagainst a .env.example shaped like tonight's:")
print(f"  resolved: {sorted(resolved)}")
print(f"  missing:  {missing}")
if "ALLOWED_ORIGINS" not in resolved:
    die("ALLOWED_ORIGINS still unresolved — the shipped default is ignored")
if resolved["ALLOWED_ORIGINS"] != "http://localhost:8766,http://127.0.0.1:8766":
    die(f"wrong value: {resolved['ALLOWED_ORIGINS']!r}")
if missing != ["SECRET_TOKEN"]:
    die(f"a placeholder must still count as missing; got {missing}")
print("  ok   the shipped default deploys; a placeholder still blocks")

print("\napplied: " + ", ".join(applied))
print(f"backup:  {backup.name}")
print()
print("Nothing to restart — the tool is imported per pipeline subprocess.")
print("Re-approve the deploy in Slack, or re-run the phase:")
print("  cd ~/DC/ducorn && .venv/bin/python flows/langgraph_flow.py "
      "ducorn-spend-status --phase deploy --engine gstack --coder crewai "
      "--complexity simple")
print()
print("Expect:  🔧 ALLOWED_ORIGINS         ← .env.example default")
print("         🔧 DATABASE_URL            ← shared/.env")
