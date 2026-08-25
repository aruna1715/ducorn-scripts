#!/usr/bin/env python3
"""Move DuCorn Intelligence sections into a right slide panel driven by a left icon rail."""
import re, sys, pathlib

P = pathlib.Path.home() / "mnt" / "DC" / "ducorn-products" / "products" / "ducorn-dashboard" / "index.html"
if not P.exists():
    P = pathlib.Path("/Users/ducorn/DC/ducorn-products/products/ducorn-dashboard/index.html")
html = P.read_text()
orig = html

def must(cond, msg):
    if not cond:
        print("FAIL: " + msg); sys.exit(1)

# ── 1. CUT the inline Intelligence block (KPI grid + SAGE section) ───────────
start_marker = '    <!-- KPI CARDS + APPROVALS + ACTIVITY -->'
must(start_marker in html, "start marker not found")
si = html.index(start_marker)
rc = html.index('<div id="researchCards"', si)
ei = html.index('</section>', rc) + len('</section>')
cut = html[si:ei]
must('id="kpiCards"' in cut and 'id="researchCards"' in cut and 'id="supportInput"' in cut,
     "cut block missing expected ids")
html = html[:si] + html[ei:]
print("cut %d chars of inline sections" % len(cut))

# ── 2. Shift main content + status bar right of the rail ────────────────────
old_wrap = '<div style="position:relative;padding:22px 30px 34px;">'
must(html.count(old_wrap) == 1, "padding wrapper not unique")
html = html.replace(old_wrap, '<div style="position:relative;padding:22px 30px 34px 78px;">')

old_sb = 'display:flex;align-items:center;padding:0 28px;gap:20px;z-index:100;'
must(html.count(old_sb) == 1, "status bar style not unique")
html = html.replace(old_sb, 'display:flex;align-items:center;padding:0 28px 0 78px;gap:20px;z-index:100;')

# ── 3. CSS ──────────────────────────────────────────────────────────────────
CSS = """
  /* ══════════ INTELLIGENCE RAIL + RIGHT SLIDE PANEL ══════════ */
  #intelRail { position:fixed;top:0;left:0;width:64px;height:100vh;z-index:150;display:flex;flex-direction:column;align-items:center;gap:5px;padding:14px 0 44px;background:rgba(11,15,20,.94);border-right:1px solid rgba(79,209,197,.18); }
  #intelRail .rail-logo { font-family:'IBM Plex Mono',monospace;font-size:12px;letter-spacing:.14em;color:#4fd1c5;margin-bottom:12px;opacity:.85; }
  .rail-btn { position:relative;cursor:pointer;width:50px;padding:8px 0 6px;display:flex;flex-direction:column;align-items:center;gap:4px;background:transparent;border:1px solid transparent;border-radius:3px;color:#5b6b78;font-family:'IBM Plex Mono',monospace;transition:background .18s,border-color .18s,color .18s; }
  .rail-btn:hover { background:rgba(79,209,197,.08);border-color:rgba(79,209,197,.25);color:#4fd1c5; }
  .rail-btn.active { background:rgba(79,209,197,.15);border-color:rgba(79,209,197,.45);color:#4fd1c5; }
  .rail-ico { font-size:15px;line-height:1; }
  .rail-lab { font-size:7.5px;letter-spacing:.08em; }
  .rail-badge { position:absolute;top:2px;right:4px;min-width:15px;height:15px;padding:0 3px;border-radius:8px;background:#f0b458;color:#0d1117;font-size:8px;line-height:15px;text-align:center;display:none;font-weight:700; }
  #intelOverlay { display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:180; }
  #intelPanel { position:fixed;top:0;right:0;height:100vh;width:clamp(360px,36vw,520px);z-index:190;background:rgba(11,15,20,.985);border-left:1px solid rgba(79,209,197,.28);box-shadow:-18px 0 48px rgba(0,0,0,.55);display:flex;flex-direction:column;transform:translateX(102%);transition:transform .28s cubic-bezier(.4,0,.2,1); }
  #intelPanel.open { transform:translateX(0); }
  .intel-head { display:flex;align-items:center;justify-content:space-between;gap:12px;padding:18px 20px 14px;border-bottom:1px solid rgba(79,209,197,.18);flex-shrink:0; }
  .intel-body { flex:1;overflow-y:auto;padding:16px 18px 40px; }
  .intel-sec { display:none; }
  .intel-sec.active { display:block; }
  .intel-close { cursor:pointer;background:rgba(79,209,197,.1);border:1px solid rgba(79,209,197,.3);border-radius:2px;color:#4fd1c5;font-family:'IBM Plex Mono',monospace;font-size:11px;padding:4px 9px; }
  #intelPanel #kpiCards { grid-template-columns:repeat(2,1fr) !important; }
  #intelPanel #researchCards { grid-template-columns:1fr !important; }
  #intelPanel .card { margin:0 !important; }
  #intelPanel #activityFeed, #intelPanel #digestText { max-height:none !important; }
  [data-theme="light"] #intelRail { background:#ffffff;border-right-color:rgba(0,0,0,.1); }
  [data-theme="light"] #intelPanel { background:#ffffff;border-left-color:rgba(0,0,0,.12);box-shadow:-18px 0 48px rgba(0,0,0,.12); }
  [data-theme="light"] .intel-head { border-bottom-color:rgba(0,0,0,.1); }
  [data-theme="light"] .rail-btn.active { background:rgba(13,148,136,.12);border-color:rgba(13,148,136,.4);color:#0d9488; }
  @media (max-width:900px) { #intelPanel { width:100vw; } }
</style>"""
must(html.count('\n</style>') >= 1, "</style> not found")
html = html.replace('\n</style>', CSS, 1)

