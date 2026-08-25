#!/usr/bin/env python3
"""Declutter the DuCorn dashboard header: meta left, title center, clock right;
action buttons demoted to the filter bar as uniform ghost buttons."""
import pathlib, sys

P = pathlib.Path.home() / "mnt/DC/ducorn-products/products/ducorn-dashboard/index.html"
if not P.exists():
    P = pathlib.Path("/Users/ducorn/DC/ducorn-products/products/ducorn-dashboard/index.html")
h = P.read_text(); orig = h

def must(c, m):
    if not c: print("FAIL: " + m); sys.exit(1)

# ── CSS ─────────────────────────────────────────────────────────────────────
CSS = """
  /* ══════════ HEADER ACTION BUTTONS ══════════ */
  .act-btn { cursor:pointer;display:inline-flex;align-items:center;font-family:'IBM Plex Mono',monospace;font-size:9px;letter-spacing:.16em;padding:6px 13px;border-radius:2px;background:transparent;border:1px solid rgba(79,209,197,.2);color:#7f909e;text-decoration:none;white-space:nowrap;transition:color .18s,border-color .18s,background .18s; }
  .act-btn:hover { color:#4fd1c5;border-color:rgba(79,209,197,.5);background:rgba(79,209,197,.07); }
  .act-btn.primary { color:#f0b458;border-color:rgba(240,180,88,.35); }
  .act-btn.primary:hover { color:#f7c979;border-color:rgba(240,180,88,.6);background:rgba(240,180,88,.08); }
  .act-sep { width:1px;height:15px;background:rgba(79,209,197,.16); }
  #themeToggleBtn { cursor:pointer;font-family:'IBM Plex Mono',monospace;font-size:8.5px;letter-spacing:.14em;padding:4px 9px;border-radius:2px;background:transparent;border:1px solid rgba(79,209,197,.22);color:#7f909e;transition:color .18s,border-color .18s; }
  #themeToggleBtn:hover { color:#4fd1c5;border-color:rgba(79,209,197,.5); }
  [data-theme="light"] .act-btn { color:#4a5568;border-color:rgba(0,0,0,.12); }
  [data-theme="light"] .act-btn:hover { color:#0d9488;border-color:rgba(13,148,136,.4);background:rgba(13,148,136,.06); }
  [data-theme="light"] .act-btn.primary { color:#b7791f;border-color:rgba(183,121,31,.35); }
  [data-theme="light"] #themeToggleBtn { color:#4a5568;border-color:rgba(0,0,0,.12);background:transparent; }
  [data-theme="light"] .act-sep { background:rgba(0,0,0,.1); }
</style>"""
must(h.count('\n</style>') == 1, "</style> not unique")
h = h.replace('\n</style>', CSS, 1)

# ── HEADER + FILTER BAR ─────────────────────────────────────────────────────
start = '    <!-- HEADER -->'
end   = '    <!-- ATLAS CHAT + VOICE ORB -->'
must(h.count(start) == 1 and h.count(end) == 1, "header/atlas markers not unique")
si, ei = h.index(start), h.index(end)
old = h[si:ei]
for frag in ['id="uptimeEl"', 'id="clockEl"', 'id="dateEl"', 'id="budgetDisplay"',
             'id="themeToggleBtn"', 'id="btnCompany"', 'id="btnProduct"',
             'id="productDropdownWrap"', 'id="productLabel"', 'id="productDropdown"',
             'syncToDrive()', 'openNewProduct()', 'openBriefWizard()']:
    must(frag in old, "expected fragment missing from old header: " + frag)

