#!/usr/bin/env python3
"""
shared/.env, read and written safely — one definition, used by CLI and admin UI.

    python3 scripts/ducorn_envfile.py                 what is set, masked
    python3 scripts/ducorn_envfile.py --check         duplicates, blanks, oddities
    python3 scripts/ducorn_envfile.py --get NAME      one value, in full
    python3 scripts/ducorn_envfile.py --set NAME=VAL  with backup and validation
    python3 scripts/ducorn_envfile.py --backups       list restore points
    python3 scripts/ducorn_envfile.py --restore FILE  put one back

── WHY A MODULE ─────────────────────────────────────────────────────────────

shared/.env is read by every service on this machine. Editing it from a web
page is the single most dangerous thing the admin dashboard will do, so the
mechanics live here — backed up, validated, written atomically — and the API
calls this rather than growing its own copy.

── WHAT IT ALREADY FOUND ────────────────────────────────────────────────────

LITELLM_MASTER_KEY and CURSOR_API_KEY are each defined TWICE in the current
file. Shell `source` and every dotenv parser take the last one, silently. Two
values for one fact, in the file that configures everything — the same defect
class as the rest of this stack, sitting in its configuration.

--check reports these. Nothing repairs them automatically: which of the two
you meant is a decision.

── WHY THE NAME ─────────────────────────────────────────────────────────────

This was first delivered as scripts/ducorn_env.py. That name was already
taken by a module holding load_ducorn_env(), which doctor.py,
langgraph_flow.py, skill_runner.py, slack_bot.py, the activity API and four
other files import — so the new file shadowed it and every one of them broke
with ImportError. The original is restored; this file carries a name nothing
else uses. "envfile" because that is what it manages: the file, not the
process environment that ducorn_env.py loads into.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

DC = Path(os.environ.get("DUCORN_ROOT", "/Users/ducorn/DC"))
ENV = DC / "shared" / ".env"
BACKUP_DIR = DC / "shared" / ".env-backups"

# A name is a secret if it looks like one. Used for masking, never for
# deciding whether to store something.
#
# NOT anchored at the end: this was `(KEY|TOKEN|...)$`, and LITELLM_KEY_REX
# ends in "REX", so every one of the ten agent keys printed in full. Matching
# anywhere in the name catches those and costs nothing — the only names it
# newly covers are ones that genuinely hold a secret.
_SECRET = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASS|CREDENTIAL|DATABASE_URL)",
                     re.I)

# Which services read which settings. Changing a value here without
# restarting these leaves the running process on the old one — which is how
# DUCORN_DAILY_BUDGET was raised and the API kept refusing to start runs.
AFFECTS = {
    r"^LITELLM_KEY_":            ["com.ducorn.litellm", "com.ducorn.router"],
    r"^LITELLM_MASTER_KEY$":     ["com.ducorn.litellm", "com.ducorn.router"],
    r"^(ANTHROPIC|DEEPSEEK|GOOGLE|SERPER)_API_KEY$":
                                 ["com.ducorn.litellm", "com.ducorn.router"],
    r"^SLACK_":                  ["com.ducorn.slack"],
    r"^DUCORN_(API_TOKEN|API_BASE_URL|DAILY_BUDGET)$": ["com.ducorn.api"],
    r"^DUCORN_SMTP_":            ["com.ducorn.api"],
    r"^DATABASE_URL$":           ["com.ducorn.api", "com.ducorn.litellm"],
    r"^OLLAMA_|^LLAMA_SERVER_":  ["com.ducorn.ollama"],
    r"^PDF_":                    ["com.ducorn.pdf"],
    r"^UI_":                     ["com.ducorn.api"],
    r"^GITHUB_":                 [],       # read per-command, nothing to restart
    r"^CURSOR_API_KEY$":         [],
    r"^CREWAI_":                 [],
}


class EnvError(Exception):
    """A refusal. The message is shown to whoever asked."""


def is_secret(name: str) -> bool:
    return bool(_SECRET.search(name))


def mask(name: str, value: str) -> str:
    if not value:
        return ""
    if not is_secret(name):
        return value
    if len(value) <= 8:
        return "•" * len(value)
    return f"{value[:4]}{'•' * 8}{value[-4:]}"


def affects(name: str) -> list:
    for pattern, services in AFFECTS.items():
        if re.search(pattern, name):
            return list(services)
    return []


def read_raw() -> list:
    """Every line, so a write can preserve comments, blanks and order."""
    if not ENV.is_file():
        raise EnvError(f"{ENV} does not exist")
    return ENV.read_text(encoding="utf-8", errors="replace").splitlines()


def parse(lines: list = None) -> list:
    """
    [{name, value, line, duplicate_of}] in file order.

    Duplicates are REPORTED, not resolved. Every parser takes the last one;
    saying so is more useful than quietly doing the same.
    """
    lines = read_raw() if lines is None else lines
    out, seen = [], {}
    for i, raw in enumerate(lines, 1):
        s = raw.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        name, _, value = s.partition("=")
        name = name.strip()
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
            continue
        raw_value = value
        value = value.strip().strip('"').strip("'")
        entry = {"name": name, "value": value, "raw": raw_value, "line": i,
                 "duplicate_of": seen.get(name)}
        seen[name] = i
        out.append(entry)
    return out


def effective() -> dict:
    """What the shell would actually export: last definition wins."""
    return {e["name"]: e["value"] for e in parse()}


def check() -> list:
    """Problems worth a human's attention. Empty list is a clean file."""
    entries = parse()
    problems = []
    by_name = {}
    for e in entries:
        by_name.setdefault(e["name"], []).append(e)

    for name, es in sorted(by_name.items()):
        if len(es) > 1:
            lines = ", ".join(str(e["line"]) for e in es)
            problems.append({
                "level": "warn", "name": name,
                "detail": (f"defined {len(es)} times (lines {lines}) — every "
                           f"parser takes line {es[-1]['line']}; the others "
                           f"are dead"),
            })
        if not es[-1]["value"]:
            problems.append({"level": "warn", "name": name,
                             "detail": "set to an empty value"})
        v = es[-1]["value"]
        # Against the RAW value. Comparing the parsed one to its own strip()
        # is always false — parse() strips before storing, so this check
        # could never fire.
        if es[-1]["raw"] != es[-1]["raw"].strip():
            problems.append({"level": "warn", "name": name,
                             "detail": "has leading or trailing whitespace"})
        if re.search(r"^(your|xxx|changeme|todo|<)", v, re.I):
            problems.append({"level": "warn", "name": name,
                             "detail": f"looks like a placeholder ({v[:20]})"})
    return problems


