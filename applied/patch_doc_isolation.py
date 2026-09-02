#!/usr/bin/env python3
"""
A document belongs to exactly one product, and the API must say so.

── THE HOLE ─────────────────────────────────────────────────────────────────

    @app.get("/products/{slug}/doc")
    def get_product_doc(slug: str, filename: str):
        docs_dir = "/Users/ducorn/DC/ducorn-products/docs"
        doc_path = f"{docs_dir}/{filename}"
        if not os.path.exists(doc_path):
            return JSONResponse({"error": "Document not found"}, status_code=404)
        content = open(doc_path).read()

The slug is accepted, named in the route, and then never used. The filename is
joined straight on. So:

    /products/anything/doc?filename=ducorn-run-history-PRD.md
        → reads another product's PRD under any slug you like

    /products/anything/doc?filename=../../shared/.env
        → reads every API key on the machine

Both are behind the x-api-key middleware, so this is a defect rather than an
open door. It is still the rule you called a showstopper — "I do not want
product 1 to read product 2's file EVER" — implemented as a parameter that is
decorative.

── THE QUIETER ONE NEXT DOOR ────────────────────────────────────────────────

get_product() lists a product's documents like this:

    glob.glob(f"{docs_dir}/{slug}*.md")

Prefix matching with no boundary. `ducorn-pipeline-dashboard-v1` would match
`ducorn-pipeline-dashboard-v10-PRD.md`, and v6, v8 and v10 already exist — the
next version number you reuse turns this on. I checked all 18 products on the
machine: no slug is currently a prefix of another, so nothing is leaking
today. This is prevention, and it is cheap because the same helper fixes both.

── THE RULE ─────────────────────────────────────────────────────────────────

A document belongs to the LONGEST known slug that prefixes its name at a
separator boundary. `ducorn-pipeline-dashboard-v10-PRD.md` belongs to v10, not
to v1, because v10 is longer and both are real products. Ownership is computed
once and used by both the listing and the fetch, so what a product lists is
exactly what it can open — a listing that shows a file you then cannot fetch
is its own kind of bug.

Three gates on the fetch, in order:

  1. the slug is a real product (known_slug, already in this file)
  2. the filename is a bare name — no separators, no leading dot
  3. the document's owner is this slug

The path is built only after all three pass, and only from validated pieces.

Documents belonging to no product — ATLAS-PRD-001-Board-Summary.md and the
like — are owned by nobody and so are reachable through no product. That is
correct for a per-product endpoint; they were never in any product's listing
either.
"""
import ast
import shutil
import sys
from datetime import datetime
from pathlib import Path

API = Path("/Users/ducorn/DC/ducorn-products/products/ducorn-activity-api/main.py")
s = API.read_text(encoding="utf-8")

if "def doc_owner" in s:
    sys.exit("Already patched — documents are owned.")
if "def known_slug" not in s:
    sys.exit("Apply patch_atlas_failure.py first — this builds on known_slug(). "
             "NOTHING WRITTEN.")

applied = []