NEW = """    <!-- HEADER -->
    <header class="card" style="display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:24px;padding:18px 24px;">
      <div class="card-scan"></div>

      <!-- left: system meta -->
      <div>
        <span class="mono section-label" style="white-space:nowrap;">UPTIME <span id="uptimeEl">0D</span></span>
      </div>

      <!-- center: wordmark -->
      <div style="display:flex;flex-direction:column;align-items:center;gap:6px;">
        <h1 style="margin:0;font-size:22px;font-weight:600;letter-spacing:.42em;color:#e6f4f1;text-indent:.42em;white-space:nowrap;">DUCORN DASHBOARD</h1>
        <div style="display:flex;align-items:center;gap:10px;">
          <span style="width:40px;height:1px;background:linear-gradient(90deg,transparent,#4fd1c5);"></span>
          <span class="mono" style="font-size:10px;letter-spacing:.28em;color:#4fd1c5;">FLEET OF 9</span>
          <span style="width:40px;height:1px;background:linear-gradient(90deg,#4fd1c5,transparent);"></span>
        </div>
      </div>

      <!-- right: clock -->
      <div style="display:flex;flex-direction:column;align-items:flex-end;gap:5px;">
        <div style="display:flex;align-items:center;gap:11px;">
          <button onclick="toggleTheme()" id="themeToggleBtn" title="Switch to light theme">LIGHT</button>
          <span id="clockEl" class="mono" style="font-size:24px;font-weight:500;letter-spacing:.06em;color:#e6f4f1;">00:00:00</span>
        </div>
        <div class="mono" style="display:flex;align-items:center;gap:9px;font-size:9px;letter-spacing:.16em;color:#5b6b78;white-space:nowrap;">
          <span id="dateEl"></span>
          <span style="color:rgba(79,209,197,.28);">|</span>
          <span>BUDGET <span id="budgetDisplay" style="color:#4fd1c5;">&mdash;</span></span>
        </div>
      </div>
    </header>

    <!-- FILTER + ACTIONS BAR -->
    <div style="position:relative;display:flex;align-items:center;justify-content:space-between;gap:20px;margin-top:18px;padding:11px 18px;background:rgba(22,28,36,.6);border:1px solid rgba(79,209,197,.14);border-radius:3px;">
      <div style="display:flex;align-items:center;gap:8px;">
        <button id="btnCompany" class="btn btn-active" onclick="setView('company')">COMPANY VIEW</button>
        <button id="btnProduct" class="btn btn-inactive" onclick="setView('product')">PRODUCT VIEW</button>
        <div id="productDropdownWrap" style="display:none;position:relative;margin-left:6px;">
          <button onclick="toggleDropdown()" style="cursor:pointer;display:flex;align-items:center;gap:12px;font-family:'IBM Plex Mono',monospace;font-size:10px;letter-spacing:.18em;padding:8px 15px;border-radius:2px;background:rgba(13,17,23,.8);border:1px solid rgba(79,209,197,.35);color:#4fd1c5;">
            <span id="productLabel">ALL PRODUCTS</span><span style="color:#5b6b78;">&#9662;</span>
          </button>
          <div id="productDropdown" style="display:none;position:absolute;top:calc(100% + 6px);left:0;z-index:40;min-width:262px;padding:5px;background:#11161d;border:1px solid rgba(79,209,197,.3);border-radius:2px;box-shadow:0 14px 40px rgba(0,0,0,.6);flex-direction:column;"></div>
        </div>
      </div>

      <div style="display:flex;align-items:center;gap:8px;">
        <a class="act-btn primary" href="#" onclick="event.preventDefault();openNewProduct();" title="Start a new product pipeline">NEW PRODUCT</a>
        <a class="act-btn" href="#" onclick="openBriefWizard();return false;" title="Generate a product brief with AI">BRIEF WIZARD</a>
        <span class="act-sep"></span>
        <a class="act-btn" href="#" onclick="event.preventDefault();syncToDrive();" title="Sync all docs to Google Drive">SYNC DRIVE</a>
        <a class="act-btn" href="slack://channel?team=&amp;id=C0BLTH5111V" target="_blank" onclick="if(!this.href.includes('slack://'))return;setTimeout(()=>window.open('https://ducorn.slack.com/archives/C0BLTH5111V','_blank'),500)" title="Open #duc-board in Slack">DUC-BOARD</a>
      </div>

      <div style="position:absolute;left:0;right:0;bottom:-1px;height:1px;background:linear-gradient(90deg,transparent,rgba(79,209,197,.75),transparent);box-shadow:0 0 12px rgba(79,209,197,.45);"></div>
    </div>

"""
h = h[:si] + NEW + h[ei:]

# ── theme button label: real words, not missing glyphs ──────────────────────
old_t = "  if (btn) btn.textContent = isDark ? '☽ THEME' : '☀ THEME';"
must(old_t in h, "toggleTheme label line not found")
h = h.replace(old_t,
  "  if (btn) { btn.textContent = isDark ? 'DARK' : 'LIGHT';\n"
  "             btn.title = isDark ? 'Switch to dark theme' : 'Switch to light theme'; }", 1)

# ── restore saved theme should also sync the button label ───────────────────
old_r = """  const t = localStorage.getItem('dcTheme');
  if (t) document.documentElement.setAttribute('data-theme', t);"""
must(old_r in h, "theme restore block not found")
h = h.replace(old_r, """  const t = localStorage.getItem('dcTheme');
  if (t) document.documentElement.setAttribute('data-theme', t);
  document.addEventListener('DOMContentLoaded', () => {
    const b = document.getElementById('themeToggleBtn');
    if (b) { const light = t === 'light';
             b.textContent = light ? 'DARK' : 'LIGHT';
             b.title = light ? 'Switch to dark theme' : 'Switch to light theme'; }
  });""", 1)

P.write_text(h)
print("OK: %d -> %d chars" % (len(orig), len(h)))
