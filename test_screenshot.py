#!/usr/bin/env python3
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
            print(f"  FAIL {name}\n         {e}")
            failed.append(name)
        except Exception as e:
            print(f"  FAIL {name}\n         {type(e).__name__}: {e}")
            failed.append(name)
        return fn
    return deco


def png_size(path):
    """Width and height from the PNG header — no image library needed."""
    data = Path(path).read_bytes()[:24]
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


SHORT = "<html><body style='margin:0;background:#123456;height:400px'>" \
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
TALL = "<html><body style='margin:0;background:#eee;height:12000px'>" \
       "<h1>Long page</h1></body></html>"

tmp = Path(tempfile.mkdtemp(prefix="ducorn-shot-"))

print("\n── it renders ──────────────────────────────────────────────────────")


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


print("\n── it shoots a SERVED page, which is the case that matters ────────")


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


print("\n── it fails usefully ───────────────────────────────────────────────")


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
