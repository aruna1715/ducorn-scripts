#!/usr/bin/env python3
"""Replace hardcoded theme colours with CSS custom properties.

Why: the dashboard styles elements inline. The previous light theme matched on
the style attribute ([style*=";color:#4fd1c5"]). But when JS touches ANY style
property (92 places do), the browser re-serialises the whole inline
declaration — "#4fd1c5" becomes "rgb(79, 209, 197)" and "background:rgba(13,17,23,.6)"
becomes "background: rgba(13, 17, 23, 0.6)". The attribute selectors then stop
matching and the dark colours come back permanently. var() references survive
serialisation intact, so tokens fix the whole class of bug.
"""
import pathlib, re, sys

P = pathlib.Path.home() / "mnt/DC/ducorn-products/products/ducorn-dashboard/index.html"
if not P.exists():
    P = pathlib.Path("/Users/ducorn/DC/ducorn-products/products/ducorn-dashboard/index.html")
h = P.read_text(); orig = h

def must(c, m):
    if not c: print("FAIL: " + m); sys.exit(1)

# ── 1. remove the three old light-theme blocks ──────────────────────────────
m1 = "/* ── LIGHT THEME ── */"
m2 = "\n  /* ══════════ INTELLIGENCE RAIL"
must(h.count(m1) == 1 and h.count(m2) == 1, "original light block markers")
h = h[:h.index(m1)] + h[h.index(m2) + 1:]

m3 = "\n  /* ══════════ LIGHT THEME — inline-style colour remap ══════════ */"
must(h.count(m3) == 1, "remap block marker")
must(h.count("\n</style>") == 1, "</style> not unique")
h = h[:h.index(m3)] + "\n</style>" + h.split("\n</style>", 1)[1]
print("removed old light-theme blocks")

# ── 2. tokenise colours ─────────────────────────────────────────────────────
# context-specific first
ctx = [
    ("body { margin: 0; background: #0d1117; color: #d8e2ea;",
     "body { margin: 0; background: var(--page); color: var(--ink-4);"),
    ("color:#0d1117", "color:var(--on-amber)"),
]
for old, new in ctx:
    must(old in h, "context replace missing: " + old[:40])
    h = h.replace(old, new)

SUBS = [
    # alpha families — prefix match keeps the alpha value intact
    ("rgba(79,209,197,",  "rgba(var(--accent-rgb),"),
    ("rgba(13,17,23,",    "rgba(var(--surface-rgb),"),
    ("rgba(22,28,36,",    "rgba(var(--surface-2-rgb),"),
    ("rgba(11,15,20,",    "rgba(var(--panel-rgb),"),
    ("rgba(240,180,88,",  "rgba(var(--amber-rgb),"),
    ("rgba(95,211,154,",  "rgba(var(--green-rgb),"),
    ("rgba(255,107,107,", "rgba(var(--red-rgb),"),
    ("rgba(91,107,120,",  "rgba(var(--muted-rgb),"),
    # neutral surfaces used by the wizard modal
    ("rgba(255,255,255,.03)", "var(--field)"),
    ("rgba(255,255,255,.04)", "var(--field)"),
    ("rgba(255,255,255,.06)", "var(--field-strong)"),
    ("rgba(255,255,255,.08)", "var(--field-strong)"),
    ("rgba(255,255,255,.1)",  "var(--field-border)"),
    # solid hexes
    ("#4fd1c5", "var(--accent)"),
    ("#f0b458", "var(--amber)"),
    ("#f7c979", "var(--amber-2)"),
    ("#5fd39a", "var(--green)"),
    ("#ff6b6b", "var(--red)"),
    ("#fc8181", "var(--red-2)"),
    ("#a78bfa", "var(--violet)"),
    ("#e6f4f1", "var(--ink)"),
    ("#dbe6ee", "var(--ink-2)"),
    ("#cdd9e5", "var(--ink-3)"),
    ("#d8e2ea", "var(--ink-4)"),
    ("#c4d4de", "var(--ink-5)"),
    ("#5b6b78", "var(--muted)"),
    ("#8a9ba8", "var(--muted-2)"),
    ("#7f909e", "var(--muted-3)"),
    ("#3a4a55", "var(--muted-4)"),
    ("#4a5560", "var(--muted-5)"),
    ("#11161d", "var(--surface-3)"),
    ("background:#0d1117", "background:var(--surface)"),
]
for old, new in SUBS:
    h = h.replace(old, new)

