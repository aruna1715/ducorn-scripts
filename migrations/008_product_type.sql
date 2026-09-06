-- 008_product_type.sql
--
-- Make "what kind of product is this" a recorded decision rather than
-- something four different functions each work out for themselves.
--
-- ── WHY ─────────────────────────────────────────────────────────────────────
--
-- The type was never stored. It was re-derived from PRD prose on every launch
-- and every resume, by two different algorithms that could disagree about the
-- same product between one phase and the next:
--
--     _infer_product_type()   regex, then a >=3 word-count heuristic
--     run_pipeline()          literal "**Type:** x", a different type list,
--                             in a different order
--
-- Meanwhile ui_test_coverage() decided the same question a third way — "are
-- there any .html files here" — and that was the one that could fail a run.
-- A finished document was failed three times for shipping no Playwright tests.
--
-- One column. Set when the run is created, read everywhere.
--
-- ── HOW TO APPLY ────────────────────────────────────────────────────────────
--
--     python3 scripts/migrate.py --status
--     python3 scripts/migrate.py
--
-- NOT with `psql -f`. scripts/migrate.py opens the transaction, applies this
-- file, and records the row in schema_migrations itself. The first version of
-- this migration did its own BEGIN/COMMIT and its own INSERT — which failed on
-- schema_migrations.name being NOT NULL and rolled the whole thing back. That
-- was a second copy of the runner's bookkeeping, written from memory instead
-- of read from the runner: the exact defect this column exists to end.

-- ── the column ──────────────────────────────────────────────────────────────
ALTER TABLE pipeline_runs
    ADD COLUMN IF NOT EXISTS product_type TEXT;

-- Constrained, so a typo in the wizard is a rejected insert rather than a
-- silent fall-through to "software" three phases later. NULL stays legal:
-- it means "nobody recorded one", which is a real state for a manual CLI run
-- and is handled explicitly in product_pathways.for_topic().
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'pipeline_runs_product_type_ck'
    ) THEN
        ALTER TABLE pipeline_runs
            ADD CONSTRAINT pipeline_runs_product_type_ck
            CHECK (product_type IS NULL OR product_type IN
                   ('document', 'webpage', 'api', 'cli', 'software'));
    END IF;
END $$;

COMMENT ON COLUMN pipeline_runs.product_type IS
    'document | webpage | api | cli | software. The recorded decision — see '
    'scripts/product_pathways.py, which is the only place the consequences of '
    'this value are defined. NULL means nobody recorded one (manual CLI run); '
    'the pathway is then inferred from the PRD and says so in the log.';

-- ── backfill what can be said with confidence ───────────────────────────────
--
-- Only from what the slug and has_ui already assert. Deliberately NOT running
-- the word-count heuristic here: guessing in a migration writes a guess into a
-- column whose whole purpose is to be a decision, and nobody would ever know
-- afterwards which rows were guessed. Anything left NULL is inferred at run
-- time, out loud, which is honest.

UPDATE pipeline_runs
   SET product_type = 'document'
 WHERE product_type IS NULL
   AND lower(coalesce(product_name, '') || ' ' || slug)
       ~ '(document|documentation|technical.reference)';

UPDATE pipeline_runs
   SET product_type = 'webpage'
 WHERE product_type IS NULL
   AND (has_ui IS TRUE
        OR lower(slug) ~ '(dashboard|landing.page|console)');

UPDATE pipeline_runs
   SET product_type = 'api'
 WHERE product_type IS NULL
   AND lower(slug) ~ '-api$';

-- Everything still NULL is left NULL on purpose. See the comment above.

-- ── after applying, look at what it did ─────────────────────────────────────
--   SELECT product_type, count(*) FROM pipeline_runs GROUP BY 1 ORDER BY 2 DESC;
--   SELECT slug, product_type FROM pipeline_runs
--    WHERE product_type IS NULL ORDER BY created_at DESC LIMIT 20;
