#!/usr/bin/env python3
"""
Put a Mermaid renderer where the PDF engine can reach it, offline.

    python3 scripts/vendor_mermaid.py            check
    python3 scripts/vendor_mermaid.py --apply    fetch and verify it

── WHY VENDOR RATHER THAN LINK A CDN ────────────────────────────────────────

The PDF engine renders HTML in Chromium via Playwright, so Mermaid needs no new
renderer — only the library and a wait. The obvious version is a <script src>
pointing at a CDN.

The failure mode of that is the one this week has been about: no network at
render time, the script silently does not load, mermaid.run() is never defined,
and the PDF comes out with the diagram as a code block. It looks exactly like a
document nobody asked for a diagram in. Vendored, it either works or the file is
missing and this says so.

3.3 MB, pinned, inlined only into documents that actually contain a diagram.

── VERIFICATION ─────────────────────────────────────────────────────────────

Not "the file downloaded". This launches Chromium, renders a real flowchart
with the vendored copy, and confirms an <svg> appeared. A 3 MB file that
parses and cannot draw is worth nothing.
"""
import argparse
import asyncio
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

VERSION = "10.9.1"
DEST = Path("/Users/ducorn/DC/ducorn-products/products/ducorn-pdf-export-tool"
            "/app/static/mermaid.min.js")
CDN = f"https://cdnjs.cloudflare.com/ajax/libs/mermaid/{VERSION}/mermaid.min.js"
VENV_PY = "/Users/ducorn/DC/ducorn/.venv/bin/python"

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true", help="fetch it")
args = ap.parse_args()

# Verification needs playwright, which lives in the pipeline venv. Re-exec HERE,
# before fetching — doing it after the download meant the 3.3 MB was fetched
# twice, once under each interpreter.
if args.apply:
    try:
        import playwright  # noqa: F401
    except ImportError:
        if Path(VENV_PY).exists():
            sys.exit(subprocess.call([VENV_PY, str(Path(__file__).resolve())]
                                     + sys.argv[1:]))
        sys.exit("playwright is not importable and the pipeline venv is "
                 "missing — cannot verify a vendored copy renders.")


def fetch_cdn(dest):
    import urllib.request
    req = urllib.request.Request(CDN, headers={"User-Agent": "ducorn-vendor"})
    with urllib.request.urlopen(req, timeout=60) as r:
        dest.write_bytes(r.read())
    return "cdnjs"


def fetch_npm(dest):
    """npm pack, for when the CDN is unreachable. Same artifact, same pin."""
    if not shutil.which("npm"):
        raise RuntimeError("npm is not installed")
    tmp = Path(tempfile.mkdtemp())
    r = subprocess.run(["npm", "pack", f"mermaid@{VERSION}", "--silent"],
                       cwd=tmp, capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        raise RuntimeError(f"npm pack failed: {r.stderr[-200:]}")
    tgz = next(tmp.glob("mermaid-*.tgz"))
    subprocess.run(["tar", "xzf", tgz.name], cwd=tmp, check=True, timeout=120)
    src = tmp / "package/dist/mermaid.min.js"
    if not src.is_file():
        raise RuntimeError("mermaid.min.js is not in the package")
    dest.write_bytes(src.read_bytes())
    return f"npm pack mermaid@{VERSION}"


async def renders(js_path):
    """Can this copy actually draw a diagram? The only question that matters."""
    from playwright.async_api import async_playwright
    doc = ("<!DOCTYPE html><html><head><meta charset='utf-8'></head><body>"
           '<pre class="mermaid">graph LR\n  a --&gt; b\n</pre>'
           "<script>" + js_path.read_text(errors="replace") + "</script>"
           "<script>window.__r=false;"
           "mermaid.initialize({startOnLoad:false});"
           "mermaid.run().then(()=>{window.__r=true;})"
           ".catch(e=>{window.__err=String(e);window.__r=true;});</script>"
           "</body></html>").replace("--&gt;", "-->")
    async with async_playwright() as pw:
        b = await pw.chromium.launch(args=["--no-sandbox", "--disable-gpu"])
        pg = await b.new_page()
        await pg.set_content(doc, wait_until="load")
        try:
            await pg.wait_for_function("window.__r === true", timeout=25000)
        except Exception:
            await b.close()
            return False, "mermaid never finished"
        err = await pg.evaluate("window.__err || ''")
        svgs = await pg.eval_on_selector_all(".mermaid svg", "e => e.length")
        await b.close()
        return svgs > 0, err or ("no svg produced" if not svgs else "")


if DEST.is_file():
    mb = DEST.stat().st_size / 1e6
    print(f"already vendored: {DEST}  ({mb:.1f} MB)")
    if not args.apply:
        print("re-run with --apply to refetch and re-verify.")
        sys.exit(0)
elif not args.apply:
    print(f"not vendored. Would fetch mermaid {VERSION} to:\n  {DEST}")
    print("\nRe-run with --apply.")
    sys.exit(1)

DEST.parent.mkdir(parents=True, exist_ok=True)
tmp_dest = DEST.with_suffix(".tmp")
how = None
errors = []
for fetch in (fetch_cdn, fetch_npm):
    try:
        how = fetch(tmp_dest)
        break
    except Exception as e:
        errors.append(f"{fetch.__name__}: {type(e).__name__}: {e}")
if how is None:
    tmp_dest.unlink(missing_ok=True)
    sys.exit("could not fetch mermaid:\n  " + "\n  ".join(errors))

size = tmp_dest.stat().st_size
print(f"fetched via {how} — {size/1e6:.1f} MB")
if size < 500_000:
    tmp_dest.unlink()
    sys.exit(f"only {size:,} bytes — that is not the full library. Nothing written.")
if "mermaid" not in tmp_dest.read_text(errors="replace")[:2000]:
    tmp_dest.unlink()
    sys.exit("the file does not look like mermaid. Nothing written.")

# The real check. A library that parses and cannot draw is worth nothing.
print("rendering a test diagram with it (launches Chromium)…")
ok, why = asyncio.run(renders(tmp_dest))

if not ok:
    tmp_dest.unlink()
    sys.exit(f"the vendored copy did not render: {why}. Nothing written.")

tmp_dest.replace(DEST)
print(f"  ok   it drew an svg")
print(f"\nvendored: {DEST}")
print(f"          mermaid {VERSION}, {size/1e6:.1f} MB, verified by rendering")
print("\nNow teach the PDF engine to use it:")
print("  python3 scripts/patch_pdf_mermaid.py")
