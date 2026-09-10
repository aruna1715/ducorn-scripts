#!/usr/bin/env python3
"""
What is about to enter git history — checked before it does.

    cd ~/DC && git add -A
    cd ~/DC && python3 scripts/git_audit.py     # exit 0 = safe to commit

Install as scripts/git_audit.py. Read-only: it stages nothing, commits
nothing, and changes no file. Exit 1 means do not commit yet.

── WHY THIS RUNS BEFORE THE FIRST COMMIT AND EVERY ONE AFTER ────────────────

Git history is append-only. `git rm` the file later and the value is still in
the history, still in every clone, still on every branch that ever had it.
The only real remedy for a committed credential is rotating it — this stack
already has seven credentials waiting on that, and none of them were in git.

.gitignore is the intent. This is the verification, and they are not the same
thing: a file that git ALREADY TRACKS keeps being tracked no matter what
.gitignore says. That is the specific way a secret survives a correct ignore
rule, and it is invisible unless something looks at the staged set.

── HOW IT DECIDES ───────────────────────────────────────────────────────────

By CONTENT, never by filename.

A filename rule blocked a legitimate .env.example in this project earlier —
the file held `ANTHROPIC_API_KEY=` with nothing after it, which is
documentation, and the check refused it for being called .env-something. The
inverse is worse: a real key in a file called config.py passes a filename
check completely.

So this reads values. `ANTHROPIC_API_KEY=` is fine. `ANTHROPIC_API_KEY=sk-ant-`
followed by forty characters is not. A placeholder — your-key-here, xxx,
CHANGEME, <redacted> — is fine, because that is what documenting the shape
looks like.

── WHAT IT CANNOT TELL YOU ──────────────────────────────────────────────────

Whether a value is live. It recognises credential SHAPES. A revoked key and a
working one look identical, so a hit is "look at this", not "you are
breached" — and a clean run means nothing matched these patterns, not that
the tree is certainly clean. Treat it as the floor, not the ceiling.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

WARN_BYTES = 5 * 1024 * 1024
BLOCK_BYTES = 90 * 1024 * 1024          # GitHub refuses a push over 100MB

# Credential SHAPES. Each must match a value, not a variable name.
PATTERNS = [
    ("Anthropic key",     re.compile(r"sk-ant-[A-Za-z0-9_\-]{24,}")),
    ("OpenAI/LiteLLM key", re.compile(r"\bsk-(?!ant-)[A-Za-z0-9_\-]{24,}")),
    ("Slack token",       re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("Slack webhook",     re.compile(r"hooks\.slack\.com/services/[A-Za-z0-9/]{20,}")),
    ("GitHub token",      re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})")),
    ("AWS access key",    re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Google API key",    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("DB URL with password",
     re.compile(r"\b(postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://"
                r"[^\s:/@]+:[^\s:/@]{6,}@")),
]

# A secret-shaped ASSIGNMENT: a credential-ish name given a real-looking value.
ASSIGN = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL)[A-Z0-9_]*)"
    r"\s*[:=]\s*[\"']?([^\s\"'#,;)]{16,})")

# What documentation looks like. A value matching any of these is a shape,
# not a secret — this is how .env.example stays committable.
#
# Applied to the CREDENTIAL-SHAPE matches as well as to assignments. The
# first version only filtered assignments, so `xoxb-your-token-here` and
# `postgres://user:CHANGEME@…` in a .env.example were both reported as live
# credentials. That is the precise false positive that got a legitimate
# .env.example blocked in this project before, and a checker that flags the
# documentation is one the operator learns to run with their eyes closed.
PLACEHOLDER = re.compile(
    r"(?i)(your[-_ ]|example|changeme|change[-_]me|placeholder|redacted|"
    r"dummy|sample|insert[-_]|replace[-_]|<[^>]*>|\.\.\.|xxx+|abc123|"
    r"^\$\{|^\$[A-Z_]+$|^os\.|^process\.env|^\*+$|^0+$|^none$|^null$|^true$|"
    r"^false$)")

# `KEY_NAME = "LITELLM_KEY_SAGE"` is a variable name being passed around, not
# a secret. Real tokens are mixed-case or base64; a bare screaming-snake
# identifier is a reference to one.
#
# SEPARATE, and deliberately NOT case-insensitive. Folded into PLACEHOLDER's
# (?i) group it became `[a-zA-Z][a-zA-Z0-9_]*` — "any identifier-shaped
# string" — and silently dismissed a live ghp_ GitHub token as documentation.
# A checker that reports nothing is indistinguishable from a clean tree, so
# that error is worse than the false positive it was meant to fix. It is also
# scoped to assignments only: a value matching a credential SHAPE is never
# waved through as a name.
NAME_REF = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")

TEXT_SUFFIX = {
    ".py", ".sh", ".zsh", ".bash", ".yaml", ".yml", ".json", ".toml", ".ini",
    ".cfg", ".conf", ".env", ".example", ".md", ".txt", ".js", ".ts", ".jsx",
    ".tsx", ".html", ".css", ".sql", ".plist", ".xml", ".properties", "",
}


def git(*args: str) -> str:
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed:\n{r.stderr.strip()}")
    return r.stdout


def staged_files() -> list:
    """Paths staged for the next commit, first commit included."""
    has_head = subprocess.run(["git", "rev-parse", "--verify", "HEAD"],
                              capture_output=True, text=True).returncode == 0
    if has_head:
        out = git("diff", "--cached", "--name-only", "--diff-filter=ACMR")
    else:
        # No HEAD yet: everything in the index is new.
        out = git("ls-files", "--cached")
    return [p for p in out.splitlines() if p.strip()]


def is_probably_text(path: Path) -> bool:
    if path.suffix.lower() in TEXT_SUFFIX:
        return True
    try:
        return b"\0" not in path.open("rb").read(4096)
    except OSError:
        return False


def line_hit(line: str):
    """
    (label, excerpt) if this line carries something credential-shaped.

    A named shape wins; a placeholder version of that shape is documentation
    and the OTHER patterns still get their turn. The earlier spelling used
    for/else and `break`, so one placebo match suppressed every remaining
    pattern AND the assignment check on that line.
    """
    for label, rx in PATTERNS:
        m = rx.search(line)
        if m and not PLACEHOLDER.search(m.group(0)):
            return label, m.group(0)[:12] + "…"

    m = ASSIGN.search(line)
    if m:
        name, val = m.group(1), m.group(2)
        if PLACEHOLDER.search(val) or NAME_REF.fullmatch(val):
            return None
        # A long value with no variety is a hash or a hex blob, not a
        # credential worth stopping a commit over.
        if len(set(val)) >= 8:
            return f"{name} has a real-looking value", val[:8] + "…"
    return None


def scan(path: Path) -> list:
    """[(line_no, label, excerpt)] for one file."""
    hits = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return hits
    for lineno, line in enumerate(text.splitlines(), start=1):
        got = line_hit(line[:4000])
        if got:
            hits.append((lineno, got[0], got[1]))
    return hits


def _mk(*parts: str) -> str:
    """
    Assemble a fixture credential at runtime.

    The fixtures are NOT written as literals, because this file is itself a
    file that gets committed and scanned. Spelled out, they made git_audit.py
    report five live credentials in git_audit.py — a checker failing on its
    own test data, which is the fourth time in this project that a check has
    read its own prose and called it a finding.

    Split across arguments, no single SOURCE LINE contains a contiguous
    credential shape, while the assembled value at runtime is exactly the
    shape the patterns must catch. The test gets its teeth; the file stays
    committable.
    """
    return "".join(parts)


_ANTHROPIC = _mk("sk-", "ant-", "api03-",
                 "7Kq2mZx9RtLvB4nWpYcE6HsJdF1gUaTiOhXbQ")
_GITHUB = _mk("ghp", "_", "9fK2mZxRvTnLwBcYeHdFaQpJ7sVgU3xNmB2r")
_SLACK = _mk("xoxb", "-", "4829174853-9271038475612-KpQmZxRvTnLwBcYeHdFa")
_LITELLM = _mk("sk-", "9fK2mZxRvTnLwBcYeHdFaQpJ7sVgU3")
_DBURL = _mk("postgresql://ducorn:", "s3cretP4ssw0rd", "@localhost:5432/dc")

SELFTEST = [
    # (line, should_be_flagged, why)
    (f"ANTHROPIC_API_KEY={_ANTHROPIC}", True,  "a live Anthropic key"),
    (f'TOKEN = "{_GITHUB}"',            True,  "a live GitHub token — this "
                                               "one was dismissed as a "
                                               "placeholder once"),
    (f"SLACK_BOT_TOKEN={_SLACK}",       True,  "a live Slack token"),
    (f"DATABASE_URL={_DBURL}",          True,  "a password in a DB URL"),
    (f"LITELLM_MASTER_KEY={_LITELLM}",  True,  "a live LiteLLM key"),
    ("ANTHROPIC_API_KEY=",              False, "a documented name"),
    ("SLACK_BOT_TOKEN=xoxb-your-token-here",
     False, "the .env.example shape that got blocked before"),
    ("LITELLM_MASTER_KEY=<your-master-key>", False, "an angle-bracket blank"),
    ("DATABASE_URL=postgresql://user:CHANGEME@localhost:5432/db",
     False, "a CHANGEME password"),
    ("API_TOKEN=${LITELLM_KEY_SAGE}",   False, "a variable reference"),
    ('KEY_NAME = "LITELLM_KEY_SAGE"',   False, "a variable NAME as a value"),
    ('PASSWORD = os.environ["DB_PASSWORD"]', False, "read from the env"),
    ('DIGEST = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"', False, "no variety"),
    ('MODEL = "claude-sonnet"',         False, "ordinary config"),
]


def selftest() -> int:
    bad = []
    for line, want, why in SELFTEST:
        got = line_hit(line) is not None
        if got != want:
            bad.append(f"{'MISSED' if want else 'FALSE ALARM ON'} {why}: "
                       f"{line[:60]}")
    print("git_audit selftest OK" if not bad
          else "git_audit selftest BAD\n  " + "\n  ".join(bad))
    return 0 if not bad else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()

    inside = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                            capture_output=True, text=True)
    if inside.returncode != 0:
        print("Not a git repository. `git init` first — and put .gitignore "
              "in place before `git add`.")
        return 1

    root = Path(git("rev-parse", "--show-toplevel").strip())
    files = staged_files()
    if not files:
        print("Nothing staged. `git add -A` first.")
        return 1

    print(f"auditing {len(files)} staged file(s) under {root}\n")

    # The specific failure .gitignore cannot fix on its own: a file git is
    # ALREADY TRACKING stays tracked, ignore rule or not.
    tracked_env = [f for f in files
                   if Path(f).name == ".env" or Path(f).name.startswith(".env.")
                   and not Path(f).name.endswith(".example")]
    secrets, big, huge = {}, [], []

    for rel in files:
        p = root / rel
        if not p.is_file():
            continue
        size = p.stat().st_size
        if size >= BLOCK_BYTES:
            huge.append((rel, size))
        elif size >= WARN_BYTES:
            big.append((rel, size))
        if size < 2 * 1024 * 1024 and is_probably_text(p):
            hits = scan(p)
            if hits:
                secrets[rel] = hits

    if tracked_env:
        print("❌ a real .env file is staged:")
        for f in tracked_env:
            print(f"     {f}")
        print("   .gitignore does not remove a file from the index. Run:")
        for f in tracked_env:
            print(f"     git rm --cached {f}")
        print()

    if secrets:
        print(f"❌ credential-shaped values in {len(secrets)} staged file(s):")
        for rel, hits in sorted(secrets.items()):
            print(f"   {rel}")
            for lineno, label, excerpt in hits[:6]:
                print(f"     line {lineno}: {label}  ({excerpt})")
            if len(hits) > 6:
                print(f"     … and {len(hits) - 6} more")
        print("\n   Each is a SHAPE match, so a placeholder can land here — "
              "look before you act.\n   If one is real: unstage the file, "
              "move the value into shared/.env, and\n   commit a .env.example "
              "showing the name with no value.\n")

    if huge:
        print("❌ files too large to push to most remotes:")
        for rel, size in huge:
            print(f"   {rel}  {size / 1e6:.0f} MB")
        print()

    if big:
        print("⚠️  large files, committable but worth a second look:")
        for rel, size in big:
            print(f"   {rel}  {size / 1e6:.1f} MB")
        print("   A build artifact or a dependency tree belongs in "
              ".gitignore, not history.\n")

    nested = [f for f in files if f.endswith("/.git") or "/.git/" in f]
    if nested:
        print(f"⚠️  {len(nested)} path(s) inside a nested .git directory are "
              f"staged — a product with its own repo should be a submodule or "
              f"be ignored.\n")

    if tracked_env or secrets or huge:
        print("Not safe to commit yet.")
        return 1

    total = sum((root / f).stat().st_size for f in files
                if (root / f).is_file())
    print(f"✅ {len(files)} files, {total / 1e6:.1f} MB, no credential shapes "
          f"and no oversized files.")
    print("   Shapes only — a clean run is the floor, not a guarantee.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
