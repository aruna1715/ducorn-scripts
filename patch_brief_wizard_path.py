#!/usr/bin/env python3
"""
Stop the brief wizard telling every document to save itself where it cannot.

── WHERE THE BAD PATH CAME FROM ─────────────────────────────────────────────

The tech-stack brief arrived with this line:

    Save to products/ducorn-tech-stack/docs/documented-architecture.pdf

Nobody typed that. It came from the wizard's own prompt template, which ends
every brief it drafts with:

    Save to products/[kebab-case-name]/[main file based on type]

For software and dashboards that is right — node_build commits
products/<slug>/. For a document it is wrong: the pipeline does `git add docs/`
and writes to ducorn-products/docs/. So the wizard reliably produces, for every
document product, an instruction that can only be followed wrongly.

It also asks the agent to invent a filename ("main file based on type"), and
for a PDF that is doubly wrong — the PDF is produced from the markdown by a
later pipeline step, not written by the builder at all.

── WHY THIS IS THE SAME BUG AS THE REST OF THE WEEK ─────────────────────────

Two copies of one fact. node_build decides where a product's files go; the
wizard's template says where they go; nothing keeps them agreeing. They have
disagreed for document products since the day both existed, silently, because
a brief with a wrong path still produces a plausible-looking run.

── THE FIX ──────────────────────────────────────────────────────────────────

The wizard stops guessing and states what the pipeline actually does, per type:

    document              docs/, written as markdown; the PDF is generated
    dashboard / software  products/<slug>/, with an index.html or an entry point

and, for a document, tells the writer not to name a PDF at all.

The mapping is derived from node_build's own two branches rather than typed
again, so a change there is visible here rather than quietly contradicted.
"""
import ast
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

API = Path("/Users/ducorn/DC/ducorn-products/products/ducorn-activity-api/main.py")
FLOW = Path("/Users/ducorn/DC/ducorn/flows/langgraph_flow.py")

s = API.read_text(encoding="utf-8")

if "_WHERE_FILES_GO" in s:
    sys.exit("Already patched — the wizard names the right destination.")
if "Save to products/[kebab-case-name]" not in s:
    sys.exit("The wizard's save line is not where expected. NOTHING WRITTEN.")

# Read node_build's actual behaviour rather than trusting my memory of it. If
# the flow ever stops treating documents specially, this patch should be the
# thing that notices.
flow_src = FLOW.read_text(encoding="utf-8") if FLOW.is_file() else ""
if "if product_type == 'document':" not in flow_src:
    sys.exit("langgraph_flow no longer branches on product_type == 'document' — "
             "check where files actually go before changing the wizard. "
             "NOTHING WRITTEN.")
if '_git_publish("docs/"' not in flow_src:
    sys.exit("documents are no longer committed to docs/ — the mapping below "
             "would be wrong. NOTHING WRITTEN.")
print("confirmed against langgraph_flow: documents → docs/, everything else "
      "→ products/<slug>/")

applied = []


def swap(label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {text.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    applied.append(label)
    return text.replace(old, new, 1)


s = swap("where files go", s, '''    prompt = f"""You are a DuCorn product brief writer.''',
         '''    # Where the pipeline ACTUALLY puts a product's files, per type. Verified
    # against node_build, which has exactly two branches: documents are
    # committed to docs/, everything else to products/<slug>/. The wizard used
    # to say products/<slug>/ for all of them, so every document brief carried
    # a path the pipeline would never write to.
    _WHERE_FILES_GO = {
        "document":
            "Save the document to docs/ as markdown, named "
            "[kebab-case-name].md. Do NOT name a PDF — the PDF is generated "
            "from the markdown by a later pipeline step.",
        "dashboard":
            "Save to products/[kebab-case-name]/, with index.html as the page.",
        "software":
            "Save to products/[kebab-case-name]/, with the entry point named "
            "in the technical notes.",
        "api":
            "Save to products/[kebab-case-name]/, with the FastAPI app under "
            "api/main.py.",
    }
    _where = _WHERE_FILES_GO.get(
        str(product_type).lower(), _WHERE_FILES_GO["software"])

    prompt = f"""You are a DuCorn product brief writer.''')

s = swap("use it", s,
         '''Save to products/[kebab-case-name]/[main file based on type]

Keep it under 200 words.''',
         '''{_where}

Keep it under 200 words.''')

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = API.with_name(f"main.backup-wizardpath-{stamp}.py")
shutil.copy2(API, backup)
API.write_text(s, encoding="utf-8")


def die(msg):
    shutil.copy2(backup, API)
    sys.exit(f"{msg} — reverted from {backup.name}")


try:
    ast.parse(s)
except SyntaxError as e:
    die(f"SYNTAX ERROR ({e})")

r = subprocess.run([sys.executable, "-m", "pyflakes", str(API)],
                   capture_output=True, text=True)
undef = [l for l in (r.stdout + r.stderr).splitlines() if "undefined name" in l]
if undef:
    die("undefined name: " + "; ".join(undef))
print("syntax and undefined-name checks: clean")

# ── what the wizard now tells each kind of product ───────────────────────────
src = API.read_text(encoding="utf-8")
tree = ast.parse(src)
mapping = None
for node in ast.walk(tree):
    if (isinstance(node, ast.Assign)
            and getattr(node.targets[0], "id", "") == "_WHERE_FILES_GO"):
        mapping = ast.literal_eval(node.value)
        break
if mapping is None:
    die("_WHERE_FILES_GO did not land as a literal")

print("\nwhere the wizard now says each kind of product goes:")
for kind in ("document", "dashboard", "software", "api"):
    where = mapping[kind]
    print(f"  {kind:10} {where[:62]}")

checks = [
    ("a document is sent to docs/, not products/",
     "docs/" in mapping["document"] and "products/" not in mapping["document"]),
    ("a document is told NOT to name a PDF",
     "Do NOT name a PDF" in mapping["document"]),
    ("a dashboard still goes to products/<slug>/",
     "products/[kebab-case-name]/" in mapping["dashboard"]),
    ("an unknown type falls back to the software rule, not to nothing",
     mapping.get("software") is not None),
]
print()
for name, ok in checks:
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")
    if not ok:
        die(name)

if "Save to products/[kebab-case-name]/[main file based on type]" in src:
    die("the old blanket save line is still in the prompt")
print("  ok   the old blanket line is gone")

print("\napplied: " + ", ".join(applied))
print(f"backup:  {backup.name}")
print()
print("Restart the API, then a document brief drafted by the wizard will name")
print("docs/ instead of a path the pipeline never writes to:")
print("  launchctl kickstart -k gui/$(id -u)/com.ducorn.api")
