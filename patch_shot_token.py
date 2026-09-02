#!/usr/bin/env python3
"""
Two things the first paid run found. One is mine.

── 1. THE SCREENSHOTS DID NOT RUN ───────────────────────────────────────────

    ✅ DESIGN: 3/3 variants rendered
    ⚠️  screenshots unavailable: KeyError: 'token'

node_design builds the URL to screenshot like this:

    jobs.append((f"{_api}/d/{r['token']}", out))

and _register_variants returns rows with these keys:

    {"id", "name", "archetype", "register", "path", "url", "problems"}

No 'token'. I took the key list from a comment in the patch that created that
function — "Returns [{name, archetype, path, token, url}]" — instead of from
the function. The comment was wrong. That is the same mistake as
check_ui_tests and --apply: a name read from something NEAR the code rather
than from the code, for the third and fourth time today.

Two changes, so it cannot recur in this shape:

  · _register_variants returns the token, which belongs in the row anyway
  · node_design derives it from the url if the key is absent, and builds the
    job list per variant so one bad row costs one screenshot rather than all
    three

What did work, exactly as designed: the failure was non-fatal, all three
variants rendered, gate 2 posted with its links, the run continued, and the log
named the cause in one line. Nothing was lost but the pictures.

── 2. A WARNING THAT IS NOT A DEFECT ────────────────────────────────────────

    · Data-Dense Professional: 14 test ids
      ⚠️ ["data-testid not kebab-case: ['agent-card-${slug}', 'bar-${dateAttr}']"]

Those come from here:

    html += `
    <div class="agent-card" data-testid="agent-card-${slug}">

It is a JavaScript template literal. `${slug}` interpolates at runtime and the
rendered attribute is perfectly good kebab-case. validate_html scans the source
as text, cannot tell markup from a template string, and flags it.

So REX is warned about three correct designs, on every UI product, forever. A
warning that is always wrong is worse than no warning: it teaches you to skim
past the ones that are right.

A testid containing ${...} is now recognised as dynamic. Its literal segments
are still checked — data-testid="Agent_Card-${slug}" is still wrong and still
reported — but the placeholder is not held against it.
"""
import ast
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

DUCORN = Path("/Users/ducorn/DC/ducorn")
FLOW = DUCORN / "flows/langgraph_flow.py"
GEN = DUCORN / "tools/generate_design.py"

edits, applied = [], []


def swap(path, label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{path.name}:{label}]: found {text.count(old)}, "
                 f"expected 1. NOTHING WRITTEN.")
    applied.append(f"{path.name}:{label}")
    return text.replace(old, new, 1)


# ═══════════════════════════════════════════════════════════════════════════
f = FLOW.read_text(encoding="utf-8")
if '"token": token' in f:
    sys.exit("Already patched — the variant row carries its token.")

f = swap(FLOW, "row token", f, '''                "url": f"{DESIGN_LINK_BASE}/d/{token}",
                "problems": v.get("problems") or [],''',
         '''                "url": f"{DESIGN_LINK_BASE}/d/{token}",
                # The capability token itself, not only the public URL. Gate 2
                # screenshots each variant through the API on localhost, which
                # needs the token and not the tunnel — and reconstructing it by
                # string-splitting the url is how a rename becomes a silent
                # failure.
                "token": token,
                "problems": v.get("problems") or [],''')

f = swap(FLOW, "job build", f, '''            _api = os.environ.get("DUCORN_LOCAL_API", "http://localhost:8000")
            jobs, out_for = [], {}
            for r in registered:
                out = str(Path(r["path"]).with_suffix(".png"))
                jobs.append((f"{_api}/d/{r['token']}", out))
                out_for[out] = r["path"]''',
         '''            _api = os.environ.get("DUCORN_LOCAL_API", "http://localhost:8000")
            jobs, out_for = [], {}
            for r in registered:
                # Per variant, so a malformed row costs one picture rather than
                # all three. The first version read r["token"] for every row up
                # front; the key did not exist, and one KeyError took out the
                # whole set.
                try:
                    tok = r.get("token") or r["url"].rsplit("/d/", 1)[-1]
                    if not tok or "/" in tok:
                        raise ValueError(f"no usable view token in {r!r}")
                    out = str(Path(r["path"]).with_suffix(".png"))
                    jobs.append((f"{_api}/d/{tok}", out))
                    out_for[out] = r["path"]
                except Exception as e:
                    print(f"   ⚠️  no screenshot for "
                          f"{r.get('name', '?')}: {type(e).__name__}: {e}")''')
