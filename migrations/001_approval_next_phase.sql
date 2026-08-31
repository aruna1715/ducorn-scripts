-- Record on each approval which pipeline phase it releases.
--
-- Until now slack_bot.cmd_approve worked out what to run next by matching the
-- approval's human-readable title:
--
--     elif "PRD Ready — approve to build:" in title:
--         ... "--phase", "build"
--
-- Three problems with that, all of which bit at once when a design gate was
-- added between PRD approval and build:
--
--   1. A new gate posts a title no branch matches, so approving it silently
--      does nothing at all. No error, no log line, the run just sits there.
--   2. Gate 1 hardcodes "--phase build", so it skips any node inserted after
--      it — the design step could never run even when the founder asked for a
--      UI.
--   3. Changing the wording of a Slack message breaks the pipeline. The
--      message is a human interface; it should not also be a control signal.
--
-- The node that raises an approval knows what should follow it. It writes that
-- here, and the approver reads it. Titles go back to being prose.
--
-- Nullable on purpose: approvals already pending when this is applied have no
-- value, and cmd_approve falls back to title matching for exactly those. Once
-- they drain, the fallback is dead code that can go.

-- product_slug goes in at the same time, for the same reason. cmd_approve
-- currently recovers the product by stripping the title's prefix:
--
--     topic = title.replace("PRD Ready — approve to build:", "").strip()
--
-- which is the same fragility one layer down: a product whose name contains
-- the prefix, or a reworded message, and the pipeline runs against the wrong
-- slug or none. The node knows the slug; it should write it down.

ALTER TABLE approval_requests
    ADD COLUMN IF NOT EXISTS next_phase   TEXT,
    ADD COLUMN IF NOT EXISTS product_slug TEXT;

COMMENT ON COLUMN approval_requests.next_phase IS
    'Pipeline phase to start when this approval is granted (e.g. design, '
    'build, launch, deploy). NULL for approvals created before 2026-08-31 or '
    'for approvals that release nothing.';

COMMENT ON COLUMN approval_requests.product_slug IS
    'pipeline_runs.slug this approval belongs to. NULL only for approvals '
    'created before 2026-08-31, where it is parsed back out of the title.';

-- Pending approvals are found by status on every Slack poll.
CREATE INDEX IF NOT EXISTS approval_requests_pending_idx
    ON approval_requests (status)
    WHERE status = 'pending';
