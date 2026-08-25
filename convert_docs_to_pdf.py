"""
DuCorn PDF Converter
Converts all .md files in ducorn-products/docs/ to PDF
Uses the ducorn-pdf-export-tool API on port 8001
"""
import os
import sys
import json
import requests
from pathlib import Path

API_URL = "http://localhost:8001/v1/convert"
API_KEY = os.environ.get("PDF_API_KEY", "dk_pro_test_key_002")
DOCS_DIR = Path("/Users/ducorn/DC/ducorn-products/docs")
PDF_DIR = Path("/Users/ducorn/DC/ducorn-products/pdfs")

def convert_md_to_pdf(md_path: Path) -> bool:
    pdf_path = PDF_DIR / md_path.with_suffix('.pdf').name
    
    # Skip if PDF already exists and is newer than the MD file
    if pdf_path.exists() and pdf_path.stat().st_mtime > md_path.stat().st_mtime:
        print(f"  ⏭ Skipping: {md_path.name} (PDF up to date)")
        return True
    
    print(f"Converting: {md_path.name} → {pdf_path.name}")
    
    content = md_path.read_text(encoding='utf-8')
    
    resp = requests.post(
        API_URL,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": API_KEY
        },
        json={
            "source_type": "markdown",
            "content": content,
            "filename": pdf_path.name
        }
    )
    
    if resp.status_code == 200:
        pdf_path.write_bytes(resp.content)
        print(f"  ✅ Saved: {pdf_path.name} ({len(resp.content):,} bytes)")
        return True
    else:
        print(f"  ❌ Failed: {resp.status_code} — {resp.text[:100]}")
        return False

if __name__ == "__main__":
    PDF_DIR.mkdir(exist_ok=True)
    
    md_files = list(DOCS_DIR.glob("*.md"))
    print(f"\n📄 Converting {len(md_files)} markdown documents to PDF...\n")
    
    converted = 0
    skipped = 0
    for md_file in sorted(md_files):
        pdf_path = PDF_DIR / md_file.with_suffix('.pdf').name
        if pdf_path.exists() and pdf_path.stat().st_mtime > md_file.stat().st_mtime:
            print(f"  ⏭ Skipping: {md_file.name} (PDF up to date)")
            skipped += 1
        else:
            if convert_md_to_pdf(md_file):
                converted += 1

    print(f"\n✅ Done: {converted} converted | {skipped} skipped")
    print(f"📁 PDFs saved to: {PDF_DIR}")