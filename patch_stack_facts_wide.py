#!/usr/bin/env python3
"""
Collect what the stack actually runs on, not just what one glob happens to see.

    python3 scripts/patch_stack_facts_wide.py
    python3 scripts/stack_facts.py            # regenerate the context

── THE GAP ──────────────────────────────────────────────────────────────────

You said the document was not thorough — no Playwright, no CLI tooling. That
one is not a delivery problem. The word "playwright" appears ZERO times in
ducorn-stack-context.md, so the document could not have mentioned it.

dependencies() reads exactly two things:

    DC.glob("ducorn-products/products/*/requirements.txt")
    ducorn/pyproject.toml

Which means it never sees:

    products/_shared/requirements-ui.txt   the ONLY file naming playwright
    gstack/package.json                    never read — package.json is not
    products/*/package.json                in the glob at all
    ducorn/.venv                           175 installed packages, including
                                           langgraph 1.2.11 and playwright
                                           1.62.0 — and langgraph is named in
                                           NO manifest anywhere in the repo

The pipeline runs on LangGraph. Nothing in the repo declares LangGraph. A
document written from manifests alone would omit the framework the whole
system is built on, and be right to.

── WHAT REPLACES IT ─────────────────────────────────────────────────────────

Three sources, in order of authority:

  declared     every requirements*.txt and package.json under ~/DC, with the
               file that declares each — so "who needs this" is answerable

  installed    read from ducorn/.venv/lib/*/site-packages/*.dist-info —
               directory names, no subprocess, no pip, no interpreter to pick.
               This is what is actually there.

  vendored     third-party assets committed into the tree (mermaid.min.js and
               friends) that no manifest will ever list

The installed set is 175 packages and most are transitive. Listing all of them
would bury the signal, so the table carries the LOAD-BEARING ones: those a
manifest declares, or that DuCorn's own source imports by name. The rest are
counted, not named. Both halves are computed from the tree — neither is a list
anyone maintains.
"""
import ast
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DC = Path(os.environ.get("DUCORN_ROOT", "/Users/ducorn/DC"))
FACTS = DC / "scripts" / "stack_facts.py"

s = FACTS.read_text(encoding="utf-8")

if "def installed_packages" in s:
    print("Already patched — the collector reads the venv, not one glob.")
    sys.exit(0)

applied = []


def swap(label, text, old, new):
    n = text.count(old)
    if n != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {n}, expected 1. NOTHING WRITTEN.")
    applied.append(label)
    return text.replace(old, new, 1)


