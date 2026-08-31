"""
Where a DuCorn document belongs in Google Drive.

WHY THIS EXISTS
---------------
gdrive_sync.py had a FOLDER_MAP: a hand-maintained list of filename patterns
from the P001 era, ending in

    ("*", f"{DRIVE_ROOT}/Company")

Every product built after P001 matched none of the patterns and fell into that
catch-all. That is why ~35 PDFs — real products, throwaway test runs and seven
near-identical dashboard PRDs — are sitting in one flat DuCorn/Company folder.
Nothing ever failed. The catch-all always succeeded.

So the fix is not to add more patterns; the list would drift again on the next
product. Routing derives from what the file IS:

  * a pipeline artifact (PRD, QA report, gstack report, launch, design, skill
    output) is named "<slug>-<doctype>", so the slug decides the folder
  * a standing company document is named for itself and keeps an explicit map,
    because there are few of them and they do not multiply per product
  * anything else goes to DuCorn/Inbox

That last rule is the point. Inbox is deliberately not a sensible destination:
an unrouted file should look wrong so somebody notices, which is exactly what
the old catch-all prevented for two months.
"""
import re

DRIVE_ROOT = "DuCorn"

# ── Pipeline artifact suffixes ───────────────────────────────────────────────
# A file ending in one of these was produced by a pipeline run, so the text
# before it is the product slug. Longest first: "-skill01-prd-analysis" must be
# tried before "-prd-analysis" would be, or the slug would keep a fragment.
DOCTYPES = [
    "-skill01-prd-analysis",
    "-skill02-design-consultation",
    "-skill03-design-review",
    "-skill04-build",
    "-skill05-code-review",
    "-skill06-qa-run-test",
    "-gstack-report",
    "-code-review",
    "-qa-report",
    "-design",
    "-launch",
    "-prd",
]

# ── Standing company documents ───────────────────────────────────────────────
# These are not products and never will be. Small, stable, explicitly listed.
COMPANY_DOCS = [
    (r"^week\d*-completion-report",     "Company/Weekly Reports"),
    (r"^atlas-prd-bb-",                 "Company/Board Documents"),
    (r"^atlas-prd-001-board-summary",   "Company/Board Documents"),
    (r"^ducorn-technical-reference$",   "Company/Technical Reference"),
    (r"^ducorn-technical-reference-v",  "Company/Technical Reference"),
    (r"^ducorn-stack-context",          "Company/Technical Reference"),
    (r"^atlas-marketing-",              "Marketing"),
    (r"^gstack-\d+",                    "Company/Technical Reference"),
    (r"^ducorn-global-gtm",             "Research/GTM"),
    (r"^ducorn-gtm",                    "Research/GTM"),
    (r"^ducorn-digest-improvements",    "Research"),
    (r"^voice-ai-performance-test",     "Research"),
    (r"^kpis$",                         "KPIs"),
]

# ── Throwaway runs ───────────────────────────────────────────────────────────
# Runs made to exercise the pipeline, not to build something anyone will use.
#
# This list is deliberately SHORT, and it got shorter on 31 Aug 2026. The first
# draft also matched ducorn-stack-health-check and ducorn-e2e-verify-aug25, and
# Vijay corrected both: they are named after what they verify, but they are real
# products. I had been reading intent out of filenames and was wrong about two
# of the three calls I put up for review.
#
# So the rule now is: only a name that says "test" in so many words, or a
# hello-world scaffold, counts. Everything else goes to Products, where a
# wrongly-filed real product is visible rather than buried in an archive nobody
# opens. pipeline_runs.environment is the real answer and is authoritative
# wherever it is set — do not extend this list for new runs, set the environment
# on the run instead.
TEST_PATTERNS = [
    r"^test-",
    r"-test-",
    r"^pipeline-test-",
    r"^lg-hello-world$",
    r"^hello-langgraph$",
]

# ── Superseded drafts ────────────────────────────────────────────────────────
# Not tests — earlier versions of something real. ducorn-pipeline-dashboard was
# iterated v5..v10, which is one product with six surviving drafts, not six
# products. They go to Archive/Superseded so Products shows the current thing
# without pretending the drafts were throwaway.
SUPERSEDED = r"^(ducorn-pipeline-dashboard)-v\d+[a-z]?$"

# ── Slug rewrites ────────────────────────────────────────────────────────────
# Applied after the slug is split, before the folder is chosen. Two reasons a
# rewrite is needed, both historical:
#
#   * the same product was run under two names (P001- prefix, then the slug)
#   * one product was iterated as v5..v10, which is one product with seven
#     attempts, not seven products — collapsing them means Archive holds one
#     folder rather than seven near-identical ones
#
# A deliberate list, not a pattern: merging two products that only LOOK alike
# would silently lose one. Note there is no rewrite for
# ducorn-autonomy-console-v2 — a v2 is a real successor product, and an earlier
# draft of these rules swept it into Archive as a "test", which is precisely
# the kind of plausible-looking wrong answer a dry run is for.
SLUG_ALIASES = {
    "p001-autonomy-console": "ducorn-autonomy-console",
    # One product run twice under two names, because the second run needed to
    # not re-use the first one's PRD. Confirmed by Vijay 31 Aug 2026. If the
    # other name is the keeper, swap the two sides of this line.
    "ducorn-pipeline-run-history": "ducorn-run-history",
}

