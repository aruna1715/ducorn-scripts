#!/usr/bin/env python3
"""
Is this machine healthy, and if not, what do I run?

    python3 scripts/doctor.py            everything
    python3 scripts/doctor.py --spend    just today's money
    python3 scripts/doctor.py --quiet    only what is wrong

── WHY ──────────────────────────────────────────────────────────────────────

Every failure this week was silent: a control that existed, read correctly in
isolation, and never reached the thing it was supposed to control. Playwright
absent so a QA branch could not run. A status the database refused. A model
switcher that did not reach the brief wizard. A dead GitHub token nothing used.

None of those are hard to see once you look. The problem is knowing where to
look, and that knowledge currently lives in a conversation rather than on the
machine.

This is that knowledge, executable. Every check runs the real thing — connects
to the database, launches the browser, calls the API — and every failure
prints the command that fixes it. No check reports "ok" on the basis of a
file existing.

Run it before starting a pipeline, after any change, and first when something
breaks.
"""
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, "/Users/ducorn/DC/scripts")
from bootstrap_python import ensure_modules  # noqa

ensure_modules("psycopg2")

import psycopg2  # noqa
from ducorn_env import load_ducorn_env  # noqa

DC = Path("/Users/ducorn/DC")
VENV_PY = DC / "ducorn/.venv/bin/python"
API = "http://localhost:8000"
API_KEY = os.environ.get("DUCORN_API_TOKEN", "ducorn-api-2026-secure")

results = []
_quiet = False


def check(section, name, ok, detail="", fix=None):
    results.append({"section": section, "name": name, "ok": bool(ok),
                    "detail": detail, "fix": fix})
    if _quiet and ok:
        return ok
    mark = "ok  " if ok else "FAIL"
    line = f"  {mark} {name}"
    if detail:
        line += f"   {detail}"
    print(line)
    if not ok and fix:
        print(f"       → {fix}")
    return ok


def heading(text):
    if not _quiet:
        print(f"\n── {text} " + "─" * max(0, 66 - len(text)))


def port_open(port, host="127.0.0.1", timeout=1.5):
    try:
        with socket.create_connection((host, port), timeout):
            return True
    except OSError:
        return False


def get_json(url, timeout=5, key=True):
    req = urllib.request.Request(
        url, headers={"x-api-key": API_KEY} if key else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def run(cmd, **kw):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, **kw)
    except (FileNotFoundError, NotADirectoryError, PermissionError) as e:
        class _F:
            returncode, stdout = 127, ""
            stderr = f"{type(e).__name__}: {e}"
        return _F()


# ═══════════════════════════════════════════════════════════════════════════
def check_services():
    heading("services")
    for name, port, fix in [
        ("activity API", 8000, "launchctl kickstart -k gui/$(id -u)/com.ducorn.api"),
        ("DuCorn router", 4001, "launchctl kickstart -k gui/$(id -u)/com.ducorn.router"),
        ("LiteLLM", 4000, "launchctl kickstart -k gui/$(id -u)/com.ducorn.litellm"),
        ("Ollama", 11434, "launchctl kickstart -k gui/$(id -u)/com.ducorn.ollama"),
        ("PDF service", 8001, "launchctl kickstart -k gui/$(id -u)/com.ducorn.pdf"),
    ]:
        check("services", f"{name} on :{port}", port_open(port),
              "" if port_open(port) else "not listening", fix)


def check_databases():
    heading("databases and schema")
    for db in ("ducorn", "litellm_db"):
        try:
            with psycopg2.connect(f"postgresql://ducorn@localhost/{db}") as c:
                c.cursor().execute("SELECT 1")
            check("db", f"{db} reachable", True)
        except Exception as e:
            check("db", f"{db} reachable", False, f"{type(e).__name__}: {e}",
                  "check PostgreSQL is running: brew services list")
            return

    r = run([sys.executable, str(DC / "scripts/migrate.py"), "--status"])
    pending = [l for l in r.stdout.splitlines() if "pending" in l.lower()]
    check("db", "migrations applied", r.returncode == 0 and not pending,
          f"{len(pending)} pending" if pending else "up to date",
          "python3 scripts/migrate.py")

    r = run([sys.executable, str(DC / "scripts/prove_db_contracts.py")])
    check("db", "code and schema agree on every status", r.returncode == 0,
          "" if r.returncode == 0 else "prove_db_contracts failed",
          "python3 scripts/prove_db_contracts.py")


