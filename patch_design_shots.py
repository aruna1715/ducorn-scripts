#!/usr/bin/env python3
"""
Show the three designs at the gate instead of linking to them.

── WHAT GATE 2 LOOKS LIKE NOW ───────────────────────────────────────────────

    🎨 ATLAS Gate 2 — 3 UI Designs Ready
    *Corn Ledger* — editorial, balanced
        <open the design>
        ✅ @DuCorn approve 337
    *Ledger* — swiss, conservative
        <open the design>
        ✅ @DuCorn approve 338
    ...

Three links. To choose, you open three tabs, and on a phone you mostly do not
bother — which makes the one decision in the pipeline that is purely visual the
one you make without looking. Now that there is a browser on this machine,
there is no reason for that.

── WHAT IT LOOKS LIKE AFTER ─────────────────────────────────────────────────

The same message, followed by the three designs as images in the thread, each
captioned with its name, archetype and approve command. The links stay: an
image is for choosing, the page is for checking.

── THE TRAP I ALMOST SHIPPED ────────────────────────────────────────────────

The first version screenshotted the HTML file directly. Here is what came out
of the approved Corn Ledger design:

    Every cent your agents spent, right now.
    ⚠ Could not load data
      Failed to fetch

A design variant is a live page: it fetches its data from the API. Opened as
file://, that fetch is a cross-origin request from a null origin and it fails,
so the screenshot is the empty error state — three pictures of nothing, which
is worse than three links because it looks like the designs are broken.

The reason you saw these designs working is that you opened them through
/d/<token>, served BY the API, where the fetch is same-origin. So that is what
gets screenshotted: the served URL, over localhost rather than the tunnel.

I only caught this by looking at the PNG.

── HOW ──────────────────────────────────────────────────────────────────────

tools/screenshot.py renders a variant with Playwright — 1440 wide, retina
scale, full page — and writes the PNG beside the HTML inside the product's
jail. A page taller than 2400px is clipped there, because Slack squeezes a very
tall image into an unreadable sliver and the top of a page is what you actually
compare; the caption says it was clipped and the link is still in the message.

design_variants gains a shot_path column (migration 004), so the gate reads
what to upload from the same row it reads the token from.

── WHEN A SCREENSHOT FAILS ──────────────────────────────────────────────────

The gate still posts, still links, and says in the message that the images are
missing and why. That is a deliberate non-fatal exception to how I have treated
silent fallbacks all evening, and the reason is that the failure is visible in
the place the decision is made: a founder who sees "screenshots unavailable —
<reason>" knows to open the links. Blocking an approved design run because a
picture did not render would be the worse trade.
"""
import ast
import shutil
import sys
from datetime import datetime
from pathlib import Path

DUCORN = Path("/Users/ducorn/DC/ducorn")
FLOW = DUCORN / "flows/langgraph_flow.py"
SHOT = DUCORN / "tools/screenshot.py"
MIG = Path("/Users/ducorn/DC/scripts/migrations/004_design_shots.sql")
TEST = Path("/Users/ducorn/DC/scripts/test_screenshot.py")

f = FLOW.read_text(encoding="utf-8")
if "shot_path" in f:
    sys.exit("Already patched — gate 2 uploads screenshots.")


