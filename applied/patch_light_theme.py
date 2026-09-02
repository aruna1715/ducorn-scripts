#!/usr/bin/env python3
"""Full light-theme pass for the DuCorn dashboard.

The dashboard is styled almost entirely with inline styles carrying dark-theme
hex colours. Author !important rules beat normal inline declarations, so this
maps every inline colour/background to a light-theme equivalent by matching the
style attribute. Teal (#4fd1c5) is unreadable on white and is replaced with a
darker teal that clears WCAG AA.
"""
import pathlib, sys

P = pathlib.Path.home() / "mnt/DC/ducorn-products/products/ducorn-dashboard/index.html"
if not P.exists():
    P = pathlib.Path("/Users/ducorn/DC/ducorn-products/products/ducorn-dashboard/index.html")
h = P.read_text(); orig = h

# ── text colour map: dark-theme hex → light-theme hex ───────────────────────
TEXT = {
    "#4fd1c5": "#0b6d63",   # teal accent      → deep teal   (7.0:1 on white)
    "#5b6b78": "#4a5568",   # muted label      → slate       (7.5:1)
    "#8a9ba8": "#4a5568",
    "#7f909e": "#4a5568",
    "#3a4a55": "#718096",   # collapse chevron → mid slate
    "#4a5560": "#4a5568",
    "#e6f4f1": "#1a202c",   # near-white text  → ink
    "#dbe6ee": "#1a202c",
    "#cdd9e5": "#1a202c",
    "#d8e2ea": "#1a202c",
    "#f0b458": "#8a5a06",   # amber            → dark amber  (5.9:1)
    "#f7c979": "#8a5a06",
    "#5fd39a": "#0f7050",   # green            → forest      (5.4:1)
    "#a78bfa": "#6b46c1",   # purple           → deep violet (5.6:1)
    "#ff6b6b": "#c02626",   # red              → dark red    (5.9:1)
    "#fc8181": "#c02626",
}

# ── background map: dark slabs → light surfaces ─────────────────────────────
BG = [
    ("rgba(22,28,36",  "#f7fafc"),
    ("rgba(13,17,23",  "#f7fafc"),
    ("rgba(11,15,20",  "#ffffff"),
    ("#0d1117",        "#ffffff"),
    ("#11161d",        "#ffffff"),
    ("rgba(255,255,255,.04)", "#f1f5f9"),
    ("rgba(255,255,255,.08)", "#e2e8f0"),
]

lines = ['', '  /* ══════════ LIGHT THEME — inline-style colour remap ══════════ */']

for dark, light in TEXT.items():
    sels = ",\n  ".join([
        f'[data-theme="light"] [style*=";color:{dark}"]',
        f'[data-theme="light"] [style*="; color:{dark}"]',
        f'[data-theme="light"] [style^="color:{dark}"]',
    ])
    lines.append(f'  {sels} {{ color:{light} !important; }}')

for dark, light in BG:
    sels = ",\n  ".join([
        f'[data-theme="light"] [style*=";background:{dark}"]',
        f'[data-theme="light"] [style^="background:{dark}"]',
        f'[data-theme="light"] [style*=" background:{dark}"]',
    ])
    lines.append(f'  {sels} {{ background:{light} !important; }}')

lines += [
    '',
    '  /* teal fills (rules, dots, accent bars) darkened so they read on white */',
    '  [data-theme="light"] [style*="background:#4fd1c5"] { background:#0d9488 !important; }',
    '  [data-theme="light"] [style*="background:#f0b458"] { background:#b7791f !important; }',
    '',
    '  /* faint teal borders on white → visible slate-teal */',
    '  [data-theme="light"] [style*="solid rgba(79,209,197"] { border-color:rgba(13,148,136,.34) !important; }',
    '  [data-theme="light"] [style*="solid rgba(240,180,88"] { border-color:rgba(183,121,31,.40) !important; }',
    '  [data-theme="light"] [style*="solid rgba(95,211,154"] { border-color:rgba(15,112,80,.36) !important; }',
    '  [data-theme="light"] [style*="solid rgba(255,107,107"] { border-color:rgba(192,38,38,.36) !important; }',
    '',
    '  /* kill the dark-theme ambience layers */',
    '  [data-theme="light"] #app > div[style*="radial-gradient"] { background:none !important; }',
    '  [data-theme="light"] #app > div[style*="linear-gradient(rgba(79,209,197"] { background-image:none !important; }',
    '',
    '  /* component classes (not inline-styled) */',
    '  [data-theme="light"] .rail-btn { color:#4a5568; }',
    '  [data-theme="light"] .rail-btn:hover { color:#0b6d63;background:rgba(13,148,136,.07);border-color:rgba(13,148,136,.28); }',
    '  [data-theme="light"] #intelRail .rail-logo { color:#0b6d63; }',
    '  [data-theme="light"] .rail-badge { background:#b7791f;color:#ffffff; }',
    '  [data-theme="light"] .intel-close { color:#0b6d63 !important;background:rgba(13,148,136,.08) !important;border-color:rgba(13,148,136,.3) !important; }',
    '  [data-theme="light"] .collapse-btn { color:#718096 !important; }',
    '  [data-theme="light"] .badge { background:rgba(183,121,31,.14) !important;color:#8a5a06 !important;border-color:rgba(183,121,31,.35) !important; }',
    '  [data-theme="light"] .section-label { color:#4a5568 !important; }',
    '  [data-theme="light"] .mono { color:#2d3748; }',
    '  [data-theme="light"] #clockEl { color:#1a202c !important; }',
    '  [data-theme="light"] #dateEl { color:#4a5568 !important; }',
    '  [data-theme="light"] #budgetDisplay { color:#0b6d63 !important; }',
    '  [data-theme="light"] a { color:#0b6d63 !important; }',
    '  [data-theme="light"] .act-btn { color:#4a5568 !important; }',
    '  [data-theme="light"] .act-btn:hover { color:#0b6d63 !important; }',
    '  [data-theme="light"] .act-btn.primary { color:#8a5a06 !important; }',
    '  [data-theme="light"] input::placeholder, [data-theme="light"] textarea::placeholder { color:#718096 !important; }',
    '',
]
CSS = "\n".join(lines) + "</style>"

if h.count("\n</style>") != 1:
    print("FAIL: </style> not unique"); sys.exit(1)
h = h.replace("\n</style>", "\n" + CSS, 1)

P.write_text(h)
print("OK: %d -> %d chars (%d light rules)" % (len(orig), len(h), len(lines)))