# ── 4. Rail + panel markup, inserted just before the status bar ─────────────
MARKUP = """
  <!-- ══════════════════ INTELLIGENCE RAIL ══════════════════ -->
  <nav id="intelRail" aria-label="Intelligence sections">
    <div class="rail-logo">DC</div>
    <button class="rail-btn" data-panel="kpi" onclick="toggleIntel('kpi')" title="KPIs"><span class="rail-ico">▦</span><span class="rail-lab">KPIS</span></button>
    <button class="rail-btn" data-panel="approvals" onclick="toggleIntel('approvals')" title="Pending approvals"><span class="rail-ico">✓</span><span class="rail-lab">APPROVE</span><span class="rail-badge" id="railBadgeApprovals">0</span></button>
    <button class="rail-btn" data-panel="activity" onclick="toggleIntel('activity')" title="Agent activity"><span class="rail-ico">⌁</span><span class="rail-lab">ACTIVITY</span></button>
    <button class="rail-btn" data-panel="digest" onclick="toggleIntel('digest')" title="Morning digest"><span class="rail-ico">☼</span><span class="rail-lab">DIGEST</span></button>
    <button class="rail-btn" data-panel="echo" onclick="toggleIntel('echo')" title="ECHO support"><span class="rail-ico">✉</span><span class="rail-lab">ECHO</span></button>
    <button class="rail-btn" data-panel="sage" onclick="toggleIntel('sage')" title="SAGE research"><span class="rail-ico">⌕</span><span class="rail-lab">SAGE</span></button>
  </nav>

  <!-- ══════════════════ INTELLIGENCE SLIDE PANEL ══════════════════ -->
  <div id="intelOverlay" onclick="closeIntel()"></div>
  <aside id="intelPanel" aria-hidden="true" aria-label="Intelligence panel">
    <div class="intel-head">
      <span id="rightPanelTitle" class="mono" style="font-size:11px;letter-spacing:.22em;color:#4fd1c5;">INTELLIGENCE</span>
      <button class="intel-close" onclick="closeIntel()" title="Close (Esc)">✕ CLOSE</button>
    </div>
    <div class="intel-body">

      <!-- KPIs -->
      <div class="intel-sec" id="panel-kpi">
        <div id="kpiCards" style="display:grid;grid-template-columns:repeat(2,1fr);gap:12px;"></div>
      </div>

      <!-- Approvals -->
      <div class="intel-sec" id="panel-approvals">
        <section class="card" style="padding:18px 20px;">
          <div class="card-scan"></div>
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;">
            <span class="mono" style="font-size:10px;letter-spacing:.22em;color:#4fd1c5;">PENDING APPROVALS</span>
            <div style="display:flex;align-items:center;gap:8px;">
              <span id="approvalCount" class="badge">0</span>
              <span class="collapse-btn" id="btn-sec-approvals" onclick="toggleSection('sec-approvals');event.stopPropagation()">▾</span>
            </div>
          </div>
          <div id="sec-approvals" class="section-body">
            <div id="approvalsList" style="display:flex;flex-direction:column;gap:10px;"></div>
          </div>
        </section>
      </div>

      <!-- Agent activity -->
      <div class="intel-sec" id="panel-activity">
        <section class="card" style="padding:18px 20px;">
          <div class="card-scan"></div>
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;">
            <span class="mono" style="font-size:10px;letter-spacing:.22em;color:#4fd1c5;">AGENT ACTIVITY · TODAY</span>
            <span class="mono" style="font-size:9px;letter-spacing:.16em;color:#5fd39a;">● LIVE</span>
          </div>
          <div id="activityFeed" style="display:flex;flex-direction:column;gap:6px;"></div>
        </section>
      </div>

      <!-- Morning digest -->
      <div class="intel-sec" id="panel-digest">
        <section class="card" style="padding:18px 20px;">
          <div class="card-scan"></div>
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;gap:8px;">
            <span class="mono" style="font-size:10px;letter-spacing:.22em;color:#4fd1c5;">MORNING DIGEST</span>
            <div style="display:flex;align-items:center;gap:8px;">
              <button onclick="playDigestAudio()" style="cursor:pointer;font-family:'IBM Plex Mono',monospace;font-size:9px;letter-spacing:.16em;padding:5px 12px;background:rgba(79,209,197,.12);border:1px solid rgba(79,209,197,.35);border-radius:2px;color:#4fd1c5;">▶ PLAY</button>
              <button onclick="generateDigest()" style="cursor:pointer;font-family:'IBM Plex Mono',monospace;font-size:9px;letter-spacing:.16em;padding:5px 12px;background:rgba(240,180,88,.1);border:1px solid rgba(240,180,88,.3);border-radius:2px;color:#f0b458;">↻ REFRESH</button>
              <span class="collapse-btn" id="btn-sec-digest" onclick="toggleSection('sec-digest');event.stopPropagation()">▾</span>
            </div>
          </div>
          <div id="sec-digest" class="section-body">
            <div id="digestText" class="mono" style="font-size:10px;line-height:1.7;color:#8a9ba8;white-space:pre-wrap;">Loading digest...</div>
          </div>
        </section>
      </div>

      <!-- ECHO support -->
      <div class="intel-sec" id="panel-echo">
        <section class="card" style="padding:18px 20px;">
          <div class="card-scan"></div>
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;">
            <span class="mono" style="font-size:10px;letter-spacing:.22em;color:#4fd1c5;">ECHO SUPPORT</span>
            <span class="mono" style="font-size:9px;letter-spacing:.16em;color:#5fd39a;">LOCAL · FREE</span>
          </div>
          <div id="supportTickets" style="font-family:'IBM Plex Mono',monospace;font-size:10px;color:#5b6b78;line-height:1.8;">No active tickets</div>
          <div style="margin-top:12px;display:flex;gap:8px;">
            <input id="supportInput" type="text" placeholder="Ask ECHO a support question..." onkeydown="if(event.key==='Enter')askEcho()" style="flex:1;min-width:0;padding:8px 12px;font-family:'IBM Plex Mono',monospace;font-size:10px;color:#dbe6ee;background:rgba(13,17,23,.85);border:1px solid rgba(79,209,197,.2);border-radius:2px;outline:none;">
            <button onclick="askEcho()" style="cursor:pointer;font-family:'IBM Plex Mono',monospace;font-size:9px;letter-spacing:.14em;padding:8px 12px;background:rgba(79,209,197,.12);border:1px solid rgba(79,209,197,.3);border-radius:2px;color:#4fd1c5;">ASK</button>
          </div>
        </section>
      </div>

      <!-- SAGE research -->
      <div class="intel-sec" id="panel-sage">
        <section class="card" style="padding:18px 20px 20px;">
          <div class="card-scan"></div>
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;gap:8px;">
            <span class="mono" style="font-size:10px;letter-spacing:.22em;color:#4fd1c5;">SAGE RESEARCH PULSE</span>
            <div style="display:flex;align-items:center;gap:8px;">
              <button onclick="runSageResearch()" style="cursor:pointer;font-family:'IBM Plex Mono',monospace;font-size:9px;letter-spacing:.16em;padding:5px 13px;background:rgba(79,209,197,.1);border:1px solid rgba(79,209,197,.3);border-radius:2px;color:#4fd1c5;">+ NEW RESEARCH</button>
              <span class="collapse-btn" id="btn-sec-sage" onclick="toggleSection('sec-sage');event.stopPropagation()">▾</span>
            </div>
          </div>
          <div id="sec-sage" class="section-body">
            <div id="researchCards" style="display:grid;grid-template-columns:1fr;gap:14px;"></div>
          </div>
        </section>
      </div>

    </div>
  </aside>

  <!-- STATUS BAR -->"""
