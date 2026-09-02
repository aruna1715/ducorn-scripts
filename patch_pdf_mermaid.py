#!/usr/bin/env python3
"""
Make diagrams render in the PDF, not appear as code.

── THE SITUATION IS BETTER THAN IT LOOKED ───────────────────────────────────

The tech-stack brief asks for an architecture diagram and a flow diagram. My
first reading was that the PDF path could not do it. It can: pdf_engine renders
HTML in Chromium through Playwright and prints the page. A browser is already
there. What is missing is the Mermaid library and a wait — not a renderer.

── WHAT THIS CHANGES ────────────────────────────────────────────────────────

1. _markdown_to_html turns a ```mermaid fence into <pre class="mermaid">. The
   markdown extension emits <pre><code class="language-mermaid"> with the
   arrows HTML-escaped, so `-->` arrives as `--&gt;` and must be unescaped or
   Mermaid sees a syntax error.

2. The vendored library and an init call are appended AT THE END OF THE BODY.
   Not the head. I tested it in the head first and got a clean pass with zero
   diagrams: mermaid.run() executed before the elements existed, found nothing
   to draw, and resolved successfully. A silent success is the failure mode
   this whole week has been about, and it caught me again here.

3. render_html waits for window.__mermaidReady before printing. Without the
   wait, Chromium prints a page whose diagrams have not been drawn yet — which
   is intermittent, which is the worst kind.

Only documents that contain a diagram get the 3.3 MB inlined. A document with
no fence is byte-identical to what it produces today.

── WHEN A DIAGRAM IS BROKEN ─────────────────────────────────────────────────

A Mermaid syntax error sets __mermaidReady anyway, so the PDF is still
produced with that diagram unrendered rather than the whole export hanging.
The error is logged. A document that is 90% right beats an export that times
out.

── VERIFIED ─────────────────────────────────────────────────────────────────

End to end, before this patch was written: markdown with a flowchart → HTML →
Chromium → PDF, then the PDF text extracted. "graph LR" does not appear as
text, the node labels do, the surrounding prose is still selectable, and the
page carries 25 vector drawing operations. It is a picture, not a code block.
"""
import ast
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PRODUCT = Path("/Users/ducorn/DC/ducorn-products/products/ducorn-pdf-export-tool")
ENGINE = PRODUCT / "app/services/pdf_engine.py"
MERMAID_JS = PRODUCT / "app/static/mermaid.min.js"

s = ENGINE.read_text(encoding="utf-8")

if "_mermaid_ready" in s:
    sys.exit("Already patched — diagrams render in the PDF.")
if not MERMAID_JS.is_file():
    sys.exit(f"{MERMAID_JS} is missing.\nRun: python3 scripts/vendor_mermaid.py "
             f"--apply\nNOTHING WRITTEN.")

applied = []


