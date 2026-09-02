#!/usr/bin/env python3
"""Tidy-up after tokenisation: drop leftover hardcoded light rules and give the
status-bar separators a token of their own."""
import pathlib, sys

P = pathlib.Path.home() / "mnt/DC/ducorn-products/products/ducorn-dashboard/index.html"
if not P.exists():
    P = pathlib.Path("/Users/ducorn/DC/ducorn-products/products/ducorn-dashboard/index.html")
h = P.read_text(); orig = h

def must(c, m):
    if not c: print("FAIL: " + m); sys.exit(1)

# 1. these predate tokenisation and now fight the tokens (NEW PRODUCT was 3.48:1)
DEAD = """  [data-theme="light"] .act-btn { color:#4a5568;border-color:rgba(0,0,0,.12); }
  [data-theme="light"] .act-btn:hover { color:#0d9488;border-color:rgba(13,148,136,.4);background:rgba(13,148,136,.06); }
  [data-theme="light"] .act-btn.primary { color:#b7791f;border-color:rgba(183,121,31,.35); }
  [data-theme="light"] #themeToggleBtn { color:#4a5568;border-color:rgba(0,0,0,.12);background:transparent; }
  [data-theme="light"] .act-sep { background:rgba(0,0,0,.1); }
"""
must(DEAD in h, "leftover act-btn light rules not found verbatim")
h = h.replace(DEAD, "", 1)

# 2. separators: a token instead of a translucent accent that vanishes on white
for alpha in (".3", ".28"):
    h = h.replace(f'<span style="color:rgba(var(--accent-rgb),{alpha});">|</span>', '<span class="sep">|</span>')
must('<span class="sep">|</span>' in h, "separator rewrite failed")
must('rgba(var(--accent-rgb),.3);">|' not in h, "separators left behind")

h = h.replace("  --on-amber:#0d1117;\n}", "  --on-amber:#0d1117;\n  --rule:rgba(79,209,197,.32);\n}", 1)
h = h.replace("  --on-amber:#ffffff;\n}", "  --on-amber:#ffffff;\n  --rule:rgba(74,85,104,.75);\n}", 1)
must(h.count("--rule:") == 2, "rule token not added to both themes")

h = h.replace(".mono { font-family:'IBM Plex Mono',monospace; }",
              ".mono { font-family:'IBM Plex Mono',monospace; }\n.sep { color:var(--rule); }", 1)
must(".sep { color:var(--rule); }" in h, "sep class not added")

P.write_text(h)
print("OK: %d -> %d chars" % (len(orig), len(h)))
