#!/usr/bin/env python3
"""
Make the PDF header and footer actually paginate, and the page number appear.

THE BUG
-------
pdf_engine.py renders with Playwright + Chromium, but styles its running
header and footer with the CSS Paged Media spec:

    .ducorn-page-footer { position: running(footer); }
    @page { @bottom-center { content: element(footer); } }

WeasyPrint and PrinceXML implement that. Chromium does not — it ignores
`position: running()` entirely. So the two divs are not lifted out of the flow;
they render as ordinary content at the top of the document. That is the stacked
dark bar and grey bar sitting above the body on page 2 of every PDF, and it is
why they never appear on page 3.

The page number is a second, independent break:

    <span>Page <span class="pageNumber"></span></span>

`.pageNumber` is substituted by Chromium ONLY inside the footerTemplate passed
to page.pdf(). In ordinary page content it is an empty span, which is why every
document says "Page" with nothing after it.

_build_pdf_kwargs already knows how to pass templates — but only when a caller
supplies header_html or footer_html, and gdrive_sync never does. So the correct
mechanism was present, wired to a condition that is never true.

THE FIX
-------
Use Chromium's own mechanism: the header and footer become templates passed to
page.pdf(), and the in-body divs are removed so they stop appearing as content.
Templates render in an isolated context with no access to page CSS, so their
styling is inline and their font sizes are absolute.

ONE THING THIS DOES NOT FIX
---------------------------
Chromium applies header and footer to EVERY page, including the first. The
cover page will now carry a thin footer line it did not have before. There is
no per-page selector in a footer template and no working @page:first, so the
only way to keep the cover pristine is to render it as a separate document and
merge — worth doing if the cover matters, but it is a bigger change than this
and I would rather you see this working first.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

ENGINE = Path("/Users/ducorn/DC/ducorn-products/products/"
              "ducorn-pdf-export-tool/app/services/pdf_engine.py")

s = ENGINE.read_text(encoding="utf-8")
if "DUCORN_FOOTER_TEMPLATE" in s:
    sys.exit("Already patched — the footer template is present.")

applied = []


def swap(label, old, new):
    global s
    if s.count(old) != 1:
        sys.exit(f"ANCHOR MISS [{label}]: found {s.count(old)}, expected 1. "
                 f"NOTHING WRITTEN.")
    s = s.replace(old, new, 1)
    applied.append(label)


# ── 1. Retire the paged-media CSS ────────────────────────────────────────────
# Two rules, not one: .ducorn-page-header has its own position: running(header)
# eighteen lines above the footer's.
swap("running header css", '''  border-bottom: 2px solid var(--teal);
  position: running(header);
}''', '''  border-bottom: 2px solid var(--teal);
}''')

swap("running footer css", '''  border-top: 1.5px solid var(--teal);
  position: running(footer);
}

@page {
  margin: 52px 40px 40px 40px;
  @top-center { content: element(header); }
  @bottom-center { content: element(footer); }
}
@page:first {
  margin: 0;
  @top-center { content: none; }
  @bottom-center { content: none; }
}''', '''  border-top: 1.5px solid var(--teal);
}

/* The header and footer are Chromium header/footer templates now — see
   DUCORN_HEADER_TEMPLATE below. position: running() and the @top-center /
   @bottom-center margin boxes are CSS Paged Media, which WeasyPrint and Prince
   implement and Chromium does not. They did nothing except leave the two bars
   stranded at the top of the body.

   The @page margins stay, and grow: Chromium draws its templates INSIDE the
   page margin, so 52px (13.7mm) at the top left no room and the header would
   have overlapped the first line of text. @page:first { margin: 0 } stays as
   well — plain @page margins ARE supported, and it is what makes the cover
   full-bleed. */
@page {
  margin: 18mm 14mm 16mm 14mm;
}
@page:first {
  margin: 0;
}''')


# ── 2. Remove the in-body header/footer, which were never running ────────────
swap("body divs", '''<!-- Running Header/Footer -->
<div class="ducorn-page-header">
  <span><span class="brand">DUCORN</span> &nbsp;&middot;&nbsp; {doc_title}</span>
  <span class="right">INTERNAL &nbsp;&middot;&nbsp; CONFIDENTIAL</span>
</div>
<div class="ducorn-page-footer">
  <span>DuCorn Autonomous AI Company &nbsp;&middot;&nbsp; ducorn-hq.live</span>
  <span>Page <span class="pageNumber"></span></span>
</div>
''', '''<!-- The running header and footer are Chromium templates, not content.
     They used to be two divs here with position: running(), which Chromium
     ignores — so they rendered inline above the body on every document. -->
''')


# ── 3. The templates themselves ──────────────────────────────────────────────
swap("templates", '''    if options.header_html or options.footer_html:
        kwargs["display_header_footer"] = True
        kwargs["header_template"] = options.header_html or "<span></span>"
        kwargs["footer_template"] = options.footer_html or "<span></span>"''',
'''    # Always on. This used to be conditional on a caller passing header_html
    # or footer_html; gdrive_sync never does, so the one mechanism Chromium
    # actually supports was wired to a condition that is never true.
    kwargs["display_header_footer"] = True
    kwargs["header_template"] = options.header_html or DUCORN_HEADER_TEMPLATE.format(
        title=_esc(doc_title or ""))
    kwargs["footer_template"] = options.footer_html or DUCORN_FOOTER_TEMPLATE''')


# ── 4. Template definitions ──────────────────────────────────────────────────
swap("template defs", '''def _build_page_options(''',
'''def _esc(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


# Chromium renders these in an isolated context: no page CSS, no custom
# properties, and a default font-size near zero. Everything is inline and
# absolute on purpose. .pageNumber and .totalPages are substituted by Chromium
# and only work here.
DUCORN_HEADER_TEMPLATE = """
<div style="width:100%;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',
     Helvetica,Arial,sans-serif;font-size:7pt;color:#5b6b78;padding:0 14mm;
     display:flex;justify-content:space-between;border-bottom:0.5pt solid #d7e0e8;
     margin-bottom:4mm;">
  <span><span style="color:#0d9488;font-weight:700;letter-spacing:.1em;">DUCORN</span>
    &nbsp;&middot;&nbsp; {title}</span>
  <span style="letter-spacing:.1em;">INTERNAL &nbsp;&middot;&nbsp; CONFIDENTIAL</span>