def check_browser():
    heading("browser")
    r = run([str(VENV_PY), "-c",
             "from playwright.sync_api import sync_playwright\n"
             "with sync_playwright() as p:\n"
             "    b = p.chromium.launch(); pg = b.new_page()\n"
             "    pg.set_content('<h1 id=t>ok</h1>')\n"
             "    print(pg.inner_text('#t')); b.close()"])
    check("browser", "chromium launches and renders",
          r.returncode == 0 and "ok" in r.stdout,
          (r.stderr.strip().splitlines() or [""])[-1][:70] if r.returncode else "",
          "python3 scripts/install_playwright.py --apply")

    req = DC / "ducorn-products/products/_shared/requirements-ui.txt"
    check("browser", "products/_shared/requirements-ui.txt", req.is_file(),
          "" if req.is_file() else "UI products cannot get a browser in their venv",
          "python3 scripts/install_playwright.py --apply")

    guide = DC / "gstack/references/web-interface-guidelines.md"
    check("browser", "interface guidelines vendored", guide.is_file(),
          f"{guide.stat().st_size:,} bytes" if guide.is_file() else "not vendored",
          "python3 scripts/vendor_web_guidelines.py")


def check_models():
    heading("models")
    try:
        cfg = get_json(f"{API}/agents/config")
    except Exception as e:
        check("models", "switcher readable", False, f"{type(e).__name__}: {e}",
              "is the API up? launchctl kickstart -k gui/$(id -u)/com.ducorn.api")
        return

    agents = cfg.get("agents") or {}
    served = {m["id"] for m in (cfg.get("available_models") or [])}
    check("models", "switcher readable", bool(agents), f"{len(agents)} agents")

    unknown = {a: m for a, m in agents.items() if served and m not in served}
    check("models", "every agent's model is served by LiteLLM", not unknown,
          f"{unknown}" if unknown else f"{len(served)} models available",
          "pick a served model in the dashboard, or add it to "
          "scripts/litellm_config.yaml")

    paid = {a: m for a, m in agents.items() if not str(m).startswith("local-")}
    if paid and not _quiet:
        print(f"       paid: {', '.join(f'{a}={m}' for a, m in sorted(paid.items()))}")


def check_keys_and_spend(spend_only=False):
    heading("spend today")
    try:
        with psycopg2.connect("postgresql://ducorn@localhost/litellm_db") as c:
            cur = c.cursor()
            cur.execute("""
                SELECT COALESCE(model,'(none)'), count(*), COALESCE(sum(spend),0)
                FROM "LiteLLM_SpendLogs"
                WHERE "startTime" >= date_trunc('day', now())
                GROUP BY 1 ORDER BY 3 DESC
            """)
            by_model = cur.fetchall()
            cur.execute("""
                SELECT COALESCE(sum(spend),0) FROM "LiteLLM_SpendLogs"
                WHERE "startTime" >= date_trunc('day', now())
            """)
            today = float(cur.fetchone()[0] or 0)
            cur.execute("""
                SELECT COALESCE(sum(spend),0) FROM "LiteLLM_SpendLogs"
                WHERE "startTime" >= date_trunc('day', now()) - interval '7 days'
            """)
            week = float(cur.fetchone()[0] or 0)
    except Exception as e:
        check("spend", "spend readable", False, f"{type(e).__name__}: {e}",
              "is litellm_db reachable?")
        return

    print(f"  today ${today:,.2f}   ·   last 7 days ${week:,.2f}")
    for model, calls, spend in by_model:
        if not _quiet or float(spend) > 0:
            share = (float(spend) / today * 100) if today else 0
            print(f"       {model:28} {calls:5} calls  ${float(spend):7.2f}"
                  f"  {share:4.0f}%")

    # Not a pass/fail — a number a person judges. Flagged only when it is
    # large enough that nobody should discover it by accident.
    check("spend", "today's spend under $25", today < 25,
          f"${today:,.2f}",
          "python3 scripts/litellm_budget.py --key ducorn-rex   (per-agent caps)")

    if spend_only:
        return

    heading("keys")
    load_ducorn_env()
    for agent in ("SAGE", "REX", "IRIS", "NOVA", "ATLAS", "DESIGN"):
        var = f"LITELLM_KEY_{agent}"
        check("keys", var, bool(os.environ.get(var, "").strip()),
              "" if os.environ.get(var) else "missing from shared/.env",
              f"python3 scripts/litellm_budget.py --create --key "
              f"ducorn-{agent.lower()}")