NEW_DEPS = '''# ── dependencies ─────────────────────────────────────────────────────────────
# Three sources. The old version read one glob —
# products/*/requirements.txt — plus pyproject.toml, which between them do not
# name playwright (it is in _shared/requirements-ui.txt) or langgraph (it is in
# no manifest at all). The stack runs on LangGraph and nothing in the repo says
# so; a document written from manifests alone would omit the framework the
# whole system is built on.

_SKIP_DIRS = {".venv", "node_modules", "__pycache__", ".git", "site-packages"}


def _walk(pattern):
    """
    Every readable match under DC, outside vendored and build directories.

    is_file() rather than bare rglob: the tree contains at least one dangling
    symlink (ducorn-products/scripts/langgraph_flow.py points at nothing), and
    rglob happily yields it. Without this the first read_text raised
    FileNotFoundError and took the entire collector down — one broken link and
    the stack has no dependency table at all.
    """
    for p in sorted(DC.rglob(pattern)):
        if _SKIP_DIRS & set(p.parts):
            continue
        try:
            if p.is_file():
                yield p
        except OSError:
            continue


def declared():
    """package -> {which files declare it}. Answers 'who needs this'."""
    seen = {}
    for req in _walk("requirements*.txt"):
        where = str(req.relative_to(DC))
        try:
            lines = req.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for ln in lines:
            ln = ln.split("#")[0].strip()
            if not ln or ln.startswith("-"):
                continue
            name = re.split(r"[=<>\\[!~]", ln, maxsplit=1)[0].strip()
            if name:
                seen.setdefault(name.lower(), {"pin": set(), "where": set()})
                seen[name.lower()]["pin"].add(ln)
                seen[name.lower()]["where"].add(where)

    for pj in _walk("package.json"):
        where = str(pj.relative_to(DC))
        try:
            data = json.loads(pj.read_text(errors="replace"))
        except (ValueError, OSError):
            continue
        for key in ("dependencies", "devDependencies"):
            for name, pin in (data.get(key) or {}).items():
                seen.setdefault(name.lower(), {"pin": set(), "where": set()})
                seen[name.lower()]["pin"].add(f"{name}{pin}")
                seen[name.lower()]["where"].add(where)

    pyproject = DC / "ducorn/pyproject.toml"
    if pyproject.is_file():
        for m in re.finditer(r\'"([A-Za-z0-9_.\\-]+)[><=~]{1,2}([^"]+)"\',
                             pyproject.read_text(errors="replace")):
            k = m.group(1).lower()
            seen.setdefault(k, {"pin": set(), "where": set()})
            seen[k]["pin"].add(m.group(1) + m.group(2))
            seen[k]["where"].add("ducorn/pyproject.toml")
    return seen


def installed_packages():
    """
    What is actually installed in the pipeline venv.

    Read from *.dist-info directory names — no pip, no subprocess, no choosing
    an interpreter. The names on disk are the source of truth and this script
    must run under any python.
    """
    out = {}
    for site in DC.glob("ducorn/.venv/lib/python*/site-packages"):
        for d in sorted(site.glob("*.dist-info")):
            stem = d.name[:-len(".dist-info")]
            if "-" not in stem:
                continue
            name, _, version = stem.rpartition("-")
            out[name.replace("_", "-").lower()] = version
    return out


def import_to_dist():
    """
    What you type in an import -> what pip calls it.

    psycopg2 is imported by half this codebase and installed as
    psycopg2-binary, so matching import names against distribution names drops
    it — the same shape as langgraph being invisible, one layer down.
    dist-info/top_level.txt is the mapping, written by the installer.
    """
    out = {}
    for site in DC.glob("ducorn/.venv/lib/python*/site-packages"):
        for d in sorted(site.glob("*.dist-info")):
            stem = d.name[:-len(".dist-info")]
            if "-" not in stem:
                continue
            dist = stem.rpartition("-")[0].replace("_", "-").lower()
            top = d / "top_level.txt"
            try:
                mods = top.read_text(errors="replace").split()
            except OSError:
                mods = [dist.replace("-", "_")]
            for m in mods:
                out[m.strip().lower()] = dist
    return out


def imported_by_ducorn():
    """Top-level modules DuCorn's OWN source imports, by name."""
    names = set()
    for py in _walk("*.py"):
        try:
            tree = ast.parse(py.read_text(errors="replace"))
        except (SyntaxError, ValueError, OSError):
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                names |= {a.name.split(".")[0].lower() for a in n.names}
            elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
                names.add(n.module.split(".")[0].lower())
    return names


def dependencies():
    """
    Load-bearing packages: declared by a manifest, or imported by our code.

    The venv holds 175 packages and most are transitive. Naming all of them
    buries the signal; naming none of them lost LangGraph. "Something declares
    it, or we import it" is computed from the tree, so it cannot go stale.
    """
    dec = declared()
    inst = installed_packages()
    imp2dist = import_to_dist()
    # Resolve each import name to its distribution before intersecting, or a
    # package installed under a different name than you import it by is simply
    # invisible — psycopg2/psycopg2-binary, sklearn/scikit-learn, yaml/PyYAML.
    ours = {imp2dist.get(n, n) for n in imported_by_ducorn()}

    rows = []
    for name in sorted(set(dec) | (set(inst) & ours)):
        version = inst.get(name, "")
        d = dec.get(name)
        pin = ", ".join(sorted(d["pin"]))[:38] if d else ""
        where = ", ".join(sorted(d["where"]))[:44] if d else "installed only"
        rows.append([name, version or "—", pin or "—", where])
    return rows


def dependency_note():
    """One line saying how many were left out, so the omission is visible."""
    inst = installed_packages()
    shown = {r[0] for r in dependencies()}
    hidden = len(set(inst) - shown)
    return (f"{len(shown)} load-bearing packages: declared by a manifest, or "
            f"imported by DuCorn's own source. A further {hidden} are "
            f"installed in `ducorn/.venv` as transitive dependencies and are "
            f"not listed.")


def vendored():
    """Third-party assets committed into the tree. No manifest lists these."""
    rows = []
    for pattern in ("*.min.js", "*.min.css"):
        for p in _walk(pattern):
            try:
                kb = p.stat().st_size // 1024
            except OSError:
                continue
            rows.append([p.name, f"{kb:,} KB", str(p.parent.relative_to(DC))])
    return sorted(rows)
'''