def swap(label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {text.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    return text.replace(old, new, 1)


# ── 1. the renderer ──────────────────────────────────────────────────────────
SHOT.write_text('''"""
Render a design variant to a PNG, so a gate can show it rather than link it.

Deliberately standalone: no database, no Slack, no pipeline imports. It takes a
path to an HTML file and gives back a path to an image, which makes it testable
on its own and reusable by anything else that wants a picture of a page.
"""
from pathlib import Path

WIDTH = 1440
HEIGHT = 900
SCALE = 2                # retina; a 1x shot of a design reads as a bad design
MAX_FULL_PAGE_PX = 2400  # past this, clip — see the note in shoot()


class ShotError(RuntimeError):
    pass


# Text that means the page rendered its failure state rather than its content.
# A design that cannot load its data still screenshots perfectly well, and the
# picture is then a picture of an error — which is the one outcome worse than
# posting a link.
_BROKEN = ("could not load", "failed to fetch", "error loading",
           "something went wrong", "unable to load")


def shoot(target, out_path=None, width=WIDTH, height=HEIGHT,
          scale=SCALE, max_px=MAX_FULL_PAGE_PX, timeout_ms=20000):
    """
    Screenshot a page. Returns (png_path, note).

    `target` is a local HTML file or an http(s) URL. Prefer the URL for
    anything that loads data: opened as file://, a page's fetch is
    cross-origin from a null origin and fails, so the screenshot is the
    page's error state.

    note is "" when all is well, or a sentence for a person to read — that the
    page was clipped, or that it appears to be showing an error.
    """
    is_url = str(target).startswith(("http://", "https://"))

    if is_url:
        if not out_path:
            raise ShotError("out_path is required when shooting a URL")
        out = Path(out_path)
        url = str(target)
    else:
        html_path = Path(target)
        if not html_path.is_file():
            raise ShotError(f"no such file: {html_path}")
        out = Path(out_path) if out_path else html_path.with_suffix(".png")
        url = html_path.as_uri()
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise ShotError(
            "playwright is not installed in this interpreter — run "
            "scripts/install_playwright.py --apply") from e

    note = ""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(
                viewport={"width": width, "height": height},
                device_scale_factor=scale)
            # networkidle, not load: these pages fetch their data after load,
            # and a shot taken at `load` catches the empty skeleton.
            try:
                page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            except Exception:
                page.goto(url, wait_until="load", timeout=timeout_ms)
            # Webfonts and any entry animation. A design shot mid-fade looks
            # like a broken design.
            page.wait_for_timeout(600)
            try:
                page.wait_for_function("document.fonts.ready.then(() => true)",
                                       timeout=3000)
            except Exception:
                pass          # not every page uses webfonts; not worth failing

            full_h = page.evaluate(
                "Math.max(document.body.scrollHeight, "
                "document.documentElement.scrollHeight)") or height
            if full_h > max_px:
                # full_page must be set even WITH a clip: a clip taller than
                # the viewport is silently truncated to the viewport without
                # it, which produced a 900px "clip" of a 12000px page and
                # looked exactly like a working screenshot. The test caught it.
                #
                # 2400px is roughly the hero plus the first section. Past that
                # a design does not compare well in Slack anyway — the preview
                # squeezes a very tall image into a sliver — and the link is
                # right there for the rest.
                note = (f"clipped to the top {max_px}px of {int(full_h)}px — "
                        f"open the link for the rest")
                page.screenshot(path=str(out), full_page=True,
                                clip={"x": 0, "y": 0,
                                      "width": width, "height": max_px})
            else:
                page.screenshot(path=str(out), full_page=True)

            try:
                body = (page.inner_text("body") or "").lower()
            except Exception:
                body = ""
            hit = next((w for w in _BROKEN if w in body), None)
            if hit:
                broke = f"the page is showing an error state ({hit!r})"
                note = f"{note}; {broke}" if note else broke
        finally:
            browser.close()

    if not out.is_file() or out.stat().st_size == 0:
        raise ShotError(f"screenshot produced nothing at {out}")
    return out, note


def shoot_all(items, **kw):
    """
    Screenshot several pages. Returns (shots, failures).

    items:    a path, or a (target, out_path) pair — mix as you like.
    shots:    [{"target": str, "png": Path, "note": str}]
    failures: [{"target": str, "error": str}]

    One variant failing does not stop the others — three designs with two
    pictures is better than three designs with none.
    """
    shots, failures = [], []
    for item in items:
        target, out = item if isinstance(item, (tuple, list)) else (item, None)
        try:
            png, note = shoot(target, out, **kw)
            shots.append({"target": str(target), "png": png, "note": note})
        except Exception as e:
            failures.append({"target": str(target),
                             "error": f"{type(e).__name__}: {e}"})
    return shots, failures
''', encoding="utf-8")

# ── 2. the migration ─────────────────────────────────────────────────────────
MIG.write_text('''-- 004: where the picture of each design variant lives.
--
-- Gate 2 used to post three links. Opening three tabs to make a purely visual
-- decision is enough friction that the decision gets made without looking, so
-- the gate now uploads the images and the row records which file to upload.
--
-- Nullable on purpose: a variant whose screenshot failed is still a variant,
-- and the gate says so rather than refusing to post.

ALTER TABLE design_variants
    ADD COLUMN IF NOT EXISTS shot_path text;
''', encoding="utf-8")

# ── 3. slack image upload ────────────────────────────────────────────────────
f = swap("slack images", f, '''def _request_approval(title: str, description: str,''',
         '''def _post_slack_images(uploads, comment=""):
    """
    Post images to the board. uploads: [{"file": path, "title": str}].

    Returns "" on success or a one-line reason. The caller decides what to do
    with a failure; at gate 2 it goes into the message the founder reads, so a
    missing picture is visible where the decision is made rather than only in a
    log nobody opens.
    """
    if not uploads:
        return "no images to post"
    try:
        from slack_sdk import WebClient
        client = WebClient(token=os.environ.get("SLACK_BOT_TOKEN", ""))
        client.files_upload_v2(
            channel="#duc-board",
            initial_comment=comment,
            file_uploads=[{"file": str(u["file"]), "title": u["title"]}
                          for u in uploads],
        )
        return ""
    except Exception as e:
        # files:write is a separate scope from chat:write. If this is the
        # first upload the app has ever attempted, that is the likely cause.
        print(f"Slack image upload failed: {type(e).__name__}: {e}")
        return f"{type(e).__name__}: {str(e)[:160]}"


def _request_approval(title: str, description: str,''')

# ── 4. node_design takes the pictures ────────────────────────────────────────
f = swap("shoot", f, '''        registered = _register_variants(topic, rendered)
        paths = [v["path"] for v in registered]''',
         '''        registered = _register_variants(topic, rendered)
        paths = [v["path"] for v in registered]

        # A picture per variant, written beside its HTML inside the jail.
        # Non-fatal by design: three designs with two pictures still beats
        # three links, and gate 2 reports what is missing.
        try:
            from tools.screenshot import shoot_all

            # Through the API, not off disk. A variant fetches its data, and
            # from file:// that fetch is cross-origin from a null origin and
            # fails — the screenshot then shows the page's error state. The
            # /d/<token> route serves it same-origin, which is why these
            # designs look right when you open the link. localhost rather
            # than the public base: same page, no tunnel in the way.
            _api = os.environ.get("DUCORN_LOCAL_API", "http://localhost:8000")
            jobs, out_for = [], {}
            for r in registered:
                out = str(Path(r["path"]).with_suffix(".png"))
                jobs.append((f"{_api}/d/{r['token']}", out))
                out_for[out] = r["path"]

            shots, shot_failures = shoot_all(jobs)
            for sh in shots:
                print(f"   📸 {Path(sh['png']).name}"
                      + (f"  ({sh['note']})" if sh["note"] else ""))
            for bad in shot_failures:
                print(f"   ⚠️  no screenshot: {bad['target']} — {bad['error']}")
            _record_shots(topic, [(out_for[str(sh["png"])], str(sh["png"]))
                                  for sh in shots
                                  if str(sh["png"]) in out_for])
        except Exception as e:
            print(f"⚠️  screenshots unavailable: {type(e).__name__}: {e}")''')

f = swap("record helper", f, '''def node_design(state: DuCornState) -> DuCornState:''',
         '''def _record_shots(topic, pairs):
    """pairs: [(variant html path, png path)] — store the picture per row."""
    if not pairs:
        return
    try:
        from ducorn_db import get_conn
        with get_conn() as conn:
            cur = conn.cursor()
            for html_path, png_path in pairs:
                cur.execute("UPDATE design_variants SET shot_path=%s "
                            "WHERE slug=%s AND path=%s",
                            (png_path, topic, html_path))
    except Exception as e:
        print(f"⚠️  could not record screenshot paths: {e}")


def node_design(state: DuCornState) -> DuCornState:''')

# ── 5. gate 2 posts them ─────────────────────────────────────────────────────
f = swap("gate select", f, '''            cur.execute("SELECT id, variant_name, archetype, register, path, "
                        "view_token FROM design_variants WHERE slug=%s "
                        "ORDER BY id", (topic,))''',
         '''            cur.execute("SELECT id, variant_name, archetype, register, path, "
                        "view_token, shot_path FROM design_variants "
                        "WHERE slug=%s ORDER BY id", (topic,))''')

f = swap("gate loop", f, '''        lines, ids = [], []
        for vid, name, archetype, register, path, token in rows:''',
         '''        lines, ids, uploads = [], [], []
        for vid, name, archetype, register, path, token, shot in rows:''')

f = swap("gate collect", f, '''            lines.append(
                f"*{name}* — {archetype}, {register or 'balanced'}\\n"
                f"    <{DESIGN_LINK_BASE}/d/{token}|open the design>\\n"
                f"    ✅ `@DuCorn approve {approval_id}`")''',
         '''            lines.append(
                f"*{name}* — {archetype}, {register or 'balanced'}\\n"
                f"    <{DESIGN_LINK_BASE}/d/{token}|open the design>\\n"
                f"    ✅ `@DuCorn approve {approval_id}`")
            if shot and Path(shot).is_file():
                uploads.append({"file": shot,
                                "title": f"{name} — {archetype} — "
                                         f"approve {approval_id}"})''')

f = swap("gate post", f, '''        approval_id = ids[0]   # state keeps one for the existing plumbing
        _post_slack(
            f"🎨 *ATLAS Gate 2 — {len(rows)} UI Designs Ready*\\n\\n"
            f"*Product:* `{topic}`\\n"
            f"*Model:* `{state.get('design_model', '?')}`\\n\\n"
            + "\\n\\n".join(lines) +
            f"\\n\\nApprove ONE — the others are set aside and the build "
            f"implements the one you pick.\\n"
            f"❌ Reject all: `@DuCorn reject {approval_id}`"
        )''',
         '''        approval_id = ids[0]   # state keeps one for the existing plumbing

        # Images first, then the message, so the pictures are above the
        # commands rather than trailing them.
        shot_problem = ""
        if uploads:
            shot_problem = _post_slack_images(
                uploads,
                f"🎨 *{topic}* — {len(uploads)} UI direction"
                f"{'s' if len(uploads) != 1 else ''} to choose from")
        elif len(rows):
            shot_problem = "no screenshots were taken"

        missing = len(rows) - len(uploads)
        note = ""
        if shot_problem:
            note = (f"\\n\\n⚠️  Designs shown as links only "
                    f"({shot_problem}) — open each one to compare.")
        elif missing:
            note = (f"\\n\\n⚠️  {missing} of {len(rows)} designs could not be "
                    f"screenshotted — open those links to see them.")

        _post_slack(
            f"🎨 *ATLAS Gate 2 — {len(rows)} UI Designs Ready*\\n\\n"
            f"*Product:* `{topic}`\\n"
            f"*Model:* `{state.get('design_model', '?')}`\\n\\n"
            + "\\n\\n".join(lines) +
            f"\\n\\nApprove ONE — the others are set aside and the build "
            f"implements the one you pick.\\n"
            f"❌ Reject all: `@DuCorn reject {approval_id}`"
            + note
        )''')

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = FLOW.with_name(f"langgraph_flow.backup-shots-{stamp}.py")
shutil.copy2(FLOW, backup)
FLOW.write_text(f, encoding="utf-8")

for path in (FLOW, SHOT):
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        shutil.copy2(backup, FLOW)
        sys.exit(f"SYNTAX ERROR in {path.name} ({e}) — flow reverted from {backup}")

# ── 6. a test that renders a real page ───────────────────────────────────────
TEST.write_text('''#!/usr/bin/env python3
"""
The screenshot tool, exercised against a real browser.

    cd ~/DC/ducorn && .venv/bin/python ../scripts/test_screenshot.py

No mocks. If this passes, gate 2 can show you a design.
"""
import contextlib
import http.server
import socketserver
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, "/Users/ducorn/DC/ducorn")

from tools.screenshot import shoot, shoot_all, ShotError, MAX_FULL_PAGE_PX  # noqa

passed, failed = [], []


def test(name):
    def deco(fn):
        try:
            fn()
            print(f"  ok   {name}")
            passed.append(name)
        except AssertionError as e:
            print(f"  FAIL {name}\\n         {e}")
            failed.append(name)
        except Exception as e:
            print(f"  FAIL {name}\\n         {type(e).__name__}: {e}")
            failed.append(name)
        return fn
    return deco


def png_size(path):
    """Width and height from the PNG header — no image library needed."""
    data = Path(path).read_bytes()[:24]
    assert data[:8] == b"\\x89PNG\\r\\n\\x1a\\n", "not a PNG"
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


SHORT = "<html><body style='margin:0;background:#123456;height:400px'>" \\
        "<h1 id='t' style='color:#fff'>Design A</h1></body></html>"

# A page that gets its content the way a real variant does.
FETCHER = """<html><body><h1>Spend</h1><div id="out">loading</div>
<script>
fetch('data.json').then(r => r.json())
  .then(d => document.getElementById('out').textContent = 'total ' + d.v)
  .catch(e => document.getElementById('out').textContent = 'Could not load data');
</script></body></html>"""


@contextlib.contextmanager
def _serve(files):
    """Serve a dict of {name: text} over http on a free port."""
    root = Path(tempfile.mkdtemp(prefix="ducorn-serve-"))
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(root), **kw)

        def log_message(self, *a):
            pass

    httpd = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
TALL = "<html><body style='margin:0;background:#eee;height:12000px'>" \\
       "<h1>Long page</h1></body></html>"

tmp = Path(tempfile.mkdtemp(prefix="ducorn-shot-"))

print("\\n── it renders ──────────────────────────────────────────────────────")


@test("a page becomes a PNG beside it")
def _():
    html = tmp / "a.html"
    html.write_text(SHORT, encoding="utf-8")
    png, note = shoot(html)
    assert png == html.with_suffix(".png"), f"unexpected path {png}"
    assert png.stat().st_size > 1000, f"suspiciously small: {png.stat().st_size}"
    assert note == "", f"unexpected note: {note!r}"


@test("the shot is retina width, not css width")
def _():
    html = tmp / "b.html"
    html.write_text(SHORT, encoding="utf-8")
    png, _n = shoot(html)
    w, h = png_size(png)
    assert w == 1440 * 2, f"width {w}, expected 2880 — is device_scale_factor set?"


@test("a very tall page is clipped, and says so")
def _():
    html = tmp / "tall.html"
    html.write_text(TALL, encoding="utf-8")
    png, note = shoot(html)
    w, h = png_size(png)
    assert h == MAX_FULL_PAGE_PX * 2, (
        f"height {h}, expected {MAX_FULL_PAGE_PX * 2} — a 12000px page should "
        f"be clipped, not uploaded whole")
    assert "clipped" in note, f"the clip is not reported: {note!r}"


print("\\n── it shoots a SERVED page, which is the case that matters ────────")


@test("an http URL is screenshotted, not just a file")
def _():
    # A design fetches its data. From file:// that fetch is cross-origin from
    # a null origin and fails, so the picture is the page's error state — the
    # first version of this shipped exactly that. Gate 2 shoots /d/<token>.
    with _serve({"index.html": SHORT}) as base:
        out = tmp / "served.png"
        png, note = shoot(f"{base}/index.html", out)
        assert png == out and png.stat().st_size > 1000, "nothing served"
        assert "error state" not in note, note


@test("a page whose fetch fails is reported, not posted as a design")
def _():
    with _serve({"index.html": FETCHER}) as base:      # no data.json served
        png, note = shoot(f"{base}/index.html", tmp / "broken.png")
        assert "error state" in note, (
            f"a page rendering 'Could not load data' was treated as fine: "
            f"{note!r}")


@test("a page whose fetch succeeds gets a clean note")
def _():
    with _serve({"index.html": FETCHER, "data.json": '{"v":"42"}'}) as base:
        png, note = shoot(f"{base}/index.html", tmp / "fetched.png")
        assert note == "", f"unexpected note: {note!r}"


print("\\n── it fails usefully ───────────────────────────────────────────────")


@test("a missing file raises rather than writing an empty PNG")
def _():
    try:
        shoot(tmp / "nope.html")
    except ShotError as e:
        assert "no such file" in str(e), str(e)
        return
    raise AssertionError("no error for a missing file")


@test("one bad variant does not stop the others")
def _():
    good = tmp / "good.html"
    good.write_text(SHORT, encoding="utf-8")
    shots, failures = shoot_all([good, tmp / "missing.html"])
    assert len(shots) == 1, f"{len(shots)} shots, expected 1"
    assert len(failures) == 1, f"{len(failures)} failures, expected 1"
    assert "missing.html" in failures[0]["target"]


print()
print(f"{len(passed)} passed, {len(failed)} failed")
if failed:
    print("FAILED: " + ", ".join(failed))
    sys.exit(1)
print(f"gate 2 can show a design  (samples in {tmp})")
''', encoding="utf-8")

print("applied: screenshots at gate 2")
print(f"created: {SHOT}")
print(f"         {MIG}")
print(f"         {TEST}")
print(f"backup:  {backup.name}")
print()
print("In order:")
print("  python3 scripts/migrate.py           # bare = apply pending")
print("  cd ~/DC/ducorn && .venv/bin/python ../scripts/test_screenshot.py")
print()
print("The Slack app needs the files:write scope. If it does not have it the")
print("gate still posts and says the images are missing — it will not fail.")
