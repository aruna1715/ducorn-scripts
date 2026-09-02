"""
Where a product's things live. One definition, imported by everyone.

── WHY THIS EXISTS ──────────────────────────────────────────────────────────

Two files computed the same path independently:

    skill_runner.py       venv = d / ".venv";  py = venv / "bin" / "python"
    DuCornDeployTool.py   venv = product_dir / ".venv" / "bin" / "python"

They agree. Nothing made them agree, and nothing would notice if they stopped.
The invariant that matters — the interpreter a product is deployed under is the
interpreter its tests passed under — held by coincidence of two people writing
the same line twice.

Every serious bug in this pipeline this week was two copies of one fact drifting
apart: a gate's threshold and the instruction describing it, a status the code
wrote and the constraint that rejected it, a model the switcher held and the
model a caller used. This module is the fact, once.

Deliberately dependency-free and side-effect-free: it is imported by a launchd
job, by a CrewAI tool, and by a health check, and none of them should inherit
anything by importing it.
"""
from pathlib import Path

PRODUCTS_ROOT = Path("/Users/ducorn/DC/ducorn-products/products")
DOCS_ROOT = Path("/Users/ducorn/DC/ducorn-products/docs")
LOGS_ROOT = Path("/Users/ducorn/DC/logs")

VENV_DIR = ".venv"
SERVICE_MANIFEST = "service.json"


def product_dir(slug: str) -> Path:
    """The product's own directory. Everything below is relative to it."""
    return PRODUCTS_ROOT / slug


def product_venv(d) -> Path:
    """
    The product's virtualenv directory.

    QA creates it to install requirements.txt and run pytest; deploy starts the
    product from it. Same directory, one definition, so those two can never
    drift into testing one environment and running another.
    """
    return Path(d) / VENV_DIR


def product_python(d) -> Path:
    """
    The interpreter inside that virtualenv.

    May not exist — callers decide whether to build it (deploy does) or treat
    its absence as "not yet tested" (QA does). This says where it would be,
    not that it is there.
    """
    return product_venv(d) / "bin" / "python"


def has_product_python(d) -> bool:
    return product_python(d).is_file()


def requirements(d) -> Path:
    return Path(d) / "requirements.txt"


def service_manifest(d) -> Path:
    return Path(d) / SERVICE_MANIFEST


def doc(slug: str, suffix: str) -> Path:
    """A product document, e.g. doc('zz', 'PRD.md') -> docs/zz-PRD.md."""
    return DOCS_ROOT / f"{slug}-{suffix}"


def flow_log(slug: str) -> Path:
    return LOGS_ROOT / f"flow_{slug}.log"
