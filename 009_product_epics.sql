-- 009_product_epics.sql
--
-- A product too big for one run, built in ordered phases.
--
-- ── WHY ─────────────────────────────────────────────────────────────────────
--
-- One pipeline run produces one product with one deliverable. There is no way
-- to say "this is phase 2, it continues phase 1", so anything larger than a
-- single run either does not get attempted or gets attempted as one enormous
-- run that fails somewhere in the middle with nothing to resume from.
--
-- The evidence for the size limit is DuCorn's own: a DOCUMENT — no code, no
-- tests, no deployment — took four QA attempts and $11 on its first try. The
-- full stack is fifteen services, four repos and two databases. That is not a
-- bigger version of the same task; it is a different task, and it needs the
-- work split into pieces each of which is the size of a thing this pipeline
-- has actually finished.
--
-- ── THE SHAPE ───────────────────────────────────────────────────────────────
--
-- An EPIC owns ONE product directory. Each PHASE is an ordinary pipeline run
-- with its own slug, its own gates and its own cost, that builds into that
-- same directory. Phase 2 does not copy phase 1's work; it continues it.
--
--     epic  ducorn-admin-rebuild   →  products/ducorn-admin-rebuild/
--       phase 1  ...-p1-config     pipeline_runs.slug, gates, cost
--       phase 2  ...-p2-services   same directory, depends on 1
--       phase 3  ...-p3-health     same directory, depends on 1,2
--
-- Deliberately NOT a directory per phase. Three directories would need phase 2
-- to copy phase 1's output before extending it, which is a merge step nobody
-- asked for and a second place for the product to exist.
--
-- ── WHAT THIS DOES NOT DO ───────────────────────────────────────────────────
--
-- No new execution machinery. A phase is started exactly the way any product
-- is started, and every gate, checkpoint, resume and budget check applies
-- unchanged. This migration only records what the phases ARE and what order
-- they go in.
--
-- ── HOW TO APPLY ────────────────────────────────────────────────────────────
--
--     python3 scripts/migrate.py --status
--     python3 scripts/migrate.py
--
-- NOT with `psql -f`. migrate.py opens the transaction and records the
-- schema_migrations row itself — 008 tried to do its own bookkeeping, hit
-- schema_migrations.name being NOT NULL, and rolled back entirely.

-- ── the epic ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS product_epics (
    id           SERIAL PRIMARY KEY,

    -- What a person calls it. Also the default product directory name.
    name         TEXT NOT NULL UNIQUE,

    -- The directory under ducorn-products/products/ that every phase builds
    -- into. Separate from `name` so an epic can be renamed without moving a
    -- directory that three finished phases have already written to.
    product_slug TEXT NOT NULL UNIQUE,

    -- The whole thing, in the founder's words. Each phase has its own brief;
    -- this is what they add up to, and it is what phase 1 is told it is part
    -- of.
    brief        TEXT,

    -- What KIND of product the finished thing is. Same vocabulary as
    -- pipeline_runs.product_type, and for the same reason: it decides which
    -- skills run. A phase inherits it unless it says otherwise, so a
    -- documentation phase inside a software epic is still possible.
    product_type TEXT,

    status       TEXT NOT NULL DEFAULT 'planned',
    created_at   TIMESTAMP NOT NULL DEFAULT now(),
    updated_at   TIMESTAMP NOT NULL DEFAULT now()
);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'product_epics_status_ck') THEN
        ALTER TABLE product_epics ADD CONSTRAINT product_epics_status_ck
            CHECK (status IN ('planned', 'running', 'complete',
                              'failed', 'abandoned'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'product_epics_product_type_ck') THEN
        ALTER TABLE product_epics ADD CONSTRAINT product_epics_product_type_ck
            CHECK (product_type IS NULL OR product_type IN
                   ('document', 'webpage', 'api', 'cli', 'software'));
    END IF;
END $$;

-- ── the phases ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS epic_phases (
    id           SERIAL PRIMARY KEY,
    epic_id      INTEGER NOT NULL
                 REFERENCES product_epics(id) ON DELETE CASCADE,

    -- 1, 2, 3 … the order they are meant to run in.
    seq          INTEGER NOT NULL,

    -- This phase's own pipeline_runs.slug.
    --
    -- NOT a foreign key, deliberately: the phases of an epic are defined
    -- before any of them runs, so the pipeline_runs row does not exist yet.
    -- A FK here would make planning an epic impossible until it had already
    -- started. Unique, so two phases cannot claim one run.
    phase_slug   TEXT NOT NULL UNIQUE,

    title        TEXT NOT NULL,
    brief        TEXT,

    -- Which earlier phases this one continues, by seq. Explicit rather than
    -- implied: "the previous one" is the common case but not the only one,
    -- and a phase that reads two earlier phases' work should say so where
    -- the jail can see it.
    --
    -- This is also the ONLY thing that widens the product jail: a phase may
    -- read the output of the phases named here, because they wrote into the
    -- same directory it is about to write into. It grants nothing across
    -- epics.
    depends_on   INTEGER[] NOT NULL DEFAULT '{}',

    status       TEXT NOT NULL DEFAULT 'pending',
    started_at   TIMESTAMP,
    completed_at TIMESTAMP,

    UNIQUE (epic_id, seq)
);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'epic_phases_status_ck') THEN
        ALTER TABLE epic_phases ADD CONSTRAINT epic_phases_status_ck
            CHECK (status IN ('pending', 'running', 'complete',
                              'failed', 'skipped'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS epic_phases_epic_seq_idx
    ON epic_phases (epic_id, seq);

-- ── comments, because the next person reads these before the code ───────────
COMMENT ON TABLE product_epics IS
    'A product built over several pipeline runs. One directory, many phases. '
    'See scripts/product_epics.py — the only place the consequences of these '
    'rows are defined.';

COMMENT ON COLUMN product_epics.product_slug IS
    'The directory under ducorn-products/products/ that every phase of this '
    'epic builds into. product_jail resolves a phase slug to THIS.';

COMMENT ON COLUMN epic_phases.phase_slug IS
    'The pipeline_runs.slug for this phase. Not a foreign key: phases are '
    'planned before they run, so the run row does not exist yet.';

COMMENT ON COLUMN epic_phases.depends_on IS
    'seq numbers of earlier phases in the SAME epic whose output this phase '
    'may read. The only sanctioned widening of the product jail; it never '
    'crosses an epic boundary.';

-- ── after applying ──────────────────────────────────────────────────────────
--   python3 scripts/product_epics.py --list
--   python3 scripts/prove_db_contracts.py
