"""
DuCorn Environment Loader
=========================
Call load_ducorn_env() at the top of every entry point.
Reads all keys from shared/.env — no reliance on subprocess env inheritance.
"""
import os
from pathlib import Path

ENV_PATH = Path("/Users/ducorn/DC/shared/.env")

def load_ducorn_env():
    """Load all keys from shared .env into os.environ."""
    if not ENV_PATH.exists():
        print(f"⚠️  .env not found at {ENV_PATH}")
        return
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            k, v = k.strip(), v.strip()
            if k and v:
                os.environ[k] = v  # Always set — overrides plist vars too
    print(f"✅ DuCorn env loaded from {ENV_PATH}")