# What this router has an opinion about. The first dry run tried to move
# index.html, main.py and main_flow.py out of a "DuCorn QA" folder and into
# Inbox — source files a person had put somewhere on purpose. Routing rules
# derived from document naming have nothing useful to say about those, so they
# are left exactly where they are.
ROUTABLE = (".pdf", ".json")

# Files that should never reach Drive at all.
EXCLUDE = [
    r"\.backup-",     # the escape-repair sweep writes these beside the source
    r"\.stale-",
    r"^~\$",
    r"^\.",
]


def _stem(filename):
    """'ducorn-cost-tracker-PRD.pdf' -> 'ducorn-cost-tracker-prd'"""
    return re.sub(r"\.(md|pdf|json)$", "", filename, flags=re.I).lower()


def excluded(filename):
    s = filename.lower()
    return any(re.search(p, s) for p in EXCLUDE)


def split_slug(filename):
    """
    Return (slug, doctype) for a pipeline artifact, or (None, None).
    """
    s = _stem(filename)
    for dt in DOCTYPES:
        if s.endswith(dt):
            return s[: -len(dt)], dt.lstrip("-")
    return None, None


def is_test(slug, environment=None):
    """
    Name patterns only. `environment` is accepted and deliberately IGNORED.

    An earlier version of this treated pipeline_runs.environment as
    authoritative, on the reasoning that the run recorded it and I was only
    guessing from filenames. The first dry run against real Drive contents
    showed what that actually does: daily-standup-bot, ducorn-run-history,
    ducorn-stack-health-check and ducorn-e2e-verify-aug25 all went to
    Archive/Tests, and Vijay had explicitly said the last two are real.

    The column does not mean what I took it to mean. environment=test records
    that a run used LOCAL MODELS — the TEST/PRODUCTION toggle on the dashboard,
    which exists to control spend. Nearly every run is environment=test because
    nearly every run was deliberately cheap. It says how the run was executed,
    not whether the product is real. Those are different questions and I
    collapsed them.

    So: nothing in the database currently answers "was this throwaway". Until
    something does, only a name that says so counts, and everything else stays
    in Products where a mistake is visible.
    """
    return any(re.search(p, slug) for p in TEST_PATTERNS)


def route(filename, environments=None):
    """
    Returns (drive_path, reason). reason is printed in the dry run so the
    classification can be argued with before 35 files move.

    environments: optional {slug: environment} read from pipeline_runs.
    """
    if excluded(filename):
        return None, "excluded — working file, not a document"
    if not filename.lower().endswith(ROUTABLE) and not filename.lower().endswith(".md"):
        return None, "not a document — left where it is"

    s = _stem(filename)
    environments = environments or {}

    # Company documents are checked FIRST. gstack-05-code-review ends in a
    # pipeline doctype and would otherwise be filed as a product called
    # "gstack-05", which does not exist.
    for pattern, folder in COMPANY_DOCS:
        if re.search(pattern, s):
            return f"{DRIVE_ROOT}/{folder}", "standing company document"

    slug, doctype = split_slug(filename)
    if slug:
        env = environments.get(slug)
        folder_slug = SLUG_ALIASES.get(slug, slug)
        superseded = re.match(SUPERSEDED, folder_slug)
        if superseded:
            folder_slug = superseded.group(1)
        why = f" -> filed under {folder_slug}" if folder_slug != slug else ""

        if is_test(slug, env):
            return (f"{DRIVE_ROOT}/Archive/Tests/{folder_slug}",
                    f"{doctype} for {slug} (named as a test run)")
        if superseded:
            return (f"{DRIVE_ROOT}/Archive/Superseded/{folder_slug}",
                    f"{doctype} for {slug} (superseded draft{why})")
        return f"{DRIVE_ROOT}/Products/{folder_slug}", f"{doctype} for {slug}{why}"

    # No catch-all. An unrouted file is a fact worth seeing.
    return f"{DRIVE_ROOT}/Inbox", "UNROUTED — no product slug, no company match"


def load_environments(database_url="postgresql://localhost/ducorn"):
    """
    {slug: environment} from pipeline_runs. Returns {} if the DB cannot be
    reached — routing then falls back to the name patterns, which is worse but
    still far better than one flat folder.
    """
    try:
        import psycopg2
        with psycopg2.connect(database_url) as conn, conn.cursor() as cur:
            cur.execute("SELECT slug, environment FROM pipeline_runs "
                        "WHERE slug IS NOT NULL")
            return {r[0]: r[1] for r in cur.fetchall() if r[0]}
    except Exception as e:
        print(f"[drive_routing] could not read pipeline_runs ({e}) — "
              f"classifying from filenames only")
        return {}
