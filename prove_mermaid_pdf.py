#!/usr/bin/env python3
"""
Prove the LIVE PDF service turns a diagram into a picture.

    python3 scripts/prove_mermaid_pdf.py

── WHY THIS AND NOT THE PATCH'S OWN TESTS ───────────────────────────────────

patch_pdf_mermaid.py checks its transform, and I rendered a diagram end to end
before writing it. Neither of those goes through the service that will actually
convert your document: a running process, started by launchd, with its own
interpreter and its own copy of the code.

Every deploy bug this week was the difference between "the function works" and
"the running thing works". This posts real markdown to http://localhost:8001,
takes the real PDF back, and reads it.

── WHAT IT ASSERTS ──────────────────────────────────────────────────────────

    the diagram source is NOT in the PDF's text     it became a picture
    the node labels ARE                             it is the right picture
    the prose around it is still text               nothing else broke
    the page carries vector drawing operations      it is drawn, not an image
    a code sample containing </body> survives       the injection point holds

The last one is the case that broke my first version: the minified renderer
contains the literal "</body>", so injecting at the FIRST occurrence put it
before the diagrams. A document about web architecture is exactly the document
that would hit that.
"""
import os
import subprocess
import sys
from pathlib import Path

VENV_PY = "/Users/ducorn/DC/ducorn/.venv/bin/python"
API = "http://localhost:8001/v1/convert"
KEY = os.environ.get("PDF_API_KEY", "dk_pro_test_key_002")
OUT = Path("/tmp/ducorn-mermaid-proof.pdf")

# pymupdf and requests live in the pipeline venv.
try:
    import pymupdf  # noqa: F401
    import requests  # noqa: F401
except ImportError:
    if os.environ.get("_PROVE_MERMAID_REEXEC") == "1":
        sys.exit("pymupdf/requests are not importable even under the venv.")
    if not Path(VENV_PY).exists():
        sys.exit(f"{VENV_PY} does not exist.")
    os.environ["_PROVE_MERMAID_REEXEC"] = "1"
    sys.exit(subprocess.call([VENV_PY, str(Path(__file__).resolve())]
                             + sys.argv[1:], env=os.environ))

import pymupdf
import requests

MD = """# DuCorn Architecture — render proof

The pipeline, as a diagram:

```mermaid
graph TD
  slack[Slack approval] --> flow[LangGraph pipeline]
  flow --> skills[G-Stack skills]
  flow --> router[Model router]
  router --> ollama[Ollama local]
  router --> remote[Remote providers]
```

Prose after the diagram, which must remain selectable text.

A code sample containing a closing body tag, which broke the first version:

```html
<body><p>awkward</p></body>
```
"""

print("posting markdown with one diagram to the live PDF service…")
try:
    r = requests.post(API, timeout=120,
                      headers={"Content-Type": "application/json",
                               "X-API-Key": KEY},
                      json={"source_type": "markdown", "content": MD,
                            "filename": "mermaid-proof.pdf"})
except requests.exceptions.ConnectionError:
    sys.exit("the PDF service is not answering on :8001.\n"
             "  launchctl kickstart -k gui/$(id -u)/com.ducorn.pdf")

if r.status_code != 200:
    sys.exit(f"the service returned {r.status_code}: {r.text[:300]}")

OUT.write_bytes(r.content)
print(f"got {len(r.content):,} bytes → {OUT}")

doc = pymupdf.open(OUT)
text = "".join(p.get_text() for p in doc)
drawings = sum(len(p.get_drawings()) for p in doc)

checks = [
    ("the diagram source is not in the text (it became a picture)",
     "graph TD" not in text),
    ("the node labels are in the text (it is the right picture)",
     all(w in text for w in ("Slack approval", "Model router", "Ollama local"))),
    ("the surrounding prose is still selectable text",
     "must remain selectable text" in text),
    ("the page carries vector drawing operations",
     drawings > 10),
    ("a code sample containing </body> survived intact",
     "<body><p>awkward</p></body>" in text),
]

print()
failed = 0
for name, ok in checks:
    print(f"  {'ok  ' if ok else 'FAIL'} {name}")
    failed += not ok

png = OUT.with_suffix(".png")
doc[0].get_pixmap(dpi=90).save(png)
print(f"\n  page 1 → {png}   (open it — the diagram should be a flowchart)")
print(f"  {doc.page_count} page(s), {drawings} drawing operations, "
      f"{len(text):,} characters of text")

if failed:
    print(f"\n{failed} check(s) failed. The service may be running the code from "
          f"before the patch:")
    print("  launchctl kickstart -k gui/$(id -u)/com.ducorn.pdf")
    print("  tail -20 ~/DC/logs/pdf_api.log")
    sys.exit(1)
print("\nDiagrams render in the PDF. The brief's Mermaid caveat no longer applies.")
