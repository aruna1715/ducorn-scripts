-- Design variants become first-class, viewable, and choosable.
--
-- Gate 2 previously posted a list of FILENAMES to Slack and asked for one
-- approve/reject over all of them. A founder could not see what they were
-- approving without opening files on the Mac, and there was no way to say
-- "variant 2" — so the gate approved a stage, not a design. node_build never
-- read the designs at all, which made the whole step decorative.
--
-- Three things this table makes possible:
--
--   1. One approval per variant, so approving IS choosing.
--   2. A capability URL per variant. Every API endpoint requires an x-api-key
--      header, and a link tapped from Slack on a phone cannot send one; the
--      API hostname has no Cloudflare Access policy either (that is why the
--      user chip forwards a client-asserted identity). A long random token in
--      the path is the honest mechanism: whoever holds the link can view that
--      one page, and nothing else. It expires.
--   3. A record of which design was chosen, so the build can implement it and
--      so the choice is still answerable a month later.

CREATE TABLE IF NOT EXISTS design_variants (
    id           SERIAL PRIMARY KEY,
    slug         TEXT        NOT NULL,
    variant_name TEXT        NOT NULL,
    archetype    TEXT,
    register     TEXT,
    path         TEXT        NOT NULL,
    -- secrets.token_urlsafe(32). Unguessable, and the ONLY thing it grants is
    -- GET on this one HTML file.
    view_token   TEXT        NOT NULL UNIQUE,
    expires_at   TIMESTAMPTZ NOT NULL,
    approval_id  INTEGER,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS design_variants_slug_idx  ON design_variants (slug);
CREATE INDEX IF NOT EXISTS design_variants_token_idx ON design_variants (view_token);

COMMENT ON COLUMN design_variants.view_token IS
    'Capability token for GET /d/<token>. Grants read of this one file and '
    'nothing else. Exempt from x-api-key because founders open these from '
    'Slack on a phone.';

-- Which variant the founder chose. NULL means gate 2 has not been passed.
ALTER TABLE pipeline_runs
    ADD COLUMN IF NOT EXISTS design_choice TEXT;

COMMENT ON COLUMN pipeline_runs.design_choice IS
    'Path of the approved design variant. node_build reads this and builds '
    'that UI. NULL for runs with no UI or not yet past gate 2.';

-- Approving one variant supersedes its siblings, which needs a status value
-- distinct from rejected — nobody rejected them, they just did not win.
ALTER TABLE approval_requests
    ADD COLUMN IF NOT EXISTS superseded_by INTEGER;

COMMENT ON COLUMN approval_requests.superseded_by IS
    'Set when a sibling approval was chosen instead. Distinct from rejected: '
    'these were not turned down, they lost a vote of one.';