must(html.count('  <!-- STATUS BAR -->') == 1, "status bar comment not unique")
html = html.replace('  <!-- STATUS BAR -->', MARKUP, 1)

# ── 5. JS ───────────────────────────────────────────────────────────────────
JS = """
  // ── INTELLIGENCE SLIDE PANEL ──────────────────────────
  const INTEL_TITLES = { kpi:"KPIs", approvals:"Approvals", activity:"Agent Activity",
                         digest:"Morning Digest", echo:"ECHO Support", sage:"SAGE Research" };
  let intelCurrent = null;

  function openIntel(key) {
    if (!INTEL_TITLES[key]) return;
    intelCurrent = key;
    document.querySelectorAll('#intelPanel .intel-sec').forEach(el =>
      el.classList.toggle('active', el.id === 'panel-' + key));
    document.querySelectorAll('#intelRail .rail-btn').forEach(b =>
      b.classList.toggle('active', b.dataset.panel === key));
    document.getElementById('rightPanelTitle').textContent = INTEL_TITLES[key];
    const p = document.getElementById('intelPanel');
    p.classList.add('open');
    p.setAttribute('aria-hidden', 'false');
    document.getElementById('intelOverlay').style.display = 'block';
    if (key === 'digest') { try { loadDigest(); } catch (e) {} }
    if (key === 'sage')   { try { renderResearch(); } catch (e) {} }
  }

  function closeIntel() {
    intelCurrent = null;
    const p = document.getElementById('intelPanel');
    p.classList.remove('open');
    p.setAttribute('aria-hidden', 'true');
    document.getElementById('intelOverlay').style.display = 'none';
    document.querySelectorAll('#intelRail .rail-btn').forEach(b => b.classList.remove('active'));
  }

  function toggleIntel(key) { (intelCurrent === key) ? closeIntel() : openIntel(key); }

  function updateRailBadges() {
    const rb = document.getElementById('railBadgeApprovals');
    if (!rb) return;
    const n = (state.approvals || []).length;
    rb.textContent = n;
    rb.style.display = n > 0 ? 'block' : 'none';
  }

  document.addEventListener('keydown', e => { if (e.key === 'Escape' && intelCurrent) closeIntel(); });

</script>"""
must(html.count('\n</script>') == 1, "</script> not unique")
html = html.replace('\n</script>', JS, 1)

# badge refresh hooked into renderApprovals
old_ra = '  const count = document.getElementById("approvalCount");\n  count.textContent = state.approvals.length;'
must(old_ra in html, "renderApprovals anchor not found")
html = html.replace(old_ra, old_ra + '\n  updateRailBadges();', 1)

P.write_text(html)
print("OK: %d -> %d bytes" % (len(orig), len(html)))