def swap(label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {text.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    applied.append(label)
    return text.replace(old, new, 1)


# ── the import this file needs at module level ───────────────────────────────
#
# main.py imports re four times, every one of them inside a function. The
# previous patch put a module-level re.compile() here and took the API down
# with a NameError at import — the same mistake I made in skill_runner.py
# yesterday, having written an audit for exactly this and not run it on this
# file. _DOC_NAME_RE below is another module-level compile, so the import is
# part of the patch rather than a thing to remember.
if "\nimport re\n" not in s.split("app = FastAPI", 1)[0]:
    s = swap("import re", s, "import glob\nfrom datetime import date",
             "import glob\nimport re\nfrom datetime import date")


# ── ownership, computed once and used by both sides ──────────────────────────
s = swap("ownership", s, '''def failure_context(slug: str) -> str:''',
         '''# A document filename as the pipeline writes them. A bare name: no directory
# separators, no leading dot, so it cannot climb out of the docs directory or
# name a hidden file.
_DOC_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

DOCS_DIR = "/Users/ducorn/DC/ducorn-products/docs"
PRODUCTS_ROOT = "/Users/ducorn/DC/ducorn-products/products"


def known_slugs() -> list:
    """
    Every product on the machine, longest first.

    Longest first is the whole point: `ducorn-pipeline-dashboard-v10-PRD.md`
    is prefixed by both v1 and v10, and only one of them owns it.
    """
    out = set()
    try:
        for p in os.listdir(PRODUCTS_ROOT):
            if not p.startswith("_") and os.path.isdir(
                    os.path.join(PRODUCTS_ROOT, p)):
                out.add(p)
    except OSError as e:
        print(f"[docs] could not list products ({e})")
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT slug FROM pipeline_runs "
                        "WHERE slug IS NOT NULL")
            out.update(r["slug"] for r in cur.fetchall() if r["slug"])
    except Exception as e:
        print(f"[docs] could not read slugs from pipeline_runs ({e})")
    finally:
        if conn:
            conn.close()
    return sorted(out, key=len, reverse=True)


def doc_owner(filename: str) -> str:
    """
    Which product owns this document, or "" for none.

    The longest known slug that prefixes the name at a separator boundary. The
    boundary is what stops `ducorn-run-history` from claiming
    `ducorn-run-history-v2-PRD.md` — that file's owner is the v2 product if it
    exists, and nobody's if it does not.
    """
    if not filename or not _DOC_NAME_RE.match(filename):
        return ""
    for slug in known_slugs():          # longest first
        if filename.startswith(slug) and filename[len(slug):len(slug) + 1] in ("-", "."):
            return slug
    return ""


def docs_for(slug: str) -> list:
    """
    This product's documents, and only this product's.

    Used by the listing and by the fetch, so the two can never disagree about
    what belongs to whom.
    """
    try:
        names = os.listdir(DOCS_DIR)
    except OSError:
        return []
    return sorted(n for n in names
                  if n.lower().endswith((".md", ".pdf"))
                  and doc_owner(n) == slug)


def failure_context(slug: str) -> str:''')

# ── the fetch enforces it ────────────────────────────────────────────────────
s = swap("fetch", s, '''def get_product_doc(slug: str, filename: str):
    """Get content of a product document"""
    docs_dir = "/Users/ducorn/DC/ducorn-products/docs"
    doc_path = f"{docs_dir}/{filename}"
    if not os.path.exists(doc_path):
        return JSONResponse({"error": "Document not found"}, status_code=404)
    content = open(doc_path).read()
    return {"filename": filename, "content": content}''',
         '''def get_product_doc(slug: str, filename: str):
    """
    Get content of a product document — this product's document.

    The slug used to be decorative: it was named in the route and never read,
    so any filename could be fetched under any product, including one with
    ../.. in it. Three gates now, and the path is built only from what has
    passed all three.
    """
    if not known_slug(slug):
        return JSONResponse({"error": "Unknown product"}, status_code=404)
    if not _DOC_NAME_RE.match(filename or ""):
        return JSONResponse({"error": "Invalid document name"}, status_code=400)

    owner = doc_owner(filename)
    if owner != slug:
        # Deliberately the same answer whether the file is another product's or
        # absent: a 403 here would confirm which documents exist.
        print(f"[docs] refused {filename!r} under {slug!r}"
              + (f" — it belongs to {owner!r}" if owner else " — unowned"))
        return JSONResponse({"error": "Document not found"}, status_code=404)

    doc_path = os.path.join(DOCS_DIR, filename)
    if not os.path.exists(doc_path):
        return JSONResponse({"error": "Document not found"}, status_code=404)
    with open(doc_path, errors="replace") as fh:
        content = fh.read()
    return {"filename": filename, "content": content}''')

# ── and the listing agrees with it ───────────────────────────────────────────
s = swap("listing", s, '    for f in sorted(glob.glob(f"{docs_dir}/{slug}*.md") + \n'
         '                   glob.glob(f"{docs_dir}/{slug}*.pdf")):',
         '''    # docs_for() rather than a {slug}* glob: prefix matching with no boundary
    # would let ducorn-...-v1 list ducorn-...-v10's documents, and the fetch
    # would then refuse what the listing had just shown.
    for f in [os.path.join(docs_dir, n) for n in docs_for(slug)]:''')

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = API.with_name(f"main.backup-docjail-{stamp}.py")
shutil.copy2(API, backup)
API.write_text(s, encoding="utf-8")


def die(msg):
    shutil.copy2(backup, API)
    sys.exit(f"{msg} — reverted from {backup.name}")


try:
    ast.parse(s)
except SyntaxError as e:
    die(f"SYNTAX ERROR ({e})")


# ── will it import? ast.parse cannot tell you, and that is what broke ────────
#
# A module-level statement using a name that is only imported inside a function
# is valid syntax and a NameError at import time. It takes the whole service
# down before a single request. I wrote this audit for skill_runner.py
# yesterday, did not run it against main.py, and put the API into a restart
# loop with exactly that. So it runs here, on the file this patch just wrote,
# every time.
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
    function_only = local_names - module_names

    hits = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Import, ast.ImportFrom)):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and sub.id in function_only:
                hits.append((getattr(node, "lineno", "?"), sub.id))
                break
    return hits