# ─────────────────────────────────────────────────────────────────────────────
# Validation — a refusal is cheaper than a broken stack
# ─────────────────────────────────────────────────────────────────────────────

_RULES = [
    (r"^DUCORN_DAILY_BUDGET$", r"^\d+(\.\d+)?$",
     "a number, e.g. 50.0"),
    (r"^DUCORN_SMTP_PORT$", r"^\d{1,5}$", "a port number"),
    (r"^ANTHROPIC_API_KEY$", r"^sk-ant-\S{20,}$",
     "an Anthropic key starting sk-ant-"),
    (r"^LITELLM_KEY_\w+$", r"^sk-\S{10,}$", "a LiteLLM key starting sk-"),
    (r"^SLACK_BOT_TOKEN$", r"^xoxb-\S{10,}$", "a Slack bot token (xoxb-)"),
    (r"^SLACK_APP_TOKEN$", r"^xapp-\S{10,}$", "a Slack app token (xapp-)"),
    (r"^GITHUB_TOKEN$", r"^gh[pousr]_\S{10,}$", "a GitHub token (ghp_ …)"),
    (r"^DATABASE_URL$", r"^postgres(ql)?://\S+$", "a postgres:// URL"),
    (r"^OLLAMA_(DEBUG|FLASH_ATTENTION)$", r"^[01]$", "0 or 1"),
]


def validate(name: str, value: str) -> None:
    """Raise EnvError if this value cannot be right. Silence means plausible."""
    if "\n" in value or "\r" in value:
        raise EnvError(f"{name}: a value cannot contain a newline")
    if value != value.strip():
        raise EnvError(f"{name}: has leading or trailing whitespace")
    for pattern, shape, described in _RULES:
        if re.search(pattern, name):
            if not re.match(shape, value):
                raise EnvError(
                    f"{name} should be {described} — refusing to write "
                    f"{value[:12] + '…' if len(value) > 12 else value!r}. "
                    f"Nothing was changed.")
            return


def backup() -> Path:
    """
    Copy the current file somewhere it will not be overwritten.

    The name was second-resolution, and restore() takes a backup before it
    restores — so restoring within the same second as the backup was made
    silently OVERWROTE the very file being restored, and put the current
    contents back instead. Found by a test that restored immediately.
    """
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    dest = BACKUP_DIR / f".env.{stamp}"
    n = 1
    while dest.exists():
        dest = BACKUP_DIR / f".env.{stamp}-{n}"
        n += 1
    shutil.copy2(ENV, dest)
    try:
        dest.chmod(0o600)
    except OSError:
        pass
    return dest