</div>
"""

DUCORN_FOOTER_TEMPLATE = """
<div style="width:100%;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',
     Helvetica,Arial,sans-serif;font-size:7pt;color:#5b6b78;padding:0 14mm;
     display:flex;justify-content:space-between;border-top:1pt solid #0d9488;
     padding-top:2mm;margin-top:4mm;">
  <span>DuCorn Autonomous AI Company &nbsp;&middot;&nbsp; ducorn-hq.live</span>
  <span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span>
</div>
"""


def _build_page_options(''')

# doc_title is derived inside _markdown_to_html and never reaches the options
# builder — but the rendered page has a <title>, and both page.pdf() call sites
# have the page. Ask the browser rather than plumbing a new argument through
# three layers.
swap("signature", '''def _build_page_options(options: PDFOptions) -> dict:
    """Translate PDFOptions → Playwright page.pdf() kwargs."""''',
'''def _build_page_options(options: PDFOptions, doc_title: str = "") -> dict:
    """Translate PDFOptions → Playwright page.pdf() kwargs."""''')

if s.count("pdf_bytes = await page.pdf(**_build_page_options(options))") != 2:
    sys.exit("ANCHOR MISS [call sites]: expected 2 page.pdf() calls. "
             "NOTHING WRITTEN.")
s = s.replace("pdf_bytes = await page.pdf(**_build_page_options(options))",
              "pdf_bytes = await page.pdf(\n"
              "                **_build_page_options(options, await page.title()))")
applied.append("call sites (2)")

backup = ENGINE.with_name(f"pdf_engine.backup-pagination-"
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
print()
print("Restart the PDF export service, then rebuild a document to check:")
print("  ~/DC/ducorn/.venv/bin/python ~/DC/scripts/gdrive_sync.py --force "
      "--file ~/DC/ducorn-products/docs/ducorn-cost-tracker-PRD.md")