edits.append((FLOW, f))

# ═══════════════════════════════════════════════════════════════════════════
g = GEN.read_text(encoding="utf-8")
if "_TESTID_OK" in g:
    sys.exit("Already patched — dynamic test ids are recognised.")

g = swap(GEN, "kebab check", g, '''    bad = [i for i in ids if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", i)]
    if bad:
        problems.append(f"data-testid not kebab-case: {bad[:5]}")''',
         '''    # A testid built in a template literal — data-testid="agent-card-${slug}"
    # — interpolates at runtime and is correct kebab-case on the page. This
    # scans source text, cannot tell markup from a template string, and used to
    # flag all three variants of every UI product. A warning that is always
    # wrong teaches you to skim past the ones that are right.
    #
    # The literal parts are still checked: "Agent_Card-${slug}" is still bad.
    bad = [i for i in ids if not _TESTID_OK(i)]
    if bad:
        problems.append(f"data-testid not kebab-case: {bad[:5]}")''')

g = swap(GEN, "helper", g, '''def validate_html(html, min_testids=6):''',
         '''_KEBAB = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
_PLACEHOLDER = re.compile(r"\\$\\{[^}]*\\}")


def _TESTID_OK(testid: str) -> bool:
    """
    Is this data-testid well formed?

    Kebab-case, with one allowance: a ${...} placeholder is a runtime value, so
    it is replaced by a neutral token before checking and the rest of the id is
    judged normally. An id that is nothing but a placeholder passes — there is
    nothing static left to have an opinion about.
    """
    stripped = _PLACEHOLDER.sub("x", testid)
    stripped = stripped.strip("-")
    return bool(stripped) and bool(_KEBAB.fullmatch(stripped))


def validate_html(html, min_testids=6):''')
edits.append((GEN, g))

# ═══════════════════════════════════════════════════════════════════════════
stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backups = []
for path, text in edits:
    backup = path.with_name(f"{path.stem}.backup-shottoken-{stamp}{path.suffix}")
    shutil.copy2(path, backup)
    backups.append((path, backup))
    path.write_text(text, encoding="utf-8")

for path, backup in backups:
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        for p, b in backups:
            shutil.copy2(b, p)
        sys.exit(f"SYNTAX ERROR in {path.name} ({e}) — all files reverted")

# ── exercise both, rather than trusting either ───────────────────────────────
src = GEN.read_text(encoding="utf-8")
seg = next((ast.get_source_segment(src, n) for n in ast.parse(src).body
            if isinstance(n, ast.FunctionDef) and n.name == "_TESTID_OK"), None)
ns = {"re": re,
      "_KEBAB": re.compile(r"[a-z0-9]+(-[a-z0-9]+)*"),
      "_PLACEHOLDER": re.compile(r"\$\{[^}]*\}")}
exec(seg, ns)
ok = ns["_TESTID_OK"]

CASES = [
    ("spend-total", True, "plain kebab"),
    ("agent-card-${slug}", True, "the case from tonight's run"),
    ("bar-${dateAttr}", True, "camelCase inside the placeholder is not ours"),
    ("${cardId}", True, "nothing but a placeholder"),
    ("call-row-${idx}", True, "trailing placeholder"),
    ("Agent_Card-${slug}", False, "bad literal part is still bad"),
    ("SpendTotal", False, "camelCase"),
    ("spend_total", False, "snake_case"),
    ("spend--total", False, "double hyphen"),
]
print("\nchecking test-id validation:")
for testid, expect, label in CASES:
    got = ok(testid)
    good = got == expect
    print(f"  {'ok  ' if good else 'FAIL'} {testid:24} {'accepted' if got else 'rejected':9} {label}")
    if not good:
        for p, b in backups:
            shutil.copy2(b, p)
        sys.exit(f"expected {expect}, got {got} — all files reverted")

# The token must now be in the row the screenshots read from.
flow_src = FLOW.read_text(encoding="utf-8")
if flow_src.count('"token": token') != 1:
    for p, b in backups:
        shutil.copy2(b, p)
    sys.exit("the token key did not land in _register_variants — reverted")

print("\napplied: " + ", ".join(applied))
print(f"backups: *.backup-shottoken-{stamp}.*")
print()
print("No restart needed — the flow is read fresh when a phase is spawned.")
print("This run's design phase is already past, so its gate 2 keeps the links.")
print("The next design run takes the pictures.")