def swap(label, text, old, new):
    if text.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {text.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    applied.append(label)
    return text.replace(old, new, 1)


# ── 1. wrap the markdown converter rather than editing inside its f-string ───
s = swap("wrap converter", s,
         '''    def _markdown_to_html(self, markdown_content: str) -> str:''',
         '''    MERMAID_JS_PATH = ("/Users/ducorn/DC/ducorn-products/products/"
                       "ducorn-pdf-export-tool/app/static/mermaid.min.js")

    @staticmethod
    def _mermaid_ready(html: str) -> str:
        """
        Turn ```mermaid fences into things Mermaid can draw, and arrange for
        them to be drawn before the page is printed.

        The script goes at the END OF THE BODY. Placed in the head it runs
        before the diagram elements exist, finds nothing, and resolves happily
        — a clean pass with no diagrams, which is exactly the sort of silent
        success that is hard to notice and expensive to trust.
        """
        import html as _html
        import re as _re
        # pdf_engine has no module-level Path. Imported here rather than added
        # to the header: a module-level name this file does not already have is
        # how I took the activity API down earlier tonight.
        from pathlib import Path as _Path

        # fenced_code emits <pre><code class="language-mermaid"> with the
        # content escaped, so `-->` arrives as `--&gt;` and Mermaid rejects it.
        pattern = _re.compile(
            r\'<pre><code class="language-mermaid">(.*?)</code></pre>\', _re.S)
        html, count = pattern.subn(
            lambda m: \'<pre class="mermaid">\' + _html.unescape(m.group(1))
                      + "</pre>", html)
        if not count:
            return html          # no diagram: not one byte added

        try:
            lib = _Path(PDFEngine.MERMAID_JS_PATH).read_text(errors="replace")
        except OSError as e:
            logger.warning("mermaid is not vendored (%s) — diagrams will print "
                           "as code. Run scripts/vendor_mermaid.py --apply", e)
            return html

        boot = (
            "<script>" + lib + "</script>"
            "<script>window.__mermaidReady=false;"
            "try{mermaid.initialize({startOnLoad:false,theme:'neutral',"
            "flowchart:{useMaxWidth:true,htmlLabels:true}});"
            "mermaid.run().then(function(){window.__mermaidReady=true;})"
            ".catch(function(e){window.__mermaidError=String(e);"
            "window.__mermaidReady=true;});}"
            # A broken diagram must not hold the whole export hostage.
            "catch(e){window.__mermaidError=String(e);"
            "window.__mermaidReady=true;}</script>")
        logger.info("mermaid: %d diagram(s), inlining the renderer", count)
        # The LAST </body>, not the first. This document may itself contain
        # the literal "</body>" in a code sample — a tech-stack document
        # certainly can — and injecting the renderer there puts it before the
        # diagrams again, which is the silent-zero-diagrams bug wearing a hat.
        cut = html.rfind("</body>")
        return html[:cut] + boot + html[cut:] if cut != -1 else html + boot

    def _markdown_to_html(self, markdown_content: str) -> str:
        """Markdown to a styled HTML document, with diagrams made drawable."""
        return self._mermaid_ready(self._markdown_to_html_base(markdown_content))

    def _markdown_to_html_base(self, markdown_content: str) -> str:''')

# ── 2. do not print until the diagrams are drawn ─────────────────────────────
s = swap("wait before printing", s,
         '''            await page.set_content(html, wait_until="networkidle")''',
         '''            await page.set_content(html, wait_until="networkidle")

            # Chromium will happily print a page whose diagrams have not been
            # drawn yet, and it will do so intermittently, which is worse than
            # never. Only wait when there is something to wait for.
            if "window.__mermaidReady" in html:
                try:
                    await page.wait_for_function(
                        "window.__mermaidReady === true", timeout=30000)
                    err = await page.evaluate("window.__mermaidError || ''")
                    if err:
                        logger.warning("mermaid could not draw a diagram: %s",
                                       err[:200])
                    else:
                        drawn = await page.eval_on_selector_all(
                            ".mermaid svg", "e => e.length")
                        logger.info("mermaid: %d diagram(s) drawn", drawn)
                except Exception as e:
                    # Print anyway. A document with one unrendered diagram is
                    # worth more than an export that failed.
                    logger.warning("mermaid did not finish (%s) — printing "
                                   "without waiting further", e)''')

stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
backup = ENGINE.with_name(f"pdf_engine.backup-mermaid-{stamp}.py")
shutil.copy2(ENGINE, backup)
ENGINE.write_text(s, encoding="utf-8")


def die(msg):
    shutil.copy2(backup, ENGINE)
    sys.exit(f"{msg} — reverted from {backup.name}")


try:
    ast.parse(s)
except SyntaxError as e:
    die(f"SYNTAX ERROR ({e})")

r = subprocess.run([sys.executable, "-m", "pyflakes", str(ENGINE)],
                   capture_output=True, text=True)
undef = [l for l in (r.stdout + r.stderr).splitlines() if "undefined name" in l]
if undef:
    die("undefined name: " + "; ".join(undef))
print("syntax and undefined-name checks: clean")

# ── exercise the transform on real markdown ──────────────────────────────────
src = ENGINE.read_text(encoding="utf-8")
tree = ast.parse(src)
cls = next((n for n in ast.walk(tree)
            if isinstance(n, ast.ClassDef) and n.name == "PDFEngine"), None)
if cls is None:
    die("PDFEngine class not found after patching")
fn = next((n for n in cls.body if isinstance(n, ast.FunctionDef)
           and n.name == "_mermaid_ready"), None)
if fn is None:
    die("_mermaid_ready did not land")

seg = ast.get_source_segment(src, fn)
import textwrap
ns = {"logger": type("L", (), {
    "warning": lambda *a, **k: None, "info": lambda *a, **k: None})(),
    "PDFEngine": type("PDFEngine", (), {"MERMAID_JS_PATH": str(MERMAID_JS)})}
exec(textwrap.dedent(seg).replace("@staticmethod\n", ""), ns)
ready = ns["_mermaid_ready"]

WITH = ('<h1>x</h1><pre><code class="language-mermaid">graph LR\n'
        '  research --&gt; gate_1\n</code></pre><p>after</p></body>')
WITHOUT = "<h1>x</h1><p>no diagram here</p></body>"

out = ready(WITH)
print("\nthe transform:")
for label, cond in [
    ("the fence becomes a mermaid element", '<pre class="mermaid">' in out),
    ("escaped arrows are restored", "-->" in out and "--&gt;" not in out),
    ("the renderer is inlined", "mermaid.initialize" in out),
    # The element must exist before the script runs. Checking against
    # "</body>" was wrong: the minified library contains that literal, so the
    # first occurrence is inside the renderer itself.
    ("the diagram element comes before the script that draws it",
     out.index('<pre class="mermaid">') < out.index("mermaid.initialize")),
    ("and the script is inside the body, not appended after it",
     out.rindex("mermaid.initialize") < out.rindex("</body>")),
    ("the ready flag exists for render_html to wait on",
     "window.__mermaidReady" in out),
]:
    print(f"  {'ok  ' if cond else 'FAIL'} {label}")
    if not cond:
        die(label)

plain = ready(WITHOUT)
print(f"  {'ok  ' if plain == WITHOUT else 'FAIL'} a document with no diagram "
      f"is byte-identical ({len(plain)} chars, was {len(WITHOUT)})")
if plain != WITHOUT:
    die("a document with no diagram was modified")

kb = len(out) / 1024
print(f"  ok   a document WITH one grows to {kb:,.0f} KB (the vendored library)")

print("\napplied: " + ", ".join(applied))
print(f"backup:  {backup.name}")
print()
print("Restart the PDF service, then convert something with a diagram:")
print("  launchctl kickstart -k gui/$(id -u)/com.ducorn.pdf")
print()
print("The log will say:  mermaid: 2 diagram(s) drawn")
print("  tail -f ~/DC/logs/pdf_api.log")