def backups() -> list:
    if not BACKUP_DIR.is_dir():
        return []
    return sorted((p for p in BACKUP_DIR.glob(".env.*") if p.is_file()),
                  key=lambda p: p.name, reverse=True)


def write(changes: dict, *, keep: int = 40) -> dict:
    """
    Apply {name: value}. Backs up first, validates all, then writes once.

    Every value is validated BEFORE anything is written, so a batch with one
    bad entry changes nothing rather than half of it.
    """
    if not changes:
        raise EnvError("nothing to change")
    for name, value in changes.items():
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
            raise EnvError(f"{name!r} is not a valid variable name")
        validate(name, value)

    b = backup()
    lines = read_raw()
    entries = parse(lines)
    last_line = {}
    for e in entries:
        last_line[e["name"]] = e["line"]

    touched, added = [], []
    for name, value in changes.items():
        rendered = f"{name}={value}"
        if name in last_line:
            lines[last_line[name] - 1] = rendered
            touched.append(name)
        else:
            lines.append(rendered)
            added.append(name)

    tmp = ENV.with_suffix(".env.tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        tmp.chmod(ENV.stat().st_mode & 0o777)
    except OSError:
        pass
    tmp.replace(ENV)                       # atomic on the same filesystem

    for old in backups()[keep:]:
        try:
            old.unlink()
        except OSError:
            pass

    services = sorted({s for n in changes for s in affects(n)})
    return {"backup": str(b), "changed": touched, "added": added,
            "restart": services}


def restore(name: str) -> str:
    src = BACKUP_DIR / name if "/" not in name else Path(name)
    if not src.is_file() or src.parent != BACKUP_DIR:
        raise EnvError(f"{name} is not one of the backups in {BACKUP_DIR}")
    backup()                               # the current file is worth keeping too
    shutil.copy2(src, ENV)
    return str(src)


# ─────────────────────────────────────────────────────────────────────────────
def _main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--get", metavar="NAME")
    ap.add_argument("--set", metavar="NAME=VALUE", action="append")
    ap.add_argument("--backups", action="store_true")
    ap.add_argument("--restore", metavar="FILE")
    a = ap.parse_args()

    if a.get:
        v = effective().get(a.get)
        if v is None:
            sys.exit(f"{a.get} is not set")
        print(v)
        raise SystemExit(0)

    if a.backups:
        bs = backups()
        print(f"{len(bs)} backup(s) in {BACKUP_DIR}")
        for p in bs[:20]:
            print(f"  {p.name}   {p.stat().st_size:,} bytes")
        raise SystemExit(0)

    if a.restore:
        print("restored from " + restore(a.restore))
        raise SystemExit(0)

    if a.set:
        changes = {}
        for pair in a.set:
            if "=" not in pair:
                sys.exit(f"--set expects NAME=VALUE, got {pair!r}")
            k, _, v = pair.partition("=")
            changes[k.strip()] = v
        try:
            r = write(changes)
        except EnvError as e:
            sys.exit(f"REFUSED: {e}")
        print(f"backed up to {r['backup']}")
        for n in r["changed"]:
            print(f"  changed {n}")
        for n in r["added"]:
            print(f"  added   {n}")
        if r["restart"]:
            print("\nrestart for this to take effect:")
            for s in r["restart"]:
                print(f"  launchctl kickstart -k gui/$(id -u)/{s}")
        raise SystemExit(0)

    if a.check:
        ps = check()
        if not ps:
            print("no problems found in shared/.env")
            raise SystemExit(0)
        print(f"{len(ps)} thing(s) worth a look:\n")
        for p in ps:
            print(f"  {p['level']:5} {p['name']:28} {p['detail']}")
        raise SystemExit(0)

    entries = parse()
    seen = set()
    print(f"{len(entries)} definitions, "
          f"{len({e['name'] for e in entries})} distinct names\n")
    print(f"  {'name':30} {'value':26} restarts")
    print("  " + "─" * 74)
    for e in reversed(entries):            # last definition wins; show that one
        if e["name"] in seen:
            continue
        seen.add(e["name"])
        svc = ", ".join(s.replace("com.ducorn.", "") for s in affects(e["name"]))
        print(f"  {e['name']:30} {mask(e['name'], e['value'])[:26]:26} {svc}")


if __name__ == "__main__":
    # A configuration tool that answers a missing file with a traceback is
    # telling you about itself instead of about your machine.
    try:
        _main()
    except EnvError as e:
        sys.exit(f"{e}")
    except KeyboardInterrupt:
        sys.exit(130)