left = re.findall(r'#(?:4fd1c5|f0b458|5fd39a|ff6b6b|5b6b78|0d1117|e6f4f1|dbe6ee)', h)
must(not left, "untokenised colours remain: %s" % set(left))

# ── 3. token definitions ────────────────────────────────────────────────────
TOKENS = """<style>
/* ══════════════ THEME TOKENS ══════════════
   Every colour below is referenced through var(). Inline styles keep their
   var() text when the browser re-serialises them after a JS style write, so
   theming survives hover handlers and any other .style mutation. */
:root {
  --accent:#4fd1c5;   --accent-rgb:79,209,197;
  --amber:#f0b458;    --amber-rgb:240,180,88;   --amber-2:#f7c979;
  --green:#5fd39a;    --green-rgb:95,211,154;
  --red:#ff6b6b;      --red-rgb:255,107,107;    --red-2:#fc8181;
  --violet:#a78bfa;
  --ink:#e6f4f1; --ink-2:#dbe6ee; --ink-3:#cdd9e5; --ink-4:#d8e2ea; --ink-5:#c4d4de;
  --muted:#5b6b78;    --muted-rgb:91,107,120;
  --muted-2:#8a9ba8; --muted-3:#7f909e; --muted-4:#3a4a55; --muted-5:#4a5560;
  --page:#0d1117;
  --surface:#0d1117;  --surface-rgb:13,17,23;
  --surface-2-rgb:22,28,36;
  --surface-3:#11161d;
  --panel-rgb:11,15,20;
  --field:rgba(255,255,255,.04);
  --field-strong:rgba(255,255,255,.08);
  --field-border:rgba(255,255,255,.1);
  --on-amber:#0d1117;
}
:root[data-theme="light"] {
  --accent:#0b6d63;   --accent-rgb:13,148,136;
  --amber:#8a5a06;    --amber-rgb:183,121,31;   --amber-2:#8a5a06;
  --green:#0f7050;    --green-rgb:15,112,80;
  --red:#c02626;      --red-rgb:192,38,38;      --red-2:#c02626;
  --violet:#6b46c1;
  --ink:#1a202c; --ink-2:#1a202c; --ink-3:#1a202c; --ink-4:#1a202c; --ink-5:#2d3748;
  --muted:#4a5568;    --muted-rgb:74,85,104;
  --muted-2:#4a5568; --muted-3:#4a5568; --muted-4:#5a677a; --muted-5:#718096;
  --page:#eef2f7;
  --surface:#ffffff;  --surface-rgb:255,255,255;
  --surface-2-rgb:255,255,255;
  --surface-3:#ffffff;
  --panel-rgb:255,255,255;
  --field:#f1f5f9;
  --field-strong:#e2e8f0;
  --field-border:rgba(0,0,0,.12);
  --on-amber:#ffffff;
}
"""
must(h.count("<style>") == 1, "<style> not unique")
h = h.replace("<style>", TOKENS, 1)

# ── 4. the only light rules still needed are structural ─────────────────────
LIGHT = """
  /* ══════════ LIGHT THEME — structural only (colour comes from tokens) ══════════ */
  [data-theme="light"] .card, [data-theme="light"] section.card, [data-theme="light"] header { background:#ffffff; border-color:rgba(0,0,0,.1); }
  [data-theme="light"] .card-scan { display:none; }
  [data-theme="light"] #app > div[style*="radial-gradient"] { background:none; }
  [data-theme="light"] #app > div[style*="linear-gradient(rgba"] { background-image:none; }
  [data-theme="light"] #intelPanel { box-shadow:-18px 0 48px rgba(0,0,0,.12); }
  [data-theme="light"] #intelRail { border-right-color:rgba(0,0,0,.1); }
  [data-theme="light"] .btn { background:var(--field-strong); color:#2d3748; border-color:rgba(0,0,0,.15); }
  [data-theme="light"] .btn-active { background:rgba(var(--accent-rgb),.1); color:var(--accent); border-color:rgba(var(--accent-rgb),.45); }
  [data-theme="light"] .rail-badge { color:#ffffff; }
</style>"""
h = h.replace("\n</style>", "\n" + LIGHT, 1)

P.write_text(h)
print("OK: %d -> %d chars" % (len(orig), len(h)))