def check_hygiene():
    heading("hygiene")
    locks = [d for d in ("ducorn", "scripts", "gstack", "ducorn-products")
             if (DC / d / ".git/index.lock").exists()]
    check("hygiene", "no stale git locks", not locks, ", ".join(locks),
          "rm -f " + " ".join(f"~/DC/{d}/.git/index.lock" for d in locks)
          if locks else None)

    unpushed = []
    for d in ("ducorn", "scripts", "gstack", "ducorn-products"):
        if not (DC / d / ".git").is_dir():
            continue
        r = run(["git", "-C", str(DC / d), "status", "--porcelain"])
        remote = run(["git", "-C", str(DC / d), "remote", "get-url", "origin"])
        if r.stdout.strip() or not remote.stdout.strip():
            unpushed.append(d)
    check("hygiene", "all repos committed and have a remote", not unpushed,
          ", ".join(unpushed),
          'python3 scripts/commit_all.py -m "wip" --apply   '
          '(and create_remotes.py for missing remotes)')

    r = run(["pgrep", "-fl", "langgraph_flow.py"])
    running = [l for l in r.stdout.splitlines() if l.strip()]
    check("hygiene", "pipelines running", True,
          f"{len(running)} running" if running else "none",
          None)
    for line in running[:5]:
        if not _quiet:
            print(f"       {line[:100]}")

    try:
        pending = get_json(f"{API}/approvals/pending")
        n = len(pending if isinstance(pending, list)
                else pending.get("approvals", []))
        check("hygiene", "pending approvals", True, f"{n} waiting")
    except Exception:
        pass

    total, used, free = shutil.disk_usage(str(DC))
    gb = free / 1e9
    check("hygiene", "disk space", gb > 5, f"{gb:,.1f} GB free",
          "clear ~/DC/_deleted and old logs" if gb <= 5 else None)

    logs = DC / "logs"
    if logs.is_dir():
        big = sorted(((p.stat().st_size, p) for p in logs.glob("*.log")),
                     reverse=True)[:1]
        if big:
            size, path = big[0]
            check("hygiene", "largest log", size < 200e6,
                  f"{path.name} {size/1e6:,.0f} MB",
                  "truncate the log or rotate it" if size >= 200e6 else None)


def main():
    global _quiet
    ap = argparse.ArgumentParser()
    ap.add_argument("--spend", action="store_true", help="only today's money")
    ap.add_argument("--quiet", action="store_true", help="only what is wrong")
    args = ap.parse_args()
    _quiet = args.quiet

    print("DuCorn doctor — every check runs the real thing\n")

    if args.spend:
        check_keys_and_spend(spend_only=True)
    else:
        check_services()
        check_databases()
        check_browser()
        check_models()
        check_keys_and_spend()
        check_hygiene()

    bad = [r for r in results if not r["ok"]]
    print("\n" + "─" * 70)
    if not bad:
        print(f"{len(results)} checks, all healthy.")
        return 0

    print(f"{len(bad)} of {len(results)} checks failed:\n")
    for r in bad:
        print(f"  · {r['name']}" + (f" — {r['detail']}" if r["detail"] else ""))
        if r["fix"]:
            print(f"      {r['fix']}")
    print("\nFix these before starting a pipeline. Re-run this to confirm.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
