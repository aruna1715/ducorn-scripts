#!/usr/bin/env python3
"""
Print the PDF service's error instead of throwing it away.

    print(f"  ❌ Conversion failed: {resp.status_code}")

The convert endpoint returns the real cause in the response body —

    raise HTTPException(status_code=500,
                        detail=f"PDF generation failed: {str(exc)}")

— and gdrive_sync discards it, so a failure reports a bare "500" and the only
way to find out what happened is to go and read the service's log, which in
this case did not have a traceback either.

Same shape as the rest of today: the information exists at the point of
failure and is dropped before anyone can see it.
"""
import shutil
import sys
from datetime import datetime
from pathlib import Path

SYNC = Path("/Users/ducorn/DC/scripts/gdrive_sync.py")
s = SYNC.read_text(encoding="utf-8")

if "detail" in s and "Conversion failed" in s and "resp.text" in s:
    sys.exit("Already patched — the response body is printed.")

OLD = '''        else:
            print(f"  ❌ Conversion failed: {resp.status_code}")
            return None'''

NEW = '''        else:
            # The endpoint puts the real cause in the body. Print it: a bare
            # status code sends you to a log that may not have the traceback.
            detail = ""
            try:
                detail = resp.json().get("detail", "")
            except Exception:
                detail = (resp.text or "")[:500]
            print(f"  ❌ Conversion failed: {resp.status_code}"
                  + (f"\\n     {detail}" if detail else "  (no detail returned)"))
            return None'''

if s.count(OLD) != 1:
    sys.exit(f"ANCHOR MISS: found {s.count(OLD)}, expected 1. Nothing written.")

backup = SYNC.with_name(f"gdrive_sync.backup-errors-{datetime.now():%Y%m%d-%H%M%S}.py")
shutil.copy2(SYNC, backup)
SYNC.write_text(s.replace(OLD, NEW, 1), encoding="utf-8")

import ast
try:
    ast.parse(SYNC.read_text(encoding="utf-8"))
except SyntaxError as e:
    shutil.copy2(backup, SYNC)
    sys.exit(f"SYNTAX ERROR ({e}) — reverted from {backup}")

print("applied: conversion error detail")
print(f"backup:  {backup}")