# ── swap the function block ──────────────────────────────────────────────────
OLD_DEPS_START = "# ── dependencies ─────────────────────────────────────────────────────────────\ndef dependencies():"
i = s.find(OLD_DEPS_START)
if i < 0:
    sys.exit("ANCHOR MISS [dependencies block]: header not found. NOTHING WRITTEN.")
j = s.find("\n# ═══", i)
if j < 0:
    sys.exit("ANCHOR MISS [dependencies block]: end not found. NOTHING WRITTEN.")
s = s[:i] + NEW_DEPS + s[j:]
applied.append("dependencies reads three sources")

# ── json must be importable at module level ──────────────────────────────────
if "\nimport json" not in s:
    s = swap("import json", s, "\nimport re\n", "\nimport json\nimport re\n")

# ── the section itself ───────────────────────────────────────────────────────
s = swap("dependency section", s,
         '''h("Dependencies")
line("Pinned across product requirements and the pipeline's own project file.")
line()
table(["package", "pin"], dependencies())''',
         '''h("Dependencies")
line(dependency_note())
line()
table(["package", "installed", "pin", "declared in"], dependencies())

_vendored = vendored()
if _vendored:
    h("Vendored assets")
    line("Third-party files committed into the tree. No manifest lists these, "
         "so nothing else in this document would know they exist.")
    line()
    table(["file", "size", "location"], _vendored)''')

# ── write, verify, revert on failure ─────────────────────────────────────────
stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = FACTS.with_name(f"stack_facts.backup-wide-{stamp}.py")
shutil.copy2(FACTS, backup)
FACTS.write_text(s, encoding="utf-8")


def die(msg):
    shutil.copy2(backup, FACTS)
    sys.exit(f"{msg} — reverted from {backup.name}")


try:
    ast.parse(s)
except SyntaxError as e:
    die(f"SYNTAX ERROR ({e})")

r = subprocess.run([sys.executable, "-m", "pyflakes", str(FACTS)],
                   capture_output=True, text=True)
u = [l for l in (r.stdout + r.stderr).splitlines() if "undefined name" in l]
if u:
    die("undefined name: " + "; ".join(u))
print("syntax and undefined-name checks: clean")

# ── exercise the new collectors against the real tree ────────────────────────
src = FACTS.read_text(encoding="utf-8")
tree = ast.parse(src)
ns = {"DC": DC, "Path": Path, "ast": ast, "json": __import__("json"),
      "re": __import__("re")}
for fname in ("_walk", "declared", "installed_packages", "import_to_dist",
              "imported_by_ducorn", "dependencies", "dependency_note",
              "vendored"):
    seg = next((ast.get_source_segment(src, n) for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == fname), None)
    if seg is None:
        die(f"{fname} did not land")
    exec(seg, ns)
ns["_SKIP_DIRS"] = {".venv", "node_modules", "__pycache__", ".git",
                    "site-packages"}

inst = ns["installed_packages"]()
dec = ns["declared"]()
rows = ns["dependencies"]()
vend = ns["vendored"]()

print(f"\n  {'installed in ducorn/.venv':32} {len(inst):>4}")
print(f"  {'declared by a manifest':32} {len(dec):>4}")
print(f"  {'load-bearing (the table)':32} {len(rows):>4}")
print(f"  {'vendored assets':32} {len(vend):>4}")

by_name = {r[0]: r for r in rows}
print("\nthe ones the old collector could not see:\n")
FOUND = []
for pkg in ("playwright", "langgraph", "crewai", "psycopg2-binary"):
    r = by_name.get(pkg)
    FOUND.append((pkg, r))
    print(f"  {pkg:16} " + (f"{r[1]:<12} declared in: {r[3]}" if r
                            else "STILL MISSING"))

for pkg, r in FOUND:
    if pkg in ("playwright", "langgraph", "psycopg2-binary") and not r:
        die(f"{pkg} is still not collected")

if not vend:
    print("\n  (no vendored .min.js/.css found — nothing to report)")
else:
    print("\nvendored:")
    for v in vend[:4]:
        print(f"  {v[0]:24} {v[1]:>10}  {v[2]}")

print("\napplied: " + ", ".join(applied))
print(f"backup:  {backup.name}")
print("""
Regenerate the context, then check what the document will now be given:

  python3 scripts/stack_facts.py
  grep -ci playwright ducorn-products/docs/ducorn-stack-context.md
  python3 scripts/stack_context.py ducorn-technology-stack-documentation
""")