bad = unbound_at_module_level(API.read_text(encoding="utf-8"))
if bad:
    die("the patched file would NameError at import: " +
        ", ".join(f"line {ln} uses {nm!r}" for ln, nm in bad))
print("\nimport check: every module-level statement can reach the names it uses")

# ── exercise ownership against the collision that is coming ──────────────────
src = API.read_text(encoding="utf-8")
tree = ast.parse(src)
seg = next((ast.get_source_segment(src, n) for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == "doc_owner"), None)
if seg is None:
    die("doc_owner did not land")

import re as _re
FAKE = ["ducorn-pipeline-dashboard-v1", "ducorn-pipeline-dashboard-v10",
        "ducorn-run-history", "ducorn-run-history-v2", "ducorn-spend-status"]
ns = {"_DOC_NAME_RE": _re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"),
      "known_slugs": lambda: sorted(FAKE, key=len, reverse=True)}
exec(seg, ns)
owner = ns["doc_owner"]

print("\nchecking who owns what (v1/v10 both real, which is the trap):")
for name, want, why in [
    ("ducorn-pipeline-dashboard-v10-PRD.md", "ducorn-pipeline-dashboard-v10",
     "the longer slug wins"),
    ("ducorn-pipeline-dashboard-v1-PRD.md", "ducorn-pipeline-dashboard-v1",
     "and the shorter one still gets its own"),
    ("ducorn-run-history-v2-PRD.md", "ducorn-run-history-v2",
     "not the shorter run-history"),
    ("ducorn-run-history-PRD.md", "ducorn-run-history", "plain case"),
    ("ducorn-spend-status.md", "ducorn-spend-status", "dot boundary"),
    ("ducorn-spend-statusXX.md", "", "no boundary — not this product's"),
    ("ATLAS-PRD-001-Board-Summary.md", "", "belongs to no product"),
    ("../../shared/.env", "", "traversal"),
    ("..%2F..%2Fshared%2F.env", "", "encoded traversal"),
    (".env", "", "leading dot"),
    ("", "", "empty"),
]:
    got = owner(name)
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {name[:38]:40} → "
          f"{got or '(nobody)':30} {why}")
    if not ok:
        die(f"{name!r}: expected {want!r}, got {got!r}")

for must in ("if not known_slug(slug):", "owner != slug",
             "os.path.join(DOCS_DIR, filename)", "docs_for(slug)"):
    if must not in src:
        die(f"{must!r} missing from the patched file")
if 'doc_path = f"{docs_dir}/{filename}"' in src:
    die("the unvalidated join is still there")

print("\napplied: " + ", ".join(applied))
print(f"backup:  {backup.name}")
print()
print("Restart the API, then confirm the hole is shut:")
print("  launchctl kickstart -k gui/$(id -u)/com.ducorn.api")
print()
print('  K=$DUCORN_API_TOKEN')
print('  curl -s -H "x-api-key: $K" '
      '"http://localhost:8000/products/ducorn-spend-status/doc?filename=../../shared/.env"')
print('      expect: {"error":"Invalid document name"}')
print('  curl -s -H "x-api-key: $K" '
      '"http://localhost:8000/products/ducorn-spend-status/doc?filename=ducorn-run-history-launch.md"')
print('      expect: {"error":"Document not found"}   (another product owns it)')
