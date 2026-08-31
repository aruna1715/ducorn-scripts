#!/usr/bin/env python3
"""
Stop the running header and footer landing on the cover page.

Apply AFTER patch_pdf_pagination.py.

WHAT I BROKE
------------
Moving the header and footer to Chromium templates fixed the body pages and
wrecked the cover, because Chromium stamps templates on EVERY page and has no
per-page selector. On page 1 you now get:

  * the template header sitting above the dark cover block, squeezing it down
    off the top edge so it no longer bleeds
  * the template footer printed directly on top of the cover's own footer —
    two lines of grey text overlapping, which looks like a rendering fault

I predicted the footer would appear and called it "a thin line". It is not a
thin line, it is a visible collision, and this is a document meant to be put in
front of Vijay.

THE FIX
-------
Render twice and merge. pypdf is already a dependency (_apply_text_watermark
uses it), so this costs one extra set_content and a merge:

  pass 1  cover only    no templates, zero margins, full bleed restored
  pass 2  body only     templates on, margins as set

Both passes use the SAME html with one injected style rule hiding the other
half, so there is no structural parsing and no second source of truth about
what a cover looks like.

A side effect worth having: page numbers now count body pages only, so the
first content page is "Page 1 of 21" rather than "Page 2 of 22". That is what
a numbered document normally does.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

ENGINE = Path("/Users/ducorn/DC/ducorn-products/products/"
              "ducorn-pdf-export-tool/app/services/pdf_engine.py")

s = ENGINE.read_text(encoding="utf-8")
if "DUCORN_FOOTER_TEMPLATE" not in s:
    sys.exit("Run patch_pdf_pagination.py first.")
if "_render_two_pass" in s:
    sys.exit("Already patched — _render_two_pass is present.")

applied = []


def swap(label, old, new):
    global s
    if s.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {s.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    s = s.replace(old, new, 1)
    applied.append(label)


swap("two-pass helper", '''    async def render_html(self, html: str, options: Optional[PDFOptions] = None) -> bytes:
        """Render an HTML string to PDF bytes."""''',
'''    @staticmethod
    def _merge(parts: list) -> bytes:
        """Concatenate rendered PDFs. pypdf is already a dependency."""
        import io
        from pypdf import PdfWriter, PdfReader  # type: ignore

        writer = PdfWriter()
        for blob in parts:
            for page in PdfReader(io.BytesIO(blob)).pages:
                writer.add_page(page)
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()

    async def _render_two_pass(self, page, html, options, title):
        """
        Cover and body rendered separately, then merged.

        Chromium draws header/footer templates on every page and offers no way
        to skip the first, so the cover has to be a separate render. Both
        passes use the same html with one rule hiding the other half — a second
        cover template would be a second thing to keep in sync.
        """
        # Cover: no templates, no margins, so the dark block bleeds to the edge
        # the way it did before templates existed.
        await page.set_content(
            html + "<style>.ducorn-content{display:none !important}"
                   "@page{margin:0 !important}</style>",
            wait_until="networkidle")
        cover_opts = _build_page_options(options, title)
        cover_opts["display_header_footer"] = False
        cover_opts["margin"] = {"top": "0", "bottom": "0",
                                "left": "0", "right": "0"}
        cover = await page.pdf(**cover_opts)

        # Body: templates on. Page numbers count body pages only, so the first
        # content page is "Page 1 of N" rather than "Page 2 of N+1".
        await page.set_content(
            html + "<style>.ducorn-cover{display:none !important}"
                   "@page{margin:18mm 14mm 16mm 14mm !important}</style>",
            wait_until="networkidle")
        body = await page.pdf(**_build_page_options(options, title))

        return self._merge([cover, body])

    async def render_html(self, html: str, options: Optional[PDFOptions] = None) -> bytes:
        """Render an HTML string to PDF bytes."""''')


swap("render_html branch", '''            pdf_bytes = await page.pdf(
                **_build_page_options(options, await page.title()))
            await browser.close()

        if options.watermark_text:
            pdf_bytes = await self._apply_text_watermark(pdf_bytes, options.watermark_text)

        return pdf_bytes

    async def render_url''',
'''            title = await page.title()
            if 'class="ducorn-cover"' in html:
                pdf_bytes = await self._render_two_pass(page, html, options, title)
            else:
                # No cover — a single pass is correct and cheaper. Rendering
                # everything twice regardless would double the cost of every
                # document that does not have one.
                pdf_bytes = await page.pdf(**_build_page_options(options, title))
            await browser.close()

        if options.watermark_text:
            pdf_bytes = await self._apply_text_watermark(pdf_bytes, options.watermark_text)

        return pdf_bytes

    async def render_url''')

backup = ENGINE.with_name(f"pdf_engine.backup-cover-"
                          f"{datetime.now():%Y%m%d-%H%M%S}.py")
shutil.copy2(ENGINE, backup)
ENGINE.write_text(s, encoding="utf-8")

import ast
try:
    ast.parse(s)
except SyntaxError as e:
    shutil.copy2(backup, ENGINE)
    sys.exit(f"SYNTAX ERROR ({e}) — reverted from {backup}")

print("applied: " + ", ".join(applied))
print(f"backup:  {backup}")
