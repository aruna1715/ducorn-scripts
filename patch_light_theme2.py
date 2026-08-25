#!/usr/bin/env python3
"""Second light-theme pass: close the remaining WCAG AA gaps found by audit."""
import pathlib, sys

P = pathlib.Path.home() / "mnt/DC/ducorn-products/products/ducorn-dashboard/index.html"
if not P.exists():
    P = pathlib.Path("/Users/ducorn/DC/ducorn-products/products/ducorn-dashboard/index.html")
h = P.read_text(); orig = h

def must(c, m):
    if not c: print("FAIL: " + m); sys.exit(1)

EXTRA = """
  /* ── light theme: remaining AA gaps ── */
  [data-theme="light"] [style*=";color:#c4d4de"],
  [data-theme="light"] [style*="; color:#c4d4de"] { color:#2d3748 !important; }
  [data-theme="light"] .btn-active { color:#0b6d63 !important;background:rgba(13,148,136,.09) !important;border-color:rgba(13,148,136,.4) !important; }
  [data-theme="light"] .collapse-btn { color:#5a677a !important; }
  [data-theme="light"] .rail-badge { background:#8a5a06;color:#ffffff; }
  /* decorative separators: teal at 30% is invisible on white */
  [data-theme="light"] [style*="color:rgba(79,209,197,.3)"],
  [data-theme="light"] [style*="color:rgba(79,209,197,.28)"],
  [data-theme="light"] [style*="color:rgba(79,209,197,.25)"] { color:rgba(74,85,104,.55) !important; }
</style>"""
must(h.count("\n</style>") == 1, "</style> not unique")
h = h.replace("\n</style>", "\n" + EXTRA, 1)

P.write_text(h)
print("OK: %d -> %d chars" % (len(orig), len(h)))
